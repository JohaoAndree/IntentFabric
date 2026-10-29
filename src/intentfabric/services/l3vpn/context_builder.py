"""Contexto plano de L3VPN por salto, independiente de los plugins de vendor."""

from intentfabric.domain.derivations import derive_subinterface_name, derive_wan_addresses
from intentfabric.domain.intent import AccessHop, L3VpnIntent, ProviderEdgeHop, TransitHop
from intentfabric.domain.template_key import Operation


def build_l3vpn_hop_context(
    intent: L3VpnIntent, hop_index: int, operation: Operation,
) -> dict[str, object]:
    """Construye las variables del salto conservando una unica description."""
    if type(hop_index) is not int or not 0 <= hop_index < len(intent.hops):
        raise ValueError("hop_index: se requiere un indice entero dentro de la ruta")
    hop = intent.hops[hop_index]
    context: dict[str, object] = {
        "service_type": intent.service_type, "operation": operation.value,
        "description": intent.description, "vlan_id": intent.vlan_id,
        "vendor": hop.vendor, "role": hop.role.value,
        "node_id": hop.node_id,
        "management_ip": str(hop.management_ip),
    }
    if isinstance(hop, AccessHop):
        context.update(client_interface=hop.customer_port, uplink_interface=hop.uplink_interface)
    elif isinstance(hop, TransitHop):
        context.update(
            downstream_interface=hop.downstream_interface,
            upstream_interface=hop.upstream_interface,
            ingress_interface=hop.downstream_interface, egress_interface=hop.upstream_interface,
        )
    elif isinstance(hop, ProviderEdgeHop):
        wan = derive_wan_addresses(intent.wan_network)
        context.update(
            pe_interface=hop.parent_interface, parent_interface=hop.parent_interface,
            pe_subinterface=derive_subinterface_name(hop.parent_interface, intent.vlan_id),
            vrf_name=intent.vrf_name, qos_policy=intent.qos_policy_name,
            rd=intent.rd, rt_import=intent.rt_import, rt_export=intent.rt_export,
            pe_asn=intent.pe_asn, ce_asn=intent.ce_asn,
            bandwidth_mbps=intent.bandwidth_mbps, wan_network=str(intent.wan_network),
            wan_netmask=wan.netmask, wan_prefixlen=wan.prefix_length,
            wan_pe_ip=str(wan.pe_address), wan_ce_ip=str(wan.ce_address),
        )
        if intent.lan_network is not None:
            context.update(
                lan_network=str(intent.lan_network),
                lan_network_address=str(intent.lan_network.network_address),
                lan_netmask=str(intent.lan_network.netmask), lan_prefixlen=intent.lan_network.prefixlen,
            )
    return context
