"""Garantiza reportes inmutables y acumulativos de validacion previa."""

from collections.abc import Sequence
from dataclasses import FrozenInstanceError, dataclass, replace
from ipaddress import IPv4Address, IPv4Network
from itertools import permutations
import json
from typing import Any, ClassVar

import pytest

from intentfabric.application import NoOpPreFlightChecker, PreFlightCheckerPort, PreValidationService
from intentfabric.application.plugin_catalog import PluginCatalog, SemanticValidator
from intentfabric.bootstrap import build_plugin_catalog
from intentfabric.domain import (
    IntentFabricError, PreValidationFailedError, ValidationIssue,
    ValidationReport, ValidationSeverity, ValidationStage,
)
from intentfabric.domain.errors import (
    IntentParseError, PluginConsistencyError, PluginRegistrationError,
    TemplateNotFoundError, UnsupportedCombinationError,
)
from intentfabric.domain.intent import AccessHop, DiaIntent, ProviderEdgeHop, TransitHop
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey
from intentfabric.domain.vendor_definition import VendorDefinition
from intentfabric.services.dia import validate_dia_intent_semantics
from intentfabric.services.dia.intent_parser import DiaIntentParser


def _issue(**overrides: Any) -> ValidationIssue:
    fields = {
        "code": "UNSUPPORTED_VENDOR",
        "message": "Registre un vendor soportado para el salto.",
        "stage": ValidationStage.STATIC_OFFLINE,
    }
    return ValidationIssue(**(fields | overrides))


def _dia_intent() -> DiaIntent:
    return DiaIntent(
        description="LAB-DIA-001", vlan_id=3001, vrf_name="LAB-INTERNET",
        wan_network=IPv4Network("198.51.100.0/30"),
        lan_network=IPv4Network("203.0.113.0/29"), bandwidth_mbps=50,
        qos_policy_name="LAB_50MB_PARENT",
        access=AccessHop("huawei", IPv4Address("192.0.2.11"), "port", "uplink"),
        transits=(TransitHop("cisco", IPv4Address("192.0.2.12"), "down", "up"),),
        provider_edge=ProviderEdgeHop("huawei", IPv4Address("192.0.2.21"), "parent"),
    )


def _supported_catalog(
    *, validator: SemanticValidator | None = validate_dia_intent_semantics,
    omitted: tuple[TemplateKey, ...] = (), variant: str = "default",
    vendor_order: tuple[str, ...] = ("cisco", "huawei"),
) -> PluginCatalog:
    catalog = PluginCatalog()
    for vendor_id in vendor_order:
        catalog.register_vendor(VendorDefinition(vendor_id, {
            TemplateKey("DIA", operation, role, variant): (
                f"templates/dia/{operation.value}/{role.value}.j2"
            )
            for operation in Operation for role in NodeRole
            if TemplateKey("DIA", operation, role, variant) not in omitted
        }))
    catalog.register_service(DiaIntentParser(catalog.vendor_ids()))
    if validator is not None:
        catalog.register_service_validator("DIA", validator)
    return catalog


class _PreFlightChecker:
    def __init__(self, issues: Sequence[ValidationIssue] = ()) -> None:
        self.issues = issues
        self.call_count = 0
        self.intents: list[DiaIntent] = []

    def check_preflight(self, intent: DiaIntent) -> Sequence[ValidationIssue]:
        """Registra la llamada y devuelve los hallazgos operativos previstos."""
        self.call_count += 1
        self.intents.append(intent)
        return self.issues


@dataclass(frozen=True)
class _IdentifiedIntent(DiaIntent):
    service_id: str | None = None


@dataclass(frozen=True)
class _IdentifiedAccess(AccessHop):
    node_id: str | None = None
    hostname: str | None = None


class _UnsupportedIntent(DiaIntent):
    service_type: ClassVar[str] = "LAB"


@pytest.mark.parametrize("code", [None, 3, "", " \n\t", "lower_case", "BAD-CODE", " BAD", "1_BAD"])
def test_issue_rejects_invalid_codes(code: object) -> None:
    """Rechaza codigos vacios o ajenos al formato UPPER_SNAKE_CASE."""
    with pytest.raises(ValueError, match="code:"):
        _issue(code=code)


@pytest.mark.parametrize("message", [None, 3, "", " \n\t"])
def test_issue_rejects_empty_or_non_text_messages(message: object) -> None:
    """Exige un mensaje textual no vacio para cada hallazgo."""
    with pytest.raises(ValueError, match="message:"):
        _issue(message=message)


def test_issue_preserves_taxonomy_and_default_severity() -> None:
    """Conserva los campos de entrada y asigna ERROR por defecto."""
    issue = _issue(code="VLAN_802_1Q", field_path="vlan_id", node_id="LAB-PE")
    assert issue.severity is ValidationSeverity.ERROR
    assert issue.sort_key() == ("static_offline", "error", "VLAN_802_1Q", "LAB-PE", "vlan_id")
    assert _issue().sort_key() == ("static_offline", "error", "UNSUPPORTED_VENDOR", "", "")
    assert ValidationStage.PREFLIGHT_ONLINE.value == "preflight_online"
    assert ValidationSeverity.WARNING.value == "warning"


@pytest.mark.parametrize("model", [_issue(), ValidationReport("LAB-001", "DIA", ())])
def test_validation_models_are_frozen_and_slotted(
    model: ValidationIssue | ValidationReport,
) -> None:
    """Impide mutar campos y agregar atributos a los modelos de validacion."""
    field = "code" if isinstance(model, ValidationIssue) else "service_id"
    with pytest.raises(FrozenInstanceError):
        setattr(model, field, "CHANGED")
    assert not hasattr(model, "__dict__")


def test_report_canonically_orders_every_sort_dimension() -> None:
    """Ordena por subfase, severidad, codigo, nodo y campo sin depender de la insercion."""
    expected = (
        _issue(stage=ValidationStage.PREFLIGHT_ONLINE),
        _issue(code="DUPLICATE_NODE_HOP"),
        _issue(node_id="LAB-A", field_path="hops[0]"),
        _issue(node_id="LAB-A", field_path="hops[1]"),
        _issue(node_id="LAB-B"),
        _issue(severity=ValidationSeverity.WARNING),
    )
    serialized = json.dumps(ValidationReport("LAB-001", "DIA", expected).to_dict())
    for issue_order in permutations(expected):
        report = ValidationReport("LAB-001", "DIA", issue_order)
        assert report.issues == expected
        assert json.dumps(report.to_dict()) == serialized


def test_report_filters_errors_and_warnings_in_canonical_order() -> None:
    """Clasifica todos los hallazgos y solo considera invalidantes los errores."""
    error = _issue()
    warning = _issue(code="CHECK_POLICY", severity=ValidationSeverity.WARNING)
    report = ValidationReport("LAB-001", "DIA", (warning, error))
    assert report.errors == (error,)
    assert report.warnings == (warning,)
    assert not report.is_valid
    assert not report.preflight_executed
    assert ValidationReport("LAB-001", "DIA", (warning,)).is_valid
    assert ValidationReport("LAB-001", "DIA", ()).is_valid


def test_report_orders_messages_when_taxonomy_and_location_match() -> None:
    """Resuelve empates de la clave canonica sin depender del orden de llegada."""
    first = _issue(message="Declare la plantilla provision.")
    second = _issue(message="Declare la plantilla teardown.")
    assert first.sort_key() == second.sort_key()
    for issue_order in [(first, second), (second, first)]:
        assert ValidationReport("LAB-001", "DIA", issue_order).issues == (first, second)


@pytest.mark.parametrize("error_type", [
    IntentParseError, PluginConsistencyError, PluginRegistrationError,
    TemplateNotFoundError, UnsupportedCombinationError,
])
def test_existing_errors_inherit_the_framework_base(error_type: type[Exception]) -> None:
    """Conserva compatibilidad con Exception y permite capturar errores del framework."""
    assert issubclass(error_type, IntentFabricError)
    assert issubclass(error_type, Exception)


def test_pre_validation_error_preserves_the_report_and_error_codes() -> None:
    """Expone el reporte original y detalla servicio y errores en el mensaje."""
    warning = _issue(code="CHECK_POLICY", severity=ValidationSeverity.WARNING)
    report = ValidationReport("LAB-001", "DIA", (_issue(), warning))
    error = PreValidationFailedError(report)
    assert isinstance(error, IntentFabricError)
    assert error.report is report
    assert "LAB-001" in str(error)
    assert "['UNSUPPORTED_VENDOR']" in str(error)
    assert "CHECK_POLICY" not in str(error)


def test_report_serializes_explicit_values_and_fixed_field_order() -> None:
    """Expone conteos, subfase ejecutada y campos completos en orden fijo."""
    issue = _issue(field_path="hops[0].vendor", node_id="LAB-A")
    report = ValidationReport("LAB-001", "DIA", (issue,), preflight_executed=True)
    serialized = report.to_dict()
    assert list(serialized) == [
        "service_id", "service_type", "is_valid", "preflight_executed",
        "error_count", "warning_count", "issues",
    ]
    assert serialized == {
        "service_id": "LAB-001", "service_type": "DIA", "is_valid": False,
        "preflight_executed": True, "error_count": 1, "warning_count": 0,
        "issues": [{
            "code": "UNSUPPORTED_VENDOR", "message": issue.message,
            "stage": "static_offline", "severity": "error",
            "field_path": "hops[0].vendor", "node_id": "LAB-A",
        }],
    }
    assert list(serialized["issues"][0]) == [
        "code", "message", "stage", "severity", "field_path", "node_id",
    ]
    serialized["issues"].clear()
    assert report.issues == (issue,)


@pytest.mark.parametrize("vlan_id", [-1, 0, 4095])
def test_dia_rejects_vlans_outside_the_service_range(vlan_id: int) -> None:
    """Rechaza VLAN fuera de 1..4094 aunque la intencion se construya en memoria."""
    issues = validate_dia_intent_semantics(replace(_dia_intent(), vlan_id=vlan_id))
    assert len(issues) == 1
    assert issues[0].code == "INVALID_VLAN_RANGE"
    assert issues[0].field_path == "vlan_id"


@pytest.mark.parametrize("vlan_id", [1, 1002, 1003, 1004, 1005])
def test_dia_reports_each_cisco_hop_using_a_reserved_vlan(vlan_id: int) -> None:
    """Informa cada salto Cisco afectado por una VLAN reservada."""
    intent = _dia_intent()
    intent = replace(intent, vlan_id=vlan_id, access=replace(intent.access, vendor="cisco"))
    issues = validate_dia_intent_semantics(intent)
    assert [(issue.code, issue.field_path, issue.node_id) for issue in issues] == [
        ("RESERVED_CISCO_VLAN", "vlan_id", "192.0.2.11"),
        ("RESERVED_CISCO_VLAN", "vlan_id", "192.0.2.12"),
    ]


@pytest.mark.parametrize("vlan_id", [1, 1002, 1003, 1004, 1005, 4094])
def test_huawei_path_accepts_vlans_reserved_only_for_cisco(vlan_id: int) -> None:
    """No aplica la reserva Cisco cuando todos los saltos son Huawei."""
    intent = _dia_intent()
    intent = replace(intent, vlan_id=vlan_id, transits=tuple(
        replace(hop, vendor="huawei") for hop in intent.transits
    ))
    assert validate_dia_intent_semantics(intent) == ()


@pytest.mark.parametrize("address", [
    "198.51.100.0", "198.51.100.1", "198.51.100.2", "198.51.100.3",
    "203.0.113.0", "203.0.113.1", "203.0.113.7",
])
def test_dia_reports_management_overlap_in_wan_and_lan(address: str) -> None:
    """Detecta gestion contenida en WAN o LAN, incluidas sus direcciones de borde."""
    intent = _dia_intent()
    intent = replace(intent, provider_edge=replace(
        intent.provider_edge, management_ip=IPv4Address(address),
    ))
    issues = validate_dia_intent_semantics(intent)
    assert len(issues) == 1
    assert issues[0].code == "MANAGEMENT_IP_OVERLAPS_SERVICE_NETWORK"
    assert issues[0].field_path == "hops[2].management_ip"
    assert issues[0].node_id == address


@pytest.mark.parametrize("bandwidth_mbps, expected_count", [(1000, 0), (1001, 1)])
def test_dia_enforces_the_laboratory_port_capacity(
    bandwidth_mbps: int, expected_count: int,
) -> None:
    """Acepta 1000 Mbps y rechaza el primer valor superior a la capacidad."""
    issues = validate_dia_intent_semantics(replace(_dia_intent(), bandwidth_mbps=bandwidth_mbps))
    assert len(issues) == expected_count
    if issues:
        assert issues[0].code == "BANDWIDTH_EXCEEDS_PORT_CAPACITY"
        assert issues[0].field_path == "bandwidth_mbps"


def test_dia_accumulates_semantic_defects_at_every_hop() -> None:
    """Acumula reservas, superposiciones y exceso de capacidad sin abortar."""
    intent = _dia_intent()
    intent = replace(
        intent, vlan_id=1, bandwidth_mbps=1001,
        access=replace(intent.access, management_ip=IPv4Address("198.51.100.1")),
        transits=(replace(intent.transits[0], management_ip=IPv4Address("203.0.113.1")),),
        provider_edge=replace(intent.provider_edge, management_ip=IPv4Address("198.51.100.2")),
    )
    issues = validate_dia_intent_semantics(intent)
    assert [issue.code for issue in issues].count("MANAGEMENT_IP_OVERLAPS_SERVICE_NETWORK") == 3
    assert {issue.code for issue in issues} == {
        "RESERVED_CISCO_VLAN", "MANAGEMENT_IP_OVERLAPS_SERVICE_NETWORK",
        "BANDWIDTH_EXCEEDS_PORT_CAPACITY",
    }
    assert all(issue.stage is ValidationStage.STATIC_OFFLINE for issue in issues)
    assert all(issue.severity is ValidationSeverity.ERROR for issue in issues)


def test_catalog_keeps_semantic_validation_optional_and_isolated() -> None:
    """Conserva servicios sin validador y aisla los registros entre catalogos."""
    catalog = PluginCatalog()
    catalog.register_service(DiaIntentParser(frozenset()))
    intent = _dia_intent()
    assert catalog.validate_semantics(intent) == ()
    calls: list[DiaIntent] = []

    def validate(candidate: DiaIntent) -> list[ValidationIssue]:
        calls.append(candidate)
        return [_issue()]

    catalog.register_service_validator("DIA", validate)
    assert catalog.validate_semantics(intent) == (_issue(),)
    assert calls == [intent]
    assert PluginCatalog().validate_semantics(intent) == ()
    with pytest.raises(PluginRegistrationError, match="validador duplicado"):
        catalog.register_service_validator("DIA", validate)


def test_catalog_requires_a_registered_service_for_its_validator() -> None:
    """Rechaza un validador huerfano de servicio en el catalogo."""
    with pytest.raises(PluginRegistrationError, match="servicio no registrado"):
        PluginCatalog().register_service_validator("DIA", validate_dia_intent_semantics)


def test_bootstrap_registers_the_dia_semantic_rules() -> None:
    """Activa las reglas DIA mediante la raiz de composicion existente."""
    intent = replace(_dia_intent(), vlan_id=0)
    assert build_plugin_catalog().validate_semantics(intent) == validate_dia_intent_semantics(intent)


@pytest.mark.parametrize("checker", [None, NoOpPreFlightChecker()])
def test_offline_validation_explicitly_omits_preflight(
    checker: PreFlightCheckerPort | None,
) -> None:
    """Permite validar offline y declara que no se ejecuto Pre-Flight."""
    intent = _dia_intent()
    report = PreValidationService(_supported_catalog(), checker).validate_and_require(intent)
    assert report.service_id == intent.description
    assert report.service_type == "DIA"
    assert report.issues == ()
    assert report.is_valid
    assert not report.preflight_executed
    assert NoOpPreFlightChecker().check_preflight(intent) == ()


def test_noop_subclasses_are_never_invoked_as_online_checkers() -> None:
    """Omite tambien los checkers que heredan de NoOpPreFlightChecker."""
    class NoOpSpy(NoOpPreFlightChecker):
        def check_preflight(self, intent: Any) -> Sequence[ValidationIssue]:
            """Detecta una invocacion indebida a la implementacion nula."""
            raise AssertionError("NoOp no debe ejecutarse como chequeo online")

    report = PreValidationService(_supported_catalog(), NoOpSpy()).validate(_dia_intent())
    assert report.is_valid
    assert not report.preflight_executed


@pytest.mark.parametrize("service_id", [None, "", "LAB-SERVICE-001"])
def test_report_identity_uses_service_id_or_description(service_id: str | None) -> None:
    """Prefiere service_id cuando existe y usa description como alternativa oficial."""
    intent = _IdentifiedIntent(**vars(_dia_intent()), service_id=service_id)
    report = PreValidationService(_supported_catalog()).validate(intent)
    assert report.service_id == (service_id or intent.description)


@pytest.mark.parametrize("node_id, hostname, expected", [
    ("LAB-NODE", "LAB-HOST", "LAB-NODE"),
    (None, "LAB-HOST", "LAB-HOST"),
    ("", "", "192.0.2.11"),
])
def test_catalog_issues_resolve_the_official_node_identity(
    node_id: str | None, hostname: str | None, expected: str,
) -> None:
    """Identifica el salto por node_id, hostname o management_ip en ese orden."""
    intent = _dia_intent()
    access = _IdentifiedAccess(
        **(vars(intent.access) | {"vendor": "unknown"}), node_id=node_id, hostname=hostname,
    )
    report = PreValidationService(_supported_catalog()).validate(replace(intent, access=access))
    assert [(issue.code, issue.node_id) for issue in report.issues] == [
        ("UNSUPPORTED_VENDOR", expected),
    ]


def test_static_validation_accumulates_defects_and_short_circuits() -> None:
    """Acumula duplicidad, vendor, plantilla y semantica sin invocar Pre-Flight."""
    intent = _dia_intent()
    intent = replace(
        intent, vlan_id=1, bandwidth_mbps=1001,
        transits=(
            replace(intent.transits[0], management_ip=intent.access.management_ip),
            replace(intent.transits[0], vendor="unknown", management_ip=intent.provider_edge.management_ip),
        ),
    )
    missing_key = TemplateKey("DIA", Operation.TEARDOWN, NodeRole.TRANSIT)
    checker = _PreFlightChecker()
    service = PreValidationService(_supported_catalog(omitted=(missing_key,)), checker)
    report = service.validate(intent)
    assert [issue.code for issue in report.issues] == [
        "BANDWIDTH_EXCEEDS_PORT_CAPACITY", "DUPLICATE_MANAGEMENT_IP",
        "DUPLICATE_MANAGEMENT_IP", "MISSING_TEMPLATE_KEY",
        "RESERVED_CISCO_VLAN", "UNSUPPORTED_VENDOR",
    ]
    duplicates = [issue for issue in report.issues if issue.code == "DUPLICATE_MANAGEMENT_IP"]
    assert [(issue.field_path, issue.node_id) for issue in duplicates] == [
        ("hops[1].management_ip", "192.0.2.11"),
        ("hops[3].management_ip", "192.0.2.21"),
    ]
    assert not report.is_valid
    assert not report.preflight_executed
    assert checker.call_count == 0
    with pytest.raises(PreValidationFailedError) as error:
        service.validate_and_require(intent)
    assert error.value.report == report
    assert checker.call_count == 0


def test_unsupported_service_does_not_mask_route_or_vendor_errors() -> None:
    """Informa servicio desconocido y sigue revisando vendor y duplicidad sin plantillas."""
    intent = _UnsupportedIntent(**vars(_dia_intent()))
    intent = replace(intent, access=replace(
        intent.access, vendor="unknown", management_ip=intent.provider_edge.management_ip,
    ))
    checker = _PreFlightChecker()
    report = PreValidationService(_supported_catalog(), checker).validate(intent)
    assert {issue.code for issue in report.issues} == {
        "UNSUPPORTED_SERVICE", "UNSUPPORTED_VENDOR", "DUPLICATE_MANAGEMENT_IP",
    }
    assert next(issue for issue in report.issues if issue.code == "UNSUPPORTED_SERVICE").field_path == "service_type"
    assert not report.preflight_executed
    assert checker.call_count == 0


@pytest.mark.parametrize("position", ["access", "transits", "provider_edge"])
def test_programmatic_role_disorder_blocks_preflight(position: str) -> None:
    """Rechaza tipos de salto ajenos al rol de su posicion en la ruta."""
    intent = _dia_intent()
    if position == "access":
        intent = replace(intent, access=ProviderEdgeHop("huawei", intent.access.management_ip, "port"))
    elif position == "transits":
        intent = replace(intent, transits=(AccessHop("cisco", intent.transits[0].management_ip, "p", "u"),))
    else:
        intent = replace(intent, provider_edge=TransitHop("huawei", intent.provider_edge.management_ip, "d", "u"))
    checker = _PreFlightChecker()
    report = PreValidationService(_supported_catalog(), checker).validate(intent)
    assert [issue.code for issue in report.issues] == ["INVALID_PATH_ROLE_ORDER"]
    assert report.errors[0].field_path == "hops"
    assert not report.preflight_executed
    assert checker.call_count == 0


@pytest.mark.parametrize("transit_count", [0, 1, 3])
def test_valid_path_supports_zero_or_more_transit_hops(transit_count: int) -> None:
    """Admite acceso y PE unidos mediante cero o mas transitos ordenados."""
    intent = _dia_intent()
    intent = replace(intent, transits=tuple(
        TransitHop("cisco", IPv4Address(f"192.0.2.{30 + index}"), "down", "up")
        for index in range(transit_count)
    ))
    checker = _PreFlightChecker()
    report = PreValidationService(_supported_catalog(), checker).validate_and_require(intent)
    assert report.issues == ()
    assert report.preflight_executed
    assert checker.call_count == 1
    assert checker.intents == [intent]


def test_empty_vendor_declarations_report_every_required_template() -> None:
    """Acumula provision y teardown faltantes para cada rol de la ruta real."""
    checker = _PreFlightChecker()
    report = PreValidationService(build_plugin_catalog(), checker).validate(_dia_intent())
    assert len(report.errors) == 6
    assert all(issue.code == "MISSING_TEMPLATE_KEY" for issue in report.errors)
    for index in range(3):
        messages = [issue.message for issue in report.errors if issue.field_path == f"hops[{index}].role"]
        assert len(messages) == 2
        assert any("/provision/" in message for message in messages)
        assert any("/teardown/" in message for message in messages)
    assert not report.preflight_executed
    assert checker.call_count == 0


def test_operation_subset_and_variant_are_forwarded_by_validate_and_require() -> None:
    """Comprueba solo las operaciones solicitadas en la variante indicada."""
    omitted = tuple(TemplateKey("DIA", Operation.TEARDOWN, role, "lab") for role in NodeRole)
    service = PreValidationService(_supported_catalog(variant="lab", omitted=omitted))
    report = service.validate_and_require(_dia_intent(), operations=("provision",), variant="lab")
    assert report.is_valid
    with pytest.raises(PreValidationFailedError) as error:
        service.validate_and_require(_dia_intent(), variant="lab")
    assert len(error.value.report.errors) == 3
    assert all("/teardown/" in issue.message and issue.message.endswith("/lab antes de continuar.")
               for issue in error.value.report.errors)
    assert len(service.validate(_dia_intent(), operations=("provision",)).errors) == 3


def test_undeclared_operation_is_reported_as_missing_template_coverage() -> None:
    """Informa una operacion sin plantilla para todos los saltos sin abortar."""
    report = PreValidationService(_supported_catalog()).validate(_dia_intent(), operations=("audit",))
    assert len(report.errors) == 3
    assert all(issue.code == "MISSING_TEMPLATE_KEY" and "/audit/" in issue.message for issue in report.errors)


def test_report_is_independent_of_vendor_and_operation_iteration_order() -> None:
    """Mantiene el mismo reporte al invertir registros y operaciones faltantes."""
    all_keys = tuple(TemplateKey("DIA", operation, role) for operation in Operation for role in NodeRole)
    reports = []
    for vendor_order, operations in [
        (("cisco", "huawei"), ("provision", "teardown")),
        (("huawei", "cisco"), ("teardown", "provision")),
    ]:
        catalog = _supported_catalog(omitted=all_keys, vendor_order=vendor_order)
        reports.append(PreValidationService(catalog).validate(_dia_intent(), operations=operations).to_dict())
    assert reports[0] == reports[1]


@pytest.mark.parametrize("static_warning", [False, True])
def test_preflight_executes_without_static_errors(static_warning: bool) -> None:
    """Ejecuta Pre-Flight cuando no hay hallazgos estaticos o solo hay advertencias."""
    warnings = (_issue(code="CHECK_POLICY", severity=ValidationSeverity.WARNING),) if static_warning else ()

    def validate(candidate: DiaIntent) -> tuple[ValidationIssue, ...]:
        return warnings

    checker = _PreFlightChecker()
    report = PreValidationService(_supported_catalog(validator=validate), checker).validate(_dia_intent())
    assert report.is_valid
    assert report.warnings == warnings
    assert report.preflight_executed
    assert checker.call_count == 1


def test_preflight_propagates_all_operational_collisions_and_full_report() -> None:
    """Acumula colisiones online y expone el reporte completo al exigir validez."""
    offline_warning = _issue(code="CHECK_POLICY", severity=ValidationSeverity.WARNING)

    def validate(candidate: DiaIntent) -> tuple[ValidationIssue, ...]:
        return (offline_warning,)

    online_issues = [
        _issue(code=code, stage=ValidationStage.PREFLIGHT_ONLINE, node_id="192.0.2.21")
        for code in ["VLAN_COLLISION", "SUBINTERFACE_ALREADY_EXISTS", "MISSING_QOS_POLICY"]
    ]
    checker = _PreFlightChecker(online_issues)
    service = PreValidationService(_supported_catalog(validator=validate), checker)
    report = service.validate(_dia_intent())
    assert [issue.code for issue in report.errors] == [
        "MISSING_QOS_POLICY", "SUBINTERFACE_ALREADY_EXISTS", "VLAN_COLLISION",
    ]
    assert all(issue.stage is ValidationStage.PREFLIGHT_ONLINE for issue in report.errors)
    assert report.warnings == (offline_warning,)
    assert report.preflight_executed
    assert checker.call_count == 1
    with pytest.raises(PreValidationFailedError) as error:
        service.validate_and_require(_dia_intent())
    assert error.value.report == report
    assert error.value.report.to_dict()["error_count"] == 3
    assert checker.call_count == 2


def test_online_warnings_allow_the_pipeline_to_continue() -> None:
    """Conserva advertencias online sin rechazar un reporte libre de errores."""
    warning = _issue(severity=ValidationSeverity.WARNING, stage=ValidationStage.PREFLIGHT_ONLINE)
    checker = _PreFlightChecker([warning])
    report = PreValidationService(_supported_catalog(), checker).validate_and_require(_dia_intent())
    assert report.warnings == (warning,)
    assert report.is_valid
    assert report.preflight_executed
    assert checker.call_count == 1


def test_require_valid_rejects_only_reports_with_errors() -> None:
    """Lanza la excepcion con el mismo reporte y permite reportes vacios o con advertencias."""
    service = PreValidationService(_supported_catalog())
    invalid = ValidationReport("LAB-001", "DIA", (_issue(),))
    with pytest.raises(PreValidationFailedError) as error:
        service.require_valid(invalid)
    assert error.value.report is invalid
    assert service.require_valid(ValidationReport("LAB-001", "DIA", ())) is None
    warnings = (_issue(severity=ValidationSeverity.WARNING),)
    assert service.require_valid(ValidationReport("LAB-001", "DIA", warnings)) is None


def test_static_validation_reports_the_full_criterion_two_combination() -> None:
    """Reporta en una sola ejecucion los seis defectos del criterio 2 con identidad por description."""
    intent = _dia_intent()
    intent = replace(
        intent, vlan_id=1, bandwidth_mbps=1001,
        transits=(
            replace(intent.transits[0], management_ip=intent.access.management_ip),
            replace(intent.transits[0], vendor="unknown", management_ip=IPv4Address("198.51.100.1")),
        ),
    )
    missing_key = TemplateKey("DIA", Operation.TEARDOWN, NodeRole.TRANSIT)
    checker = _PreFlightChecker()
    report = PreValidationService(_supported_catalog(omitted=(missing_key,)), checker).validate(intent)
    assert [issue.code for issue in report.issues] == [
        "BANDWIDTH_EXCEEDS_PORT_CAPACITY", "DUPLICATE_MANAGEMENT_IP",
        "MANAGEMENT_IP_OVERLAPS_SERVICE_NETWORK", "MISSING_TEMPLATE_KEY",
        "RESERVED_CISCO_VLAN", "UNSUPPORTED_VENDOR",
    ]
    assert report.service_id == intent.description
    assert not report.is_valid
    assert not report.preflight_executed
    assert checker.call_count == 0
