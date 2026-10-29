"""Contexto plano de L2VPN por salto, independiente de los plugins de vendor."""

from intentfabric.domain.derivations import derive_subinterface_name
from intentfabric.domain.intent import AccessHop, L2VpnIntent, ProviderEdgeHop, TransitHop
from intentfabric.domain.template_key import Operation


def build_l2vpn_hop_context(
    intent: L2VpnIntent, hop_index: int, operation: Operation,
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
        context.update(
            pe_interface=hop.parent_interface, parent_interface=hop.parent_interface,
            pe_subinterface=derive_subinterface_name(hop.parent_interface, intent.vlan_id),
            qos_policy=intent.qos_policy_name, bandwidth_mbps=intent.bandwidth_mbps,
            pw_id=intent.pw_id, evi_id=intent.evi_id, local_ac_id=intent.local_ac_id,
            remote_ac_id=intent.remote_ac_id, instance_name=intent.instance_name,
            rd=intent.rd, rt_import=intent.rt_import, rt_export=intent.rt_export,
            remote_pe_node_id=intent.remote_pe_node_id, remote_pe_ip=str(intent.remote_pe_ip),
        )
    return context
