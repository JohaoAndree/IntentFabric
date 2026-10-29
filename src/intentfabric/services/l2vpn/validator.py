"""Acumula defectos offline del extremo L2VPN sin efectos secundarios."""

from intentfabric.domain.intent import (
    L2VpnIntent, is_valid_evi_id, is_valid_pseudowire_id,
    is_valid_route_distinguisher_or_target,
)
from intentfabric.domain.validation import ValidationIssue, ValidationStage


def _issue(code: str, field: str, message: str, node_id: str | None = None) -> ValidationIssue:
    return ValidationIssue(
        code=code, field_path=field, message=f"{field}: {message}",
        stage=ValidationStage.STATIC_OFFLINE, node_id=node_id,
    )


def validate_l2vpn_semantics(intent: L2VpnIntent) -> tuple[ValidationIssue, ...]:
    """Detecta defectos de VLAN, capacidad, identificadores y extremo remoto."""
    issues: list[ValidationIssue] = []
    if not 1 <= intent.vlan_id <= 4094:
        issues.append(_issue("INVALID_VLAN_RANGE", "vlan_id", "utilice una VLAN entre 1 y 4094."))
    for hop in intent.hops:
        if intent.vlan_id in {1, 1002, 1003, 1004, 1005} and hop.vendor == "cisco":
            issues.append(_issue(
                "RESERVED_CISCO_VLAN", "vlan_id",
                "elija una VLAN distinta de 1 y 1002..1005 para Cisco.", hop.node_id,
            ))
    if intent.bandwidth_mbps > 1000:
        issues.append(_issue("BANDWIDTH_EXCEEDS_PORT_CAPACITY", "bandwidth_mbps", "reduzca el ancho de banda a 1000 Mbps o menos."))
    for field in ("pw_id", "local_ac_id", "remote_ac_id"):
        if not is_valid_pseudowire_id(getattr(intent, field)):
            issues.append(_issue("INVALID_PW_ID_RANGE", field, "utilice un entero entre 1 y 4294967295."))
    if not is_valid_evi_id(intent.evi_id):
        issues.append(_issue("INVALID_EVI_ID_RANGE", "evi_id", "utilice un entero entre 1 y 65535."))
    for field, code in (("rd", "INVALID_RD_FORMAT"), ("rt_import", "INVALID_RT_FORMAT"), ("rt_export", "INVALID_RT_FORMAT")):
        if not is_valid_route_distinguisher_or_target(getattr(intent, field)):
            issues.append(_issue(code, field, "utilice un RD o RT valido en formato admin:assigned."))
    if intent.remote_pe_node_id == intent.provider_edge.node_id:
        issues.append(_issue(
            "SAME_LOCAL_REMOTE_PE", "remote_pe_node_id", "utilice un PE distinto del local.",
            intent.provider_edge.node_id,
        ))
    if intent.remote_pe_ip == intent.provider_edge.management_ip:
        issues.append(_issue(
            "SAME_LOCAL_REMOTE_PE", "remote_pe_ip", "utilice una direccion distinta del PE local.",
            intent.provider_edge.node_id,
        ))
    return tuple(issues)


validate_l2vpn_intent_semantics = validate_l2vpn_semantics
