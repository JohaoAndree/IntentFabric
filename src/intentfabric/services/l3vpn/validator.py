"""Acumula defectos offline del extremo L3VPN sin efectos secundarios."""

from intentfabric.domain.intent import (
    L3VpnIntent, is_valid_asn, is_valid_route_distinguisher_or_target,
)
from intentfabric.domain.validation import ValidationIssue, ValidationStage


def _issue(code: str, field: str, message: str, node_id: str | None = None) -> ValidationIssue:
    return ValidationIssue(
        code=code, field_path=field, message=f"{field}: {message}",
        stage=ValidationStage.STATIC_OFFLINE, node_id=node_id,
    )


def validate_l3vpn_semantics(intent: L3VpnIntent) -> tuple[ValidationIssue, ...]:
    """Detecta todos los defectos de VLAN, redes, capacidad, RD, RT y ASN."""
    issues: list[ValidationIssue] = []
    if not 1 <= intent.vlan_id <= 4094:
        issues.append(_issue("INVALID_VLAN_RANGE", "vlan_id", "utilice una VLAN entre 1 y 4094."))
    for hop in intent.hops:
        if intent.vlan_id in {1, 1002, 1003, 1004, 1005} and hop.vendor == "cisco":
            issues.append(_issue(
                "RESERVED_CISCO_VLAN", "vlan_id",
                "elija una VLAN distinta de 1 y 1002..1005 para Cisco.", hop.node_id,
            ))
    if intent.wan_network.prefixlen != 30:
        issues.append(_issue("INVALID_WAN_PREFIX_LENGTH", "wan_network", "utilice un prefijo /30."))
    if intent.lan_network is not None:
        if not 8 <= intent.lan_network.prefixlen <= 30:
            issues.append(_issue("INVALID_LAN_PREFIX_LENGTH", "lan_network", "utilice un prefijo entre /8 y /30."))
        if intent.wan_network.overlaps(intent.lan_network):
            issues.append(_issue("WAN_LAN_OVERLAP", "lan_network", "utilice una LAN sin solapamiento con la WAN."))
    for index, hop in enumerate(intent.hops):
        if hop.management_ip in intent.wan_network or (
            intent.lan_network is not None and hop.management_ip in intent.lan_network
        ):
            issues.append(_issue(
                "MANAGEMENT_IP_OVERLAPS_SERVICE_NETWORK", f"hops[{index}].management_ip",
                "utilice una direccion fuera de las redes WAN y LAN del servicio.", hop.node_id,
            ))
    if intent.bandwidth_mbps > 1000:
        issues.append(_issue("BANDWIDTH_EXCEEDS_PORT_CAPACITY", "bandwidth_mbps", "reduzca el ancho de banda a 1000 Mbps o menos."))
    for field, code in (("rd", "INVALID_RD_FORMAT"), ("rt_import", "INVALID_RT_FORMAT"), ("rt_export", "INVALID_RT_FORMAT")):
        if not is_valid_route_distinguisher_or_target(getattr(intent, field)):
            issues.append(_issue(code, field, "utilice un RD o RT valido en formato admin:assigned."))
    for field in ("pe_asn", "ce_asn"):
        if not is_valid_asn(getattr(intent, field)):
            issues.append(_issue("INVALID_ASN_RANGE", field, "utilice un ASN entre 1 y 4294967294."))
    if is_valid_asn(intent.pe_asn) and is_valid_asn(intent.ce_asn) and intent.pe_asn == intent.ce_asn:
        issues.append(_issue("SAME_PE_CE_ASN", "ce_asn", "utilice un ASN distinto del PE para eBGP."))
    return tuple(issues)


validate_l3vpn_intent_semantics = validate_l3vpn_semantics
