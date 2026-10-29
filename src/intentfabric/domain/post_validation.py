"""Define estados esperados y observados de la validacion posdespliegue."""

from dataclasses import asdict, dataclass, replace
from enum import StrEnum

from intentfabric.domain.derivations import derive_subinterface_name, derive_wan_addresses
from intentfabric.domain.errors import PostValidationContractError, UnsupportedCombinationError
from intentfabric.domain.intent import DiaIntent, L2VpnIntent, L3VpnIntent
from intentfabric.domain.interfaces import normalize_interface_name


class ServiceOperationalStatus(StrEnum):
    """Identifica la conformidad operativa del servicio."""

    OPERATIONAL = "OPERATIONAL"
    READY_FOR_SERVICE = "READY_FOR_SERVICE"
    FAILED = "FAILED"


class TriageStepName(StrEnum):
    """Identifica cada eslabon ordenado del triage."""

    PE_INTERFACE_STATE = "pe_interface_state"
    LLDP_CONTINUITY = "lldp_continuity"
    L2_VLAN_AND_MAC = "l2_vlan_and_mac"
    SERVICE_CONTROL_AND_DATA_PLANE = "service_control_and_data_plane"


@dataclass(frozen=True, slots=True)
class ExpectedState:
    """Conserva las condiciones deterministas derivadas de la intencion."""

    service_id: str
    service_type: str
    variant: str
    vlan_id: int
    pe_node_id: str
    pe_subinterface: str
    expected_lldp_ports: tuple[tuple[str, str], ...]
    l2_node_ids: tuple[str, ...]
    requires_svi_probe: bool
    access_node_id: str
    svi_interface: str | None = None
    svi_ip_address: str | None = None
    svi_netmask: str | None = None
    ping_target_ip: str | None = None
    vrf_name: str | None = None
    expected_route_prefix: str | None = None
    bgp_neighbor_ip: str | None = None
    pw_id: int | None = None
    evi_id: int | None = None

    def to_dict(self) -> dict[str, object]:
        """Serializa condiciones con claves fijas y colecciones JSON compatibles."""
        result = asdict(self)
        result["expected_lldp_ports"] = [list(port) for port in self.expected_lldp_ports]
        result["l2_node_ids"] = list(self.l2_node_ids)
        return result


def build_expected_state(
    intent: DiaIntent | L3VpnIntent | L2VpnIntent, *, variant: str = "default",
) -> ExpectedState:
    """Deriva las condiciones por servicio respetando el orden de la ruta."""
    ports = [(intent.access.node_id, intent.access.uplink_interface)]
    for transit in intent.transits:
        ports.extend(((transit.node_id, transit.downstream_interface),
                      (transit.node_id, transit.upstream_interface)))
    ports.append((intent.provider_edge.node_id, intent.provider_edge.parent_interface))
    expected = ExpectedState(
        service_id=getattr(intent, "service_id", None) or intent.description,
        service_type=intent.service_type, variant=variant, vlan_id=intent.vlan_id,
        pe_node_id=intent.provider_edge.node_id,
        pe_subinterface=normalize_interface_name(
            derive_subinterface_name(intent.provider_edge.parent_interface, intent.vlan_id),
            vendor=intent.provider_edge.vendor,
        ),
        expected_lldp_ports=tuple(ports),
        l2_node_ids=(intent.access.node_id, *(hop.node_id for hop in intent.transits)),
        access_node_id=intent.access.node_id,
        requires_svi_probe=not isinstance(intent, L2VpnIntent),
    )
    if isinstance(intent, L2VpnIntent):
        return replace(expected, pw_id=intent.pw_id, evi_id=intent.evi_id)
    wan = derive_wan_addresses(intent.wan_network)
    return replace(
        expected,
        svi_interface=f"{'Vlan' if intent.access.vendor == 'cisco' else 'Vlanif'}{intent.vlan_id}",
        svi_ip_address=str(wan.ce_address), svi_netmask=wan.netmask,
        ping_target_ip=str(wan.pe_address), vrf_name=intent.vrf_name,
        expected_route_prefix=str(intent.lan_network if isinstance(intent, DiaIntent)
                                  else intent.wan_network),
        bgp_neighbor_ip=str(wan.ce_address) if isinstance(intent, L3VpnIntent) else None,
    )


def build_ephemeral_svi_provision_commands(
    vendor: str, vlan_id: int, ip_address: str, netmask: str,
) -> tuple[str, ...]:
    """Construye los comandos prescritos para aprovisionar la sonda SVI."""
    if vendor == "cisco":
        return (f"interface Vlan{vlan_id}", f" ip address {ip_address} {netmask}", " no shutdown")
    if vendor == "huawei":
        return (f"interface Vlanif{vlan_id}", f" ip address {ip_address} {netmask}", " undo shutdown")
    raise UnsupportedCombinationError(f"vendor: fabricante no soportado {vendor!r}")


def build_ephemeral_svi_teardown_commands(vendor: str, vlan_id: int) -> tuple[str, ...]:
    """Construye los comandos prescritos para retirar la sonda SVI."""
    if vendor == "cisco":
        return (f"no interface Vlan{vlan_id}",)
    if vendor == "huawei":
        return (f"undo interface Vlanif{vlan_id}",)
    raise UnsupportedCombinationError(f"vendor: fabricante no soportado {vendor!r}")


@dataclass(frozen=True, slots=True)
class ObservedState:
    """Conserva evidencias operativas en orden de recorrido."""

    pe_subinterface_up: bool
    lldp_ports_up: tuple[tuple[str, str], ...]
    active_vlan_nodes: tuple[str, ...]
    mac_learned_nodes: tuple[str, ...]
    svi_ping_success: bool | None
    svi_cleaned_up: bool
    control_plane_up: bool
    ebgp_neighbor_state: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Serializa observaciones con claves fijas y colecciones JSON compatibles."""
        result = asdict(self)
        result["lldp_ports_up"] = [list(port) for port in self.lldp_ports_up]
        result["active_vlan_nodes"] = list(self.active_vlan_nodes)
        result["mac_learned_nodes"] = list(self.mac_learned_nodes)
        return result


@dataclass(frozen=True, slots=True)
class TriageStepResult:
    """Conserva el resultado y los comandos de un eslabon del triage."""

    step: TriageStepName
    passed: bool
    node_id: str
    details: str
    commands_executed: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.step, TriageStepName):
            raise PostValidationContractError("step: se requiere TriageStepName")
        if type(self.passed) is not bool:
            raise PostValidationContractError("passed: se requiere bool")
        for name in ("node_id", "details"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise PostValidationContractError(f"{name}: se requiere texto no vacio")
        if not isinstance(self.commands_executed, tuple) or not self.commands_executed:
            raise PostValidationContractError("commands_executed: se requiere una tupla no vacia")

    def to_dict(self) -> dict[str, object]:
        """Serializa el eslabon con su identificador y comandos en orden fijo."""
        return {"step": self.step.value, "passed": self.passed, "node_id": self.node_id,
                "details": self.details, "commands_executed": list(self.commands_executed)}


@dataclass(frozen=True, slots=True)
class PostValidationReport:
    """Conserva conformidad y causa raiz coherentes con el estado operativo."""

    service_id: str
    service_type: str
    variant: str
    status: ServiceOperationalStatus
    sdc: int
    expected_state: ExpectedState
    observed_state: ObservedState
    steps: tuple[TriageStepResult, ...]
    root_cause_step: TriageStepName | None = None
    root_cause_node_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, ServiceOperationalStatus):
            raise PostValidationContractError("status: se requiere ServiceOperationalStatus")
        if type(self.sdc) is not int or self.sdc != int(self.status != ServiceOperationalStatus.FAILED):
            raise PostValidationContractError("sdc: valor incompatible con status")
        if not isinstance(self.steps, tuple) or not self.steps:
            raise PostValidationContractError("steps: se requiere una tupla no vacia")
        if self.status == ServiceOperationalStatus.FAILED:
            if self.root_cause_step is None or self.root_cause_node_id is None:
                raise PostValidationContractError("root_cause: se requiere paso y nodo para FAILED")
        elif self.root_cause_step is not None or self.root_cause_node_id is not None:
            raise PostValidationContractError("root_cause: debe ser None para sdc=1")

    @property
    def is_compliant(self) -> bool:
        """Indica que el servicio cumple el estado esperado."""
        return self.sdc == 1

    def to_dict(self) -> dict[str, object]:
        """Serializa el reporte completo con orden fijo de claves."""
        return {
            "service_id": self.service_id, "service_type": self.service_type,
            "variant": self.variant, "status": self.status.value, "sdc": self.sdc,
            "is_compliant": self.is_compliant,
            "root_cause_step": self.root_cause_step.value if self.root_cause_step else None,
            "root_cause_node_id": self.root_cause_node_id,
            "expected_state": self.expected_state.to_dict(),
            "observed_state": self.observed_state.to_dict(),
            "steps": [step.to_dict() for step in self.steps],
        }
