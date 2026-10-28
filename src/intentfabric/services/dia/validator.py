"""Acumula las cuatro reglas semanticas offline del servicio DIA."""

from intentfabric.domain.intent import DiaIntent
from intentfabric.domain.validation import ValidationIssue, ValidationStage


def validate_dia_intent_semantics(intent: DiaIntent) -> tuple[ValidationIssue, ...]:
    """Detecta VLAN invalida o reservada, gestion superpuesta y exceso de capacidad."""
    issues: list[ValidationIssue] = []
    if not 1 <= intent.vlan_id <= 4094:
        issues.append(ValidationIssue(
            code="INVALID_VLAN_RANGE",
            message="vlan_id: utilice una VLAN entre 1 y 4094.",
            stage=ValidationStage.STATIC_OFFLINE, field_path="vlan_id",
        ))

    hops = (intent.access, *intent.transits, intent.provider_edge)
    lan_network = getattr(intent, "lan_network", None)
    for index, hop in enumerate(hops):
        if intent.vlan_id in {1, 1002, 1003, 1004, 1005} and hop.vendor == "cisco":
            issues.append(ValidationIssue(
                code="RESERVED_CISCO_VLAN",
                message="vlan_id: elija una VLAN de servicio distinta de 1 y 1002..1005 para Cisco.",
                stage=ValidationStage.STATIC_OFFLINE,
                field_path="vlan_id", node_id=str(hop.management_ip),
            ))
        if hop.management_ip in intent.wan_network or (
            lan_network is not None and hop.management_ip in lan_network
        ):
            issues.append(ValidationIssue(
                code="MANAGEMENT_IP_OVERLAPS_SERVICE_NETWORK",
                message="management_ip: utilice una direccion fuera de las redes WAN y LAN del servicio.",
                stage=ValidationStage.STATIC_OFFLINE,
                field_path=f"hops[{index}].management_ip", node_id=str(hop.management_ip),
            ))

    if intent.bandwidth_mbps > 1000:
        issues.append(ValidationIssue(
            code="BANDWIDTH_EXCEEDS_PORT_CAPACITY",
            message="bandwidth_mbps: reduzca el ancho de banda a un maximo de 1000 Mbps.",
            stage=ValidationStage.STATIC_OFFLINE, field_path="bandwidth_mbps",
        ))
    return tuple(issues)
