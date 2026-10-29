"""Orquesta la validacion previa offline y el puerto opcional de Pre-Flight."""

from collections.abc import Sequence
from ipaddress import IPv4Address
from typing import Any, Protocol

from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.domain.errors import PreValidationFailedError
from intentfabric.domain.intent import AccessHop, ProviderEdgeHop, TransitHop
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey
from intentfabric.domain.topology import TopologyCatalog
from intentfabric.domain.validation import (
    ValidationIssue, ValidationReport, ValidationSeverity, ValidationStage,
)


class PreFlightCheckerPort(Protocol):
    """Define el chequeo online mediante hallazgos de Pre-Flight."""

    def check_preflight(self, intent: Any) -> Sequence[ValidationIssue]:
        """Devuelve hallazgos de la subfase PREFLIGHT_ONLINE para la intencion."""
        ...


class NoOpPreFlightChecker:
    """Representa la omision de Pre-Flight sin conexiones externas."""

    def check_preflight(self, intent: Any) -> tuple[ValidationIssue, ...]:
        """Devuelve una tupla vacia sin consultar dispositivos."""
        return ()


class PreValidationService:
    """Acumula errores estaticos antes de permitir el chequeo online."""

    def __init__(
        self, catalog: PluginCatalog, preflight_checker: PreFlightCheckerPort | None = None,
        topology: TopologyCatalog | None = None,
    ) -> None:
        self._catalog = catalog
        self._topology = topology
        self._preflight_checker = (
            NoOpPreFlightChecker() if preflight_checker is None else preflight_checker
        )

    def validate(
        self, intent: Any, *, operations: Sequence[str] = ("provision", "teardown"),
        variant: str = "default",
    ) -> ValidationReport:
        """Acumula hallazgos y ejecuta Pre-Flight solo si la subfase estatica no tiene errores."""
        issues = list(self._validate_static(intent, operations, variant))
        has_errors = any(issue.severity == ValidationSeverity.ERROR for issue in issues)
        preflight_executed = False
        if not has_errors and not isinstance(self._preflight_checker, NoOpPreFlightChecker):
            issues.extend(self._preflight_checker.check_preflight(intent))
            preflight_executed = True
        return ValidationReport(
            service_id=getattr(intent, "service_id", None) or intent.description,
            service_type=intent.service_type, issues=tuple(issues),
            preflight_executed=preflight_executed,
        )

    def require_valid(self, report: ValidationReport) -> None:
        """Interrumpe el flujo con el reporte completo si existe algun error."""
        if not report.is_valid:
            raise PreValidationFailedError(report)

    def validate_and_require(
        self, intent: Any, *, operations: Sequence[str] = ("provision", "teardown"),
        variant: str = "default",
    ) -> ValidationReport:
        """Valida la intencion y devuelve el reporte solo si permite continuar."""
        report = self.validate(intent, operations=operations, variant=variant)
        self.require_valid(report)
        return report

    def _validate_static(
        self, intent: Any, operations: Sequence[str], variant: str,
    ) -> tuple[ValidationIssue, ...]:
        issues = list(_validate_path(intent))
        if self._topology is not None:
            issues.extend(_validate_topology(intent, self._topology))
        if intent.service_type not in self._catalog.service_types():
            issues.append(ValidationIssue(
                code="UNSUPPORTED_SERVICE",
                message=f"service_type: registre un parser para {intent.service_type!r}.",
                stage=ValidationStage.STATIC_OFFLINE, field_path="service_type",
            ))
        for index, hop in enumerate(_intent_hops(intent)):
            if hop.vendor not in self._catalog.vendor_ids():
                issues.append(ValidationIssue(
                    code="UNSUPPORTED_VENDOR",
                    message=f"vendor: registre el fabricante {hop.vendor!r} del salto.",
                    stage=ValidationStage.STATIC_OFFLINE,
                    field_path=f"hops[{index}].vendor", node_id=_node_identifier(hop),
                ))
        issues.extend(self._validate_template_coverage(intent, operations, variant))
        issues.extend(self._catalog.validate_semantics(intent))
        return tuple(issues)

    def _validate_template_coverage(
        self, intent: Any, operations: Sequence[str], variant: str,
    ) -> tuple[ValidationIssue, ...]:
        if intent.service_type not in self._catalog.service_types():
            return ()
        issues: list[ValidationIssue] = []
        for index, hop in enumerate(_intent_hops(intent)):
            role = _hop_role(hop)
            if hop.vendor not in self._catalog.vendor_ids() or role is None:
                continue
            for operation in operations:
                try:
                    key_operation = Operation(operation)
                except ValueError:
                    key_operation = None
                if key_operation is None or not self._catalog.supports(
                    hop.vendor, TemplateKey(intent.service_type, key_operation, role, variant),
                ):
                    issues.append(ValidationIssue(
                        code="MISSING_TEMPLATE_KEY",
                        message=(
                            f"Declare la plantilla {hop.vendor}/{intent.service_type}/"
                            f"{operation}/{role.value}/{variant} antes de continuar."
                        ),
                        stage=ValidationStage.STATIC_OFFLINE,
                        field_path=f"hops[{index}].role", node_id=_node_identifier(hop),
                    ))
        return tuple(issues)


def _node_identifier(hop: Any) -> str:
    return (
        getattr(hop, "node_id", None) or getattr(hop, "hostname", None)
        or str(hop.management_ip)
    )


def _intent_hops(intent: Any) -> tuple[AccessHop | TransitHop | ProviderEdgeHop, ...]:
    return (intent.access, *intent.transits, intent.provider_edge)


def _hop_role(hop: Any) -> NodeRole | None:
    if isinstance(hop, AccessHop):
        return NodeRole.ACCESS
    if isinstance(hop, TransitHop):
        return NodeRole.TRANSIT
    if isinstance(hop, ProviderEdgeHop):
        return NodeRole.PROVIDER_EDGE
    return None


def _validate_path(intent: Any) -> tuple[ValidationIssue, ...]:
    hops = _intent_hops(intent)
    expected_roles = (
        NodeRole.ACCESS, *(NodeRole.TRANSIT for _ in intent.transits), NodeRole.PROVIDER_EDGE,
    )
    issues: list[ValidationIssue] = []
    if tuple(_hop_role(hop) for hop in hops) != expected_roles:
        issues.append(ValidationIssue(
            code="INVALID_PATH_ROLE_ORDER",
            message="hops: utilice AccessHop, cero o mas TransitHop y ProviderEdgeHop en ese orden.",
            stage=ValidationStage.STATIC_OFFLINE, field_path="hops",
        ))
    seen_addresses: set[IPv4Address] = set()
    seen_node_ids: set[str] = set()
    for index, hop in enumerate(hops):
        if hop.node_id in seen_node_ids:
            issues.append(ValidationIssue(
                code="DUPLICATE_NODE_HOP",
                message="node_id: cada salto de la ruta debe tener una identidad distinta.",
                stage=ValidationStage.STATIC_OFFLINE,
                field_path=f"hops[{index}].node_id", node_id=hop.node_id,
            ))
        seen_node_ids.add(hop.node_id)
        if hop.management_ip in seen_addresses:
            issues.append(ValidationIssue(
                code="DUPLICATE_MANAGEMENT_IP",
                message="management_ip: cada salto de la ruta debe tener una direccion distinta.",
                stage=ValidationStage.STATIC_OFFLINE,
                field_path=f"hops[{index}].management_ip", node_id=_node_identifier(hop),
            ))
        seen_addresses.add(hop.management_ip)
    return tuple(issues)


def _hop_interfaces(hop: AccessHop | TransitHop | ProviderEdgeHop) -> tuple[tuple[str, str], ...]:
    if isinstance(hop, AccessHop):
        return (("customer_port", hop.customer_port), ("uplink_interface", hop.uplink_interface))
    if isinstance(hop, TransitHop):
        return (("downstream_interface", hop.downstream_interface), ("upstream_interface", hop.upstream_interface))
    if isinstance(hop, ProviderEdgeHop):
        return (("parent_interface", hop.parent_interface),)
    return ()


def _validate_topology(intent: Any, topology: TopologyCatalog) -> tuple[ValidationIssue, ...]:
    issues: list[ValidationIssue] = []
    hops = _intent_hops(intent)
    for index, hop in enumerate(hops):
        node = topology.find_node(hop.node_id)
        if node is None:
            issues.append(ValidationIssue(
                code="TOPOLOGY_NODE_NOT_FOUND", message="node_id: registre el nodo en el inventario.",
                stage=ValidationStage.STATIC_OFFLINE,
                field_path=f"hops[{index}].node_id", node_id=hop.node_id,
            ))
            continue
        if (hop.vendor, _hop_role(hop), hop.management_ip) != (node.vendor, node.role, node.management_ip):
            issues.append(ValidationIssue(
                code="TOPOLOGY_NODE_ATTRIBUTE_MISMATCH",
                message="hops: vendor, rol y management_ip deben coincidir con el inventario.",
                stage=ValidationStage.STATIC_OFFLINE, field_path=f"hops[{index}]", node_id=hop.node_id,
            ))
        if isinstance(hop, AccessHop) and any(
            hop.customer_port == local_interface
            for _, local_interface, _ in topology.neighbors_of(hop.node_id)
        ):
            issues.append(ValidationIssue(
                code="TOPOLOGY_CLIENT_INTERFACE_IS_TRUNK",
                message="customer_port: utilice un puerto libre de enlaces troncales en el inventario.",
                stage=ValidationStage.STATIC_OFFLINE,
                field_path=f"hops[{index}].customer_port", node_id=hop.node_id,
            ))
        for attribute, interface in _hop_interfaces(hop):
            if interface not in node.interfaces:
                issues.append(ValidationIssue(
                    code="TOPOLOGY_INTERFACE_NOT_FOUND",
                    message=f"{attribute}: utilice una interfaz declarada en el inventario del nodo.",
                    stage=ValidationStage.STATIC_OFFLINE,
                    field_path=f"hops[{index}].{attribute}", node_id=hop.node_id,
                ))
    for index, (current_hop, next_hop) in enumerate(zip(hops, hops[1:])):
        outgoing = getattr(current_hop, "uplink_interface", getattr(current_hop, "upstream_interface", None))
        incoming = getattr(next_hop, "downstream_interface", getattr(next_hop, "parent_interface", None))
        link = topology.find_link_between(current_hop.node_id, next_hop.node_id)
        if link is None or link != (outgoing, incoming):
            issues.append(ValidationIssue(
                code="TOPOLOGY_LINK_NOT_FOUND",
                message="hops: los saltos consecutivos deben utilizar los puertos del enlace inventariado.",
                stage=ValidationStage.STATIC_OFFLINE, field_path=f"hops[{index}]", node_id=current_hop.node_id,
            ))
    return tuple(issues)
