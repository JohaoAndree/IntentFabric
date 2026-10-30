"""Acumula reglas offline de VLAN, prefijo WAN, gestion y capacidad de DIA."""

from intentfabric.domain.intent import DiaIntent
from intentfabric.domain.validation import ValidationIssue, ValidationStage


def validate_dia_intent_semantics(intent: DiaIntent) -> tuple[ValidationIssue, ...]:
    """Detecta VLAN invalida o reservada, WAN sin /30, gestion superpuesta y exceso de capacidad."""
    issues: list[ValidationIssue] = []
    if not 1 <= intent.vlan_id <= 4094:
        issues.append(ValidationIssue(
            code="INVALID_VLAN_RANGE",
            message="vlan_id: utilice una VLAN entre 1 y 4094.",
            stage=ValidationStage.STATIC_OFFLINE, field_path="vlan_id",
        ))

    if intent.wan_network.prefixlen != 30:
        issues.append(ValidationIssue(
            code="INVALID_WAN_PREFIX_LENGTH",
            message="wan_network: utilice un prefijo /30.",
            stage=ValidationStage.STATIC_OFFLINE, field_path="wan_network",
        ))

    hops = (intent.access, *intent.transits, intent.provider_edge)
    for index, hop in enumerate(hops):
        if intent.vlan_id in {1, 1002, 1003, 1004, 1005} and hop.vendor == "cisco":
            issues.append(ValidationIssue(
                code="RESERVED_CISCO_VLAN",
                message="vlan_id: elija una VLAN de servicio distinta de 1 y 1002..1005 para Cisco.",
                stage=ValidationStage.STATIC_OFFLINE,
                field_path="vlan_id", node_id=hop.node_id,
            ))
        if hop.management_ip in intent.wan_network or (
            hop.management_ip in intent.lan_network
        ):
            issues.append(ValidationIssue(
                code="MANAGEMENT_IP_OVERLAPS_SERVICE_NETWORK",
                message="management_ip: utilice una direccion fuera de las redes WAN y LAN del servicio.",
                stage=ValidationStage.STATIC_OFFLINE,
                field_path=f"hops[{index}].management_ip", node_id=hop.node_id,
            ))

    if intent.bandwidth_mbps > 1000:
        issues.append(ValidationIssue(
            code="BANDWIDTH_EXCEEDS_PORT_CAPACITY",
            message="bandwidth_mbps: reduzca el ancho de banda a un maximo de 1000 Mbps.",
            stage=ValidationStage.STATIC_OFFLINE, field_path="bandwidth_mbps",
        ))
    return tuple(issues)
