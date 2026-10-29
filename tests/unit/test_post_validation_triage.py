"""Garantiza triage, limpieza SVI y parsing de extractos documentales de laboratorio.

Los fixtures son fragmentos parametrizados, no capturas de produccion.
Las fallas se inyectan sobre esos fragmentos sin modificar las referencias.
Interfaces y VLAN: mismas fuentes de tests/unit/test_preflight_online.py.
LLDP Cisco / Huawei:
https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/application-services/b-application-services/m_ce-lldp-multivend.html
https://info.support.huawei.com/network/ptmngsys/Web/tsrev_s/cn/content/s/02_edesk_link_aggregation_interconnection_failure/edesk_link_aggregation_Interconnection_failure_edesk002.html
MAC Cisco / Huawei:
https://www.cisco.com/c/en/us/td/docs/switches/lan/c9000/lyr2-fwd/cdp-lldp-mac-udld/cdp-lldp-mac-udld-configuration-guide/c-configure-mac.html
https://info.support.huawei.com/network/ptmngsys/Web/tsrev_ar/en/content/ar/29_edesk_user_cannot_ping_gateway/edesk_user_cannot_ping_gateway_edesk003.html
Ping Cisco / Huawei:
https://www.cisco.com/c/en/us/td/docs/cloud-systems-management/network-automation-and-management/terminal-services-gateways/sw-config/tg1100swcfg-xe-17-2-book.pdf
https://info.support.huawei.com/network/ptmngsys/Web/tsrev_ne/en/content/ne/09_edesk_vrp_ssh_login_failed/edesk_vrp_ssh_login_failed_edesk001.html
Ruta VRF Cisco / Huawei:
https://www.cisco.com/c/en/us/td/docs/ios-xml/ios/iproute_pi/command/iri-cr-book/iri-cr-s1.html
https://info.support.huawei.com/network/ptmngsys/Web/tsrev_ne/en/content/ne/16_edesk_ne_vpn_traffic_fails/edesk_ne_vpn_traffic_fails_edesk005.html
VPNv4 Cisco / Huawei (documento Huawei V200R003C20, copia documental):
https://www.cisco.com/c/en/us/td/docs/routers/sdwan/command/iosxe/qualified-cli-command-reference-guide/m-troubleshooting-commands.html
https://it.scribd.com/document/728143462/ATN-910-910I-910B-950B-V200R003C20-Commissioning-Guide-03-CLI
EVPN Cisco:
https://www.cisco.com/c/en/us/td/docs/routers/ncs4200/configuration/guide/segment-routing/17-1-1/b-segment-routing-17-1-ncs4200.pdf
Martini Cisco / Huawei (campos session state / VC state en ADR-011):
https://www.cisco.com/c/en/us/td/docs/routers/ios-xe/mpls/mpls/m-mp-l2vpn-intrntwkg-xe.html
https://it.scribd.com/document/728143462/ATN-910-910I-910B-950B-V200R003C20-Commissioning-Guide-03-CLI
Peer BGP Cisco / Huawei:
https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9600/software/release/17-17/command_reference/b_1717_9600_cr/ip_routing_commands.html
https://info.support.huawei.com/network/ptmngsys/Web/tsrev_ar/en/content/ar/23_edesk_can_not_establish_bgp_neighbor/edesk_can_not_establish_bgp_neighbor_edesk004.html
"""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
import json
import re

import pytest

from intentfabric.adapters import SimulatedTransportAdapter
from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.application import PostValidationTriageService
from intentfabric.application.post_validation import (
    parse_bgp_neighbor_state, parse_interface_is_up, parse_l2vpn_circuit_up,
    parse_lldp_local_ports, parse_ping_success, parse_vlan_mac_count, parse_vrf_route_present,
)
from intentfabric.bootstrap import build_plugin_catalog, build_post_validator, load_default_topology
from intentfabric.domain import (
    DiaIntent, DeviceTransportError, EphemeralProbeCleanupError, L2VpnIntent, L3VpnIntent,
    PostValidationFailedError, ServiceOperationalStatus, TopologyNode, TriageStepName,
    build_ephemeral_svi_provision_commands, build_ephemeral_svi_teardown_commands, build_expected_state,
)


_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "tests/fixtures/post_validation"


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _intent(service: str = "dia", pe_vendor: str = "huawei") -> DiaIntent | L3VpnIntent | L2VpnIntent:
    raw = dict(load_intent_mapping(_ROOT / f"examples/intents/{service}_valid.json"))
    if pe_vendor == "cisco":
        raw.update(access_node_id="S3-4505-TEST", access_interface="GE0/0/1", pe_node_id="PE1-TEST")
        if service == "l2vpn":
            raw["remote_pe_node_id"] = "PE2-TEST"
    return build_plugin_catalog().parse_intent(raw)


def _peer_output(vendor: str, neighbor: str, state: str = "Established") -> str:
    if vendor == "cisco":
        value = "0" if state == "Established" else state
        return f"{neighbor} 4 65110 0 0 1 0 0 00:20:09 {value}\n"
    return f"{neighbor} 4 65110 1601 1443 0 23:21:56 {state} 0\n"


def _transport(
    intent: DiaIntent | L3VpnIntent | L2VpnIntent, variant: str = "default",
) -> SimulatedTransportAdapter:
    transport = SimulatedTransportAdapter()
    expected = build_expected_state(intent, variant=variant)
    for hop in intent.hops:
        cisco = hop.vendor == "cisco"
        lldp_name = "cisco_show_lldp_neighbors.txt" if cisco else "huawei_display_lldp_neighbor_brief.txt"
        lldp = _fixture(lldp_name)
        source_port = "Gi1/0/10" if cisco else "GE1/0/24"
        ports = [port for node_id, port in expected.expected_lldp_ports if node_id == hop.node_id]
        transport.set_show_output(hop.node_id, "show lldp neighbors" if cisco else "display lldp neighbor brief",
                                  "".join(lldp.replace(source_port, port) for port in ports))
    for hop in (intent.access, *intent.transits):
        cisco = hop.vendor == "cisco"
        vlan_name = "cisco_show_vlan_brief_clean.txt" if cisco else "huawei_display_vlan_clean.txt"
        vlan = (_ROOT / "tests/fixtures/preflight" / vlan_name).read_text(encoding="utf-8")
        vlan = re.sub(r"^1(?=\s)", str(intent.vlan_id), vlan, flags=re.M)
        transport.set_show_output(hop.node_id, "show vlan brief" if cisco else "display vlan", vlan)
        mac = _fixture("cisco_show_mac_address_table_vlan.txt" if cisco else "huawei_display_mac_address_vlan.txt")
        transport.set_show_output(hop.node_id,
                                  f"show mac address-table vlan {intent.vlan_id}" if cisco else f"display mac-address vlan {intent.vlan_id}",
                                  mac.replace("210", str(intent.vlan_id)))
    pe = intent.provider_edge
    cisco = pe.vendor == "cisco"
    interface_name = "cisco_show_ip_interface_brief_up.txt" if cisco else "huawei_display_interface_brief_up.txt"
    interface = _fixture(interface_name).replace(
        "GigabitEthernet0/0/4.210" if cisco else "GigabitEthernet0/0/0.210", expected.pe_subinterface,
    )
    transport.set_show_output(pe.node_id, "show ip interface brief" if cisco else "display interface brief", interface)
    if isinstance(intent, L2VpnIntent):
        if variant == "martini_ldp":
            command = f"show mpls l2transport vc {intent.pw_id}" if cisco else f"display mpls l2vc {intent.pw_id}"
            fixture_name = "cisco_show_mpls_l2transport_vc_up.txt" if cisco else "huawei_display_mpls_l2vc_up.txt"
        else:
            command = "show l2vpn evpn vpws" if cisco else f"display evpl instance {intent.evi_id}"
            fixture_name = "cisco_show_l2vpn_evpn_vpws_up.txt" if cisco else "huawei_display_evpl_instance_up.txt"
        transport.set_show_output(pe.node_id, command, _fixture(fixture_name))
    else:
        transport.set_show_output(intent.access.node_id, f"ping {expected.ping_target_ip}", _fixture(f"{intent.access.vendor}_ping_success.txt"))
        if isinstance(intent, DiaIntent):
            command = f"show ip route vrf {intent.vrf_name}" if cisco else f"display ip routing-table vpn-instance {intent.vrf_name}"
            fixture_name = "cisco_show_ip_route_vrf_dia.txt" if cisco else "huawei_display_ip_routing_table_vrf_dia.txt"
        else:
            command = f"show bgp vpnv4 unicast vrf {intent.vrf_name}" if cisco else f"display bgp vpnv4 vpn-instance {intent.vrf_name} routing-table"
            fixture_name = "cisco_show_bgp_vpnv4_vrf_l3vpn.txt" if cisco else "huawei_display_bgp_vpnv4_vrf_l3vpn.txt"
            peer_command = f"show bgp vpnv4 unicast vrf {intent.vrf_name} summary" if cisco else f"display bgp vpnv4 vpn-instance {intent.vrf_name} peer"
            transport.set_show_output(pe.node_id, peer_command, _peer_output(pe.vendor, expected.bgp_neighbor_ip))
        transport.set_show_output(pe.node_id, command, _fixture(fixture_name))
    return transport


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_documented_fragments_parse_exact_service_evidence(vendor: str) -> None:
    """Extrae interfaz, LLDP, MAC, ping y rutas de los fragmentos documentales."""
    cisco = vendor == "cisco"
    interface = _fixture("cisco_show_ip_interface_brief_up.txt" if cisco else "huawei_display_interface_brief_up.txt")
    assert parse_interface_is_up(interface, vendor, "Gi0/0/4.210" if cisco else "GE0/0/0.210")
    assert not parse_interface_is_up(interface, vendor, "Gi0/0/1.210")
    lldp = _fixture("cisco_show_lldp_neighbors.txt" if cisco else "huawei_display_lldp_neighbor_brief.txt")
    assert parse_lldp_local_ports(lldp, vendor) == frozenset({"GigabitEthernet1/0/10" if cisco else "GigabitEthernet1/0/24"})
    mac = _fixture("cisco_show_mac_address_table_vlan.txt" if cisco else "huawei_display_mac_address_vlan.txt")
    assert parse_vlan_mac_count(mac, vendor, 210) == 1
    assert parse_vlan_mac_count(mac, vendor, 21) == 0
    assert parse_ping_success(_fixture(f"{vendor}_ping_success.txt"), vendor)
    route = _fixture("cisco_show_ip_route_vrf_dia.txt" if cisco else "huawei_display_ip_routing_table_vrf_dia.txt")
    assert parse_vrf_route_present(route, vendor, "10.50.1.8/29")
    assert not parse_vrf_route_present(route, vendor, "10.50.1.8/30")
    bgp = _fixture("cisco_show_bgp_vpnv4_vrf_l3vpn.txt" if cisco else "huawei_display_bgp_vpnv4_vrf_l3vpn.txt")
    assert parse_vrf_route_present(bgp, vendor, "172.16.10.0/30")


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_empty_headers_and_malformed_outputs_fail_closed(vendor: str) -> None:
    """Rechaza evidencia vacia, encabezados y filas que no corresponden al objetivo."""
    for output in ("", "Interface IP-Address Status Protocol\nLocal Intf Neighbor Dev\nNetwork NextHop\n", "nonsense"):
        assert not parse_interface_is_up(output, vendor, "GE0/0/0.210")
        assert not parse_lldp_local_ports(output, vendor)
        assert parse_vlan_mac_count(output, vendor, 210) == 0
        assert not parse_ping_success(output, vendor)
        assert not parse_vrf_route_present(output, vendor, "192.0.2.0/30")
        assert parse_bgp_neighbor_state(output, vendor, "192.0.2.2") is None
        assert not parse_l2vpn_circuit_up(output, vendor, "martini_ldp", pw_id=310, evi_id=310)


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
@pytest.mark.parametrize("state", ["Established", "Active", "Idle", "Connect", "OpenSent", "OpenConfirm"])
def test_bgp_parser_matches_exact_peer_and_preserves_state(vendor: str, state: str) -> None:
    """Distingue estados y no atribuye al peer un vecino con IP parecida."""
    output = _peer_output(vendor, "192.0.2.20", "Established") + _peer_output(vendor, "192.0.2.2", state)
    assert parse_bgp_neighbor_state(output, vendor, "192.0.2.2") == state
    assert parse_bgp_neighbor_state(output, vendor, "192.0.2.3") is None


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_ping_parser_accepts_partial_replies_and_rejects_zero(vendor: str) -> None:
    """Acepta respuesta parcial, pero respeta el resumen explicito de cero respuestas."""
    output = _fixture(f"{vendor}_ping_success.txt")
    if vendor == "cisco":
        assert parse_ping_success(output.replace("100 percent", "20 percent"), vendor)
        assert not parse_ping_success(output.replace("100 percent", "0 percent"), vendor)
        assert parse_ping_success(".!...", vendor)
        assert not parse_ping_success("Warning!", vendor)
    else:
        assert parse_ping_success(output.replace("5 packet(s) received", "1 packet(s) received"), vendor)
        assert not parse_ping_success(output.replace("5 packet(s) received", "0 packet(s) received"), vendor)


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_martini_parser_rejects_other_circuits_and_down_states(vendor: str) -> None:
    """No confunde circuitos ni acepta un VC caido aunque su sesion este activa."""
    output = _fixture("cisco_show_mpls_l2transport_vc_up.txt" if vendor == "cisco" else "huawei_display_mpls_l2vc_up.txt")
    assert parse_l2vpn_circuit_up(output, vendor, "martini_ldp", pw_id=310, evi_id=310)
    assert not parse_l2vpn_circuit_up(output, vendor, "martini_ldp", pw_id=31, evi_id=310)
    down = output.replace("UP", "DOWN") if vendor == "cisco" else output.replace("VC state : up", "VC state : down")
    assert not parse_l2vpn_circuit_up(down, vendor, "martini_ldp", pw_id=310, evi_id=310)


@pytest.mark.parametrize("variant", ["default", "evpn_vpws"])
def test_cisco_evpn_parser_scopes_instance_state(variant: str) -> None:
    """Aisla el estado EVPN de cada EVI incluso con otras instancias activas."""
    output = _fixture("cisco_show_l2vpn_evpn_vpws_up.txt")
    assert parse_l2vpn_circuit_up(output, "cisco", variant, pw_id=310, evi_id=310)
    assert not parse_l2vpn_circuit_up(output, "cisco", variant, pw_id=310, evi_id=31)
    mixed = output.replace("1 up, 0 down", "0 up, 1 down") + output.replace("instance: 310", "instance: 311")
    assert not parse_l2vpn_circuit_up(mixed, "cisco", variant, pw_id=310, evi_id=310)


@pytest.mark.parametrize("service", ["dia", "l3vpn"])
@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_l3_services_probe_and_cleanup_in_both_access_vendors(service: str, vendor: str) -> None:
    """Valida plano L3 y retira la SVI con comandos nativos y orden determinista."""
    intent = _intent(service, vendor)
    expected = build_expected_state(intent)
    transport = _transport(intent)
    validator = build_post_validator(transport=transport)
    report = validator.validate_and_require(intent)
    assert report.status == ServiceOperationalStatus.OPERATIONAL and report.sdc == 1
    assert all(step.passed for step in report.steps)
    assert tuple(step.step for step in report.steps) == tuple(TriageStepName)
    assert report.observed_state.svi_cleaned_up and report.observed_state.svi_ping_success
    configurations = [record for record in transport.history if record.mode == "config"]
    assert len(configurations) == 2
    assert configurations[0].commands == build_ephemeral_svi_provision_commands(
        intent.access.vendor, intent.vlan_id, expected.svi_ip_address, expected.svi_netmask,
    )
    assert configurations[1].commands == build_ephemeral_svi_teardown_commands(intent.access.vendor, intent.vlan_id)
    assert all(record.node_id == intent.access.node_id for record in configurations)
    repeat = validator.validate(intent)
    assert json.dumps(report.to_dict()) == json.dumps(repeat.to_dict())
    assert validator.require_compliant(report) is report


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
@pytest.mark.parametrize("state", ["Active", "Idle", "Connect"])
def test_l3vpn_waiting_for_ce_is_ready_for_service(vendor: str, state: str) -> None:
    """Acepta conformidad sin CE cuando ping, VPNv4 y eslabones previos cumplen."""
    intent = _intent("l3vpn", vendor)
    transport = _transport(intent)
    command = f"show bgp vpnv4 unicast vrf {intent.vrf_name} summary" if vendor == "cisco" else f"display bgp vpnv4 vpn-instance {intent.vrf_name} peer"
    transport.set_show_output(intent.provider_edge.node_id, command, _peer_output(vendor, "172.16.10.2", state))
    report = build_post_validator(transport=transport).validate_and_require(intent)
    assert report.status == ServiceOperationalStatus.READY_FOR_SERVICE
    assert report.sdc == 1 and report.observed_state.ebgp_neighbor_state == state


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
@pytest.mark.parametrize("failure", ["interface", "lldp", "vlan", "mac", "ping", "route", "peer"])
def test_l3vpn_attributes_each_failure_to_its_first_step(vendor: str, failure: str) -> None:
    """Atribuye fallos de interfaz, LLDP, VLAN/MAC, ping, ruta y peer al nodo exacto."""
    intent = _intent("l3vpn", vendor)
    transport = _transport(intent)
    cisco = vendor == "cisco"
    target_node = intent.provider_edge.node_id
    step = TriageStepName.SERVICE_CONTROL_AND_DATA_PLANE
    if failure == "interface":
        command = "show ip interface brief" if cisco else "display interface brief"
        step = TriageStepName.PE_INTERFACE_STATE
    elif failure == "lldp":
        target_node = intent.transits[0].node_id
        command = "show lldp neighbors" if intent.transits[0].vendor == "cisco" else "display lldp neighbor brief"
        step = TriageStepName.LLDP_CONTINUITY
    elif failure in ("vlan", "mac"):
        target = intent.transits[0] if failure == "vlan" else intent.access
        target_node = target.node_id
        command = ("show vlan brief" if target.vendor == "cisco" else "display vlan") if failure == "vlan" else (
            f"show mac address-table vlan {intent.vlan_id}" if target.vendor == "cisco" else f"display mac-address vlan {intent.vlan_id}"
        )
        step = TriageStepName.L2_VLAN_AND_MAC
    elif failure == "ping":
        command = "ping 172.16.10.1"
        transport.set_show_output(intent.access.node_id, command, "")
        command = None
    elif failure == "route":
        command = f"show bgp vpnv4 unicast vrf {intent.vrf_name}" if cisco else f"display bgp vpnv4 vpn-instance {intent.vrf_name} routing-table"
    else:
        command = f"show bgp vpnv4 unicast vrf {intent.vrf_name} summary" if cisco else f"display bgp vpnv4 vpn-instance {intent.vrf_name} peer"
    if command:
        transport.set_show_output(target_node, command, "")
    validator = build_post_validator(transport=transport)
    report = validator.validate(intent)
    assert report.status == ServiceOperationalStatus.FAILED and report.sdc == 0
    assert (report.root_cause_step, report.root_cause_node_id) == (step, target_node)
    assert len(report.steps) == 4 and report.observed_state.svi_cleaned_up
    with pytest.raises(PostValidationFailedError) as captured:
        validator.require_compliant(report)
    assert captured.value.report is report
    with pytest.raises(PostValidationFailedError):
        validator.validate_and_require(intent)


@pytest.mark.parametrize("vendor,variant", [("cisco", "default"), ("cisco", "evpn_vpws"),
                                           ("cisco", "martini_ldp"), ("huawei", "martini_ldp")])
def test_l2vpn_queries_circuit_without_svi_or_mac_requirement(vendor: str, variant: str) -> None:
    """Valida variantes L2VPN sin sonda y sin exigir trafico de CE."""
    intent = _intent("l2vpn", vendor)
    transport = _transport(intent, variant)
    for hop in (intent.access, *intent.transits):
        command = f"show mac address-table vlan {intent.vlan_id}" if hop.vendor == "cisco" else f"display mac-address vlan {intent.vlan_id}"
        transport.set_show_output(hop.node_id, command, "")
    report = build_post_validator(transport=transport).validate_and_require(intent, variant=variant)
    assert report.status == ServiceOperationalStatus.OPERATIONAL and report.sdc == 1
    assert report.observed_state.svi_ping_success is None and report.observed_state.svi_cleaned_up
    assert report.observed_state.mac_learned_nodes == ()
    assert all(record.mode == "show" for record in transport.history)
    assert report.steps[-1].commands_executed == transport.history[-1].commands


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
@pytest.mark.parametrize("phase", ["ping", "vlan", "mac"])
def test_intermediate_transport_failure_always_removes_svi(vendor: str, phase: str) -> None:
    """Retira la sonda aun si una consulta operativa lanza DeviceTransportError."""
    intent = _intent("dia", vendor)
    access = intent.access
    command = ("ping 192.168.10.1" if phase == "ping" else
               ("show vlan brief" if access.vendor == "cisco" else "display vlan") if phase == "vlan" else
               ("show mac address-table vlan 10" if access.vendor == "cisco" else "display mac-address vlan 10"))
    transport = _transport(intent)
    original_show = transport.execute_show

    def failing_show(node: TopologyNode, current_command: str) -> str:
        if node.node_id == access.node_id and current_command == command:
            raise DeviceTransportError("fallo inyectado", node_id=node.node_id, command=current_command)
        return original_show(node, current_command)

    transport.execute_show = failing_show
    with pytest.raises(DeviceTransportError, match="fallo inyectado"):
        build_post_validator(transport=transport).validate(intent)
    assert transport.history[-1].commands == build_ephemeral_svi_teardown_commands(access.vendor, intent.vlan_id)


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_teardown_failure_exposes_cleanup_error_with_original_cause(vendor: str) -> None:
    """Da prioridad al error de limpieza con nodo, VLAN y causa conservados."""
    intent = _intent("dia", vendor)
    transport = _transport(intent)
    original_push = transport.push_configuration
    failure = DeviceTransportError("teardown bloqueado", node_id=intent.access.node_id)

    def failing_teardown(node: TopologyNode, commands: Sequence[str]) -> tuple[str, bool]:
        if tuple(commands) == build_ephemeral_svi_teardown_commands(node.vendor, intent.vlan_id):
            raise failure
        return original_push(node, commands)

    transport.push_configuration = failing_teardown
    with pytest.raises(EphemeralProbeCleanupError) as captured:
        build_post_validator(transport=transport).validate(intent)
    assert captured.value.__cause__ is failure
    assert (captured.value.node_id, captured.value.vlan_id) == (intent.access.node_id, intent.vlan_id)


def test_factory_accepts_injected_topology() -> None:
    """Compone el validador con inventario y transporte proporcionados."""
    topology = load_default_topology()
    intent = _intent()
    validator = build_post_validator(topology, transport=_transport(intent))
    assert isinstance(validator, PostValidationTriageService)
    assert validator.validate(intent).is_compliant


@pytest.mark.parametrize("vendor,variant", [("cisco", "default"), ("cisco", "evpn_vpws"),
                                           ("cisco", "martini_ldp"), ("huawei", "martini_ldp")])
@pytest.mark.parametrize("failed_step", list(TriageStepName))
def test_l2vpn_cascade_reports_exact_first_failed_node(
    vendor: str, variant: str, failed_step: TriageStepName,
) -> None:
    """Atribuye cada eslabon L2VPN al nodo fallido y prioriza el primer fallo."""
    intent = _intent("l2vpn", vendor)
    transport = _transport(intent, variant)
    pe = intent.provider_edge
    if variant == "martini_ldp":
        circuit_command = f"show mpls l2transport vc {intent.pw_id}" if vendor == "cisco" else f"display mpls l2vc {intent.pw_id}"
    else:
        circuit_command = "show l2vpn evpn vpws"
    transport.set_show_output(pe.node_id, circuit_command, "")
    if failed_step == TriageStepName.PE_INTERFACE_STATE:
        target_node = pe.node_id
        command = "show ip interface brief" if vendor == "cisco" else "display interface brief"
    elif failed_step == TriageStepName.LLDP_CONTINUITY:
        target_node = intent.access.node_id
        command = "show lldp neighbors" if intent.access.vendor == "cisco" else "display lldp neighbor brief"
    elif failed_step == TriageStepName.L2_VLAN_AND_MAC:
        target = intent.transits[0]
        target_node = target.node_id
        command = "show vlan brief" if target.vendor == "cisco" else "display vlan"
    else:
        target_node = pe.node_id
        command = circuit_command
    transport.set_show_output(target_node, command, "")
    report = build_post_validator(transport=transport).validate(intent, variant=variant)
    assert report.status == ServiceOperationalStatus.FAILED and report.sdc == 0
    assert (report.root_cause_step, report.root_cause_node_id) == (failed_step, target_node)
    assert len(report.steps) == 4 and report.steps[-1].passed is False
    assert all(record.mode == "show" for record in transport.history)


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_l3_access_mac_is_required_but_transit_mac_is_only_observed(vendor: str) -> None:
    """Conserva la exigencia de MAC en acceso de Parte B sin ampliarla al transito."""
    intent = _intent("dia", vendor)
    transport = _transport(intent)
    transit = intent.transits[0]
    command = f"show mac address-table vlan {intent.vlan_id}" if transit.vendor == "cisco" else f"display mac-address vlan {intent.vlan_id}"
    transport.set_show_output(transit.node_id, command, "")
    report = build_post_validator(transport=transport).validate_and_require(intent)
    assert report.observed_state.mac_learned_nodes == (intent.access.node_id,)


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_pe_subinterface_down_state_is_not_accepted(vendor: str) -> None:
    """No confunde interfaz presente con protocolo y enlace operativos."""
    output = _fixture("cisco_show_ip_interface_brief_up.txt" if vendor == "cisco" else "huawei_display_interface_brief_up.txt")
    interface = "Gi0/0/4.210" if vendor == "cisco" else "GE0/0/0.210"
    assert not parse_interface_is_up(output.replace("up up", "up down"), vendor, interface)
    assert not parse_interface_is_up(output.replace("up up", "down up"), vendor, interface)


def test_route_parser_accepts_compact_bgp_marker_and_excludes_prefix_summaries() -> None:
    """Distingue rutas exactas de agregados informativos y ecos de comandos."""
    bgp = _fixture("cisco_show_bgp_vpnv4_vrf_l3vpn.txt")
    assert parse_vrf_route_present(bgp.replace("*> ", "*>i"), "cisco", "172.16.10.0/30")
    for output in (
        "172.16.10.0/30 is subnetted, 1 subnets",
        "172.16.10.0/30 is variably subnetted, 2 subnets, 2 masks",
        "PE-LAB# show ip route vrf LAB 172.16.10.0/30",
        bgp.replace("172.16.10.0/30", "172.16.100.0/30"),
    ):
        assert not parse_vrf_route_present(output, "cisco", "172.16.10.0/30")


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_teardown_error_takes_priority_over_failed_query(vendor: str) -> None:
    """Conserva la causa de limpieza cuando tambien falla una consulta de la sonda."""
    intent = _intent("dia", vendor)
    transport = _transport(intent)
    original_push = transport.push_configuration
    query_error = DeviceTransportError("consulta interrumpida", node_id=intent.access.node_id)
    cleanup_error = DeviceTransportError("limpieza interrumpida", node_id=intent.access.node_id)
    original_show = transport.execute_show

    def failing_show(node: TopologyNode, command: str) -> str:
        if command.startswith("ping "):
            raise query_error
        return original_show(node, command)

    def failing_teardown(node: TopologyNode, commands: Sequence[str]) -> tuple[str, bool]:
        if tuple(commands) == build_ephemeral_svi_teardown_commands(node.vendor, intent.vlan_id):
            raise cleanup_error
        return original_push(node, commands)

    transport.execute_show = failing_show
    transport.push_configuration = failing_teardown
    with pytest.raises(EphemeralProbeCleanupError) as captured:
        build_post_validator(transport=transport).validate(intent)
    assert captured.value.__cause__ is cleanup_error
    assert cleanup_error.__context__ is query_error


def test_lldp_queries_repeated_hop_node_only_once() -> None:
    """Consulta cada nodo LLDP una vez aun cuando figure repetido en la ruta."""
    intent = _intent("dia")
    intent = replace(intent, transits=intent.transits * 2)
    transport = _transport(intent)
    report = build_post_validator(transport=transport).validate(intent)
    lldp_records = [record for record in transport.history if "lldp" in record.commands[0]]
    assert [record.node_id for record in lldp_records] == list(dict.fromkeys(hop.node_id for hop in intent.hops))
    assert report.steps[1].passed
