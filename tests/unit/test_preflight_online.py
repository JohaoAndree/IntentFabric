"""Garantiza precondiciones online con fragmentos oficiales parametrizados de laboratorio.

Los fixtures son extractos documentales, no capturas de equipos de produccion.
Se parametrizan interfaces, VLAN, nombres VRF, direcciones, ASN y fechas fijas.
Fuentes por pareja de fixtures (Cisco / Huawei):
VLAN:
https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-18/command_reference/b_1718_9300_cr/vlan_commands.html
https://info.support.huawei.com/network/ptmngsys/Web/tsrev_s/en/content/s/06_edesk_VLAN_Cannot_Communicate/edesk_VLAN_Cannot_Communicate_edesk002.html
Puerto de acceso:
https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9300/software/release/17-17/command_reference/b_1717_9300_cr/interface_and_hardware_commands.html
https://info.support.huawei.com/network/ptmngsys/Web/tsrev_s/en/content/s/10_edesk_Ping_Fail/edesk_Ping_Fail_edesk001.html
Interfaces:
https://www.cisco.com/c/en/us/td/docs/routers/access/isr4400/software/configuration/xe-17/isr4400-sw-config-xe-17/isr4400swcfg-xe-16-9-book_chapter_011010.html
https://info.support.huawei.com/network/ptmngsys/Web/tsrev_ar/en/content/ar/29_edesk_user_cannot_ping_gateway/edesk_user_cannot_ping_gateway_edesk002.html
VRF:
https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9600/software/release/17-13/configuration_guide/vxlan/b_1713_bgp_evpn_vxlan_9600_cg/bgp-evpn-vxlan-additional-bgp-features.html
https://info.support.huawei.com/network/ptmngsys/Web/tsrev_security/en/content/security/06_edesk_hrp_settings_sync_failed/edesk_hrp_settings_sync_failed_edesk002.html
BGP:
https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9600/software/release/17-17/command_reference/b_1717_9600_cr/ip_routing_commands.html
https://info.support.huawei.com/network/ptmngsys/Web/tsrev_ar/en/content/ar/23_edesk_can_not_establish_bgp_neighbor/edesk_can_not_establish_bgp_neighbor_edesk004.html
"""

from dataclasses import replace
from pathlib import Path

import pytest

from intentfabric.adapters import SimulatedTransportAdapter
from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.application import OnlinePreFlightChecker
from intentfabric.application.preflight_online import (
    parse_access_port_vlan, parse_active_vlans, parse_existing_interfaces,
    parse_existing_vrfs, parse_local_bgp_asn,
)
from intentfabric.bootstrap import (
    build_online_preflight_checker, build_plugin_catalog, build_pre_validator, load_default_topology,
)
from intentfabric.domain import DeviceTransportError, PreValidationFailedError, ValidationStage
from intentfabric.domain.intent import DiaIntent, L2VpnIntent, L3VpnIntent
from intentfabric.domain.interfaces import abbreviate_interface_name


_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "tests/fixtures/preflight"
_SERVICES = ("dia", "l3vpn", "l2vpn")


def _fixture(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


def _intent(service: str = "dia", pe_vendor: str = "huawei") -> DiaIntent | L3VpnIntent | L2VpnIntent:
    raw = dict(load_intent_mapping(_ROOT / f"examples/intents/{service}_valid.json"))
    if pe_vendor == "cisco":
        raw.update(
            access_node_id="S3-4505-TEST", access_interface="GE0/0/1", pe_node_id="PE1-TEST",
        )
        if service == "l2vpn":
            raw["remote_pe_node_id"] = "PE2-TEST"
    return build_plugin_catalog().parse_intent(raw)


def _transport(intent: DiaIntent | L3VpnIntent | L2VpnIntent) -> SimulatedTransportAdapter:
    return SimulatedTransportAdapter(default_show_outputs={
        "show vlan brief": _fixture("cisco_show_vlan_brief_clean.txt"),
        "display vlan": _fixture("huawei_display_vlan_clean.txt"),
        f"show interfaces {intent.access.customer_port} switchport": _fixture("cisco_show_interfaces_switchport_free.txt"),
        f"display port vlan {intent.access.customer_port}": _fixture("huawei_display_port_vlan_free.txt"),
        "show ip interface brief": _fixture("cisco_show_ip_interface_brief_clean.txt"),
        "display interface brief": _fixture("huawei_display_interface_brief_clean.txt"),
        "show vrf": _fixture("cisco_show_vrf_clean.txt"),
        "display ip vpn-instance": _fixture("huawei_display_ip_vpn_instance_clean.txt"),
        "show bgp all summary": _fixture("cisco_show_bgp_all_summary_clean.txt"),
        "display bgp peer": _fixture("huawei_display_bgp_peer_clean.txt"),
    })


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_documented_fixtures_parse_without_header_false_positives(vendor: str) -> None:
    """Extrae VLAN, PVID, interfaces, VRF y ASN sin incluir encabezados."""
    cisco = vendor == "cisco"
    assert parse_active_vlans(_fixture(f"{vendor}_{'show_vlan_brief' if cisco else 'display_vlan'}_clean.txt"), vendor) == frozenset({1})
    assert parse_access_port_vlan(
        _fixture(f"{vendor}_{'show_interfaces_switchport' if cisco else 'display_port_vlan'}_free.txt"),
        vendor, "Gi1/0/1" if cisco else "GE0/0/1",
    ) == 1
    assert parse_existing_interfaces(
        _fixture(f"{vendor}_{'show_ip_interface_brief' if cisco else 'display_interface_brief'}_clean.txt"), vendor,
    ) == frozenset({"GigabitEthernet0/0/4" if cisco else "GigabitEthernet0/0/0"})
    assert parse_existing_vrfs(
        _fixture(f"{vendor}_{'show_vrf' if cisco else 'display_ip_vpn_instance'}_clean.txt"), vendor,
    ) == frozenset({"TEST-INTERNET", "VRF_CORP_A"})
    assert parse_local_bgp_asn(
        _fixture(f"{vendor}_{'show_bgp_all_summary' if cisco else 'display_bgp_peer'}_clean.txt"), vendor,
    ) == 65000


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_empty_or_header_only_outputs_have_no_invented_values(vendor: str) -> None:
    """Devuelve colecciones vacias o None si no hay valores reconocibles."""
    output = "\nInterface IP-Address Status\nName Default RD\nVPN-Instance Name RD\nTotal VPN-Instances configured : 0\n"
    assert parse_active_vlans(output, vendor) == frozenset()
    assert parse_access_port_vlan(output, vendor, "Gi0/0/1") is None
    assert parse_existing_interfaces(output, vendor) == frozenset()
    assert parse_existing_vrfs(output, vendor) == frozenset()
    assert parse_local_bgp_asn(output, vendor) is None


def test_vlan_parser_obeys_ranges_and_huawei_table_or_active_list() -> None:
    """Limita VLAN a 1..4094 y admite tipos y listados activos especificados."""
    assert parse_active_vlans("0 common\n1 common\n210 mux\n310 super\n4094 common\n4095 common", "huawei") == frozenset({1, 210, 310, 4094})
    assert parse_active_vlans("1 210 310 4094 4095\nThe total number of vlans is : 4", "huawei") == frozenset({1, 210, 310, 4094})
    assert parse_active_vlans("0 default active\n1 default active\n4094 lab active\n4095 invalid active", "cisco") == frozenset({1, 4094})


def test_huawei_port_parser_matches_only_the_requested_interface() -> None:
    """Compara abreviaturas canonicas y omite filas de otras interfaces."""
    output = _fixture("huawei_display_port_vlan_free.txt").replace("GigabitEthernet", "GE")
    assert parse_access_port_vlan(output, "huawei", "GigabitEthernet0/0/1") == 1
    assert parse_access_port_vlan(output, "huawei", "GigabitEthernet0/0/2") is None


@pytest.mark.parametrize("service", _SERVICES)
@pytest.mark.parametrize("pe_vendor", ["cisco", "huawei"])
def test_clean_preflight_checks_each_hop_in_order_read_only(service: str, pe_vendor: str) -> None:
    """Acepta la ruta limpia de cada servicio usando exclusivamente consultas ordenadas."""
    intent = _intent(service, pe_vendor)
    transport = _transport(intent)
    checker = build_online_preflight_checker(transport=transport)
    assert checker.check_preflight(intent) == ()
    access_command = (f"show interfaces {intent.access.customer_port} switchport" if intent.access.vendor == "cisco"
                      else f"display port vlan {intent.access.customer_port}")
    expected = [
        (intent.access.node_id, "show vlan brief" if intent.access.vendor == "cisco" else "display vlan"),
        (intent.access.node_id, access_command),
        (intent.transits[0].node_id, "show vlan brief" if intent.transits[0].vendor == "cisco" else "display vlan"),
        (intent.provider_edge.node_id, "show ip interface brief" if pe_vendor == "cisco" else "display interface brief"),
    ]
    if service == "dia":
        expected.append((intent.provider_edge.node_id, "show vrf" if pe_vendor == "cisco" else "display ip vpn-instance"))
    if service == "l3vpn":
        expected.append((intent.provider_edge.node_id, "show bgp all summary" if pe_vendor == "cisco" else "display bgp peer"))
    assert [(record.node_id, record.commands[0]) for record in transport.history] == expected
    assert all(record.mode == "show" and not record.committed for record in transport.history)


@pytest.mark.parametrize("pe_vendor", ["cisco", "huawei"])
def test_preflight_accumulates_all_dia_collisions_in_hop_order(pe_vendor: str) -> None:
    """Detecta colisiones de VLAN, puerto, subinterfaz y ausencia de VRF con ubicacion exacta."""
    intent = _intent(pe_vendor=pe_vendor)
    transport = _transport(intent)
    for hop in (intent.access, *intent.transits):
        cisco = hop.vendor == "cisco"
        command = "show vlan brief" if cisco else "display vlan"
        source = _fixture("cisco_show_vlan_brief_clean.txt" if cisco else "huawei_display_vlan_clean.txt")
        transport.set_show_output(hop.node_id, command, source.replace("1    ", f"{intent.vlan_id}    "))
    cisco_access = intent.access.vendor == "cisco"
    port_command = (f"show interfaces {intent.access.customer_port} switchport" if cisco_access
                    else f"display port vlan {intent.access.customer_port}")
    port_output = _fixture("cisco_show_interfaces_switchport_free.txt" if cisco_access else "huawei_display_port_vlan_free.txt")
    port_output = port_output.replace("VLAN: 1", "VLAN: 210") if cisco_access else port_output.replace("access       1", "access       210")
    transport.set_show_output(intent.access.node_id, port_command, port_output)
    cisco_pe = pe_vendor == "cisco"
    interface_command = "show ip interface brief" if cisco_pe else "display interface brief"
    interface_output = _fixture("cisco_show_ip_interface_brief_clean.txt" if cisco_pe else "huawei_display_interface_brief_clean.txt")
    abbreviated = abbreviate_interface_name(intent.provider_edge.parent_interface, pe_vendor)
    parent = "GigabitEthernet0/0/4" if cisco_pe else "GigabitEthernet0/0/0"
    transport.set_show_output(intent.provider_edge.node_id, interface_command, interface_output.replace(parent, f"{abbreviated}.{intent.vlan_id}"))
    transport.set_show_output(intent.provider_edge.node_id, "show vrf" if cisco_pe else "display ip vpn-instance", "")
    issues = build_online_preflight_checker(transport=transport).check_preflight(intent)
    assert [issue.code for issue in issues] == [
        "VLAN_COLLISION", "CLIENT_PORT_BUSY", "VLAN_COLLISION", "SUBINTERFACE_ALREADY_EXISTS", "MISSING_BASE_VRF",
    ]
    assert [issue.node_id for issue in issues] == [intent.access.node_id, intent.access.node_id, intent.transits[0].node_id, intent.provider_edge.node_id, intent.provider_edge.node_id]
    assert [issue.field_path for issue in issues] == ["vlan_id", "hops[0].customer_port", "vlan_id", "vlan_id", "vrf_name"]
    assert all(issue.stage == ValidationStage.PREFLIGHT_ONLINE for issue in issues)
    assert issues[0].message == f"vlan_id: la VLAN {intent.vlan_id} ya existe en {intent.access.node_id}."
    assert issues[1].message == f"customer_port: el puerto {intent.access.customer_port} ya pertenece a la VLAN 210 en {intent.access.node_id}."
    assert f"{intent.provider_edge.parent_interface}.{intent.vlan_id}" in issues[3].message


@pytest.mark.parametrize("pe_vendor", ["cisco", "huawei"])
@pytest.mark.parametrize("bgp_state", ["absent", "wrong_asn", "matching_asn"])
def test_l3vpn_requires_local_bgp_and_allows_existing_shared_vrf(pe_vendor: str, bgp_state: str) -> None:
    """Permite VRF compartida y rechaza solo ausencia o ASN local BGP distinto."""
    intent = _intent("l3vpn", pe_vendor)
    transport = _transport(intent)
    command = "show bgp all summary" if pe_vendor == "cisco" else "display bgp peer"
    fixture = "cisco_show_bgp_all_summary_clean.txt" if pe_vendor == "cisco" else "huawei_display_bgp_peer_clean.txt"
    output = _fixture(fixture)
    if bgp_state == "absent":
        output = ""
    elif bgp_state == "wrong_asn":
        output = output.replace("65000", "65001")
    transport.set_show_output(intent.provider_edge.node_id, command, output)
    checker = OnlinePreFlightChecker(load_default_topology(), transport)
    report = build_pre_validator(preflight_checker=checker).validate(intent)
    assert report.preflight_executed
    assert report.is_valid is (bgp_state == "matching_asn")
    assert [issue.code for issue in report.issues] == ([] if report.is_valid else ["BGP_PROCESS_NOT_RUNNING"])
    assert all(record.commands[0] not in ("show vrf", "display ip vpn-instance") for record in transport.history)
    if report.errors:
        issue = report.errors[0]
        assert (issue.field_path, issue.node_id) == ("pe_asn", intent.provider_edge.node_id)
        assert issue.message == f"pe_asn: BGP con ASN {intent.pe_asn} no esta activo en {intent.provider_edge.node_id}."


def test_prevalidation_short_circuits_before_online_queries_on_static_error() -> None:
    """Un fallo estatico impide toda consulta online al transporte."""
    intent = replace(_intent(), bandwidth_mbps=1001)
    transport = _transport(intent)
    topology = load_default_topology()
    checker = build_online_preflight_checker(topology, transport=transport)
    validator = build_pre_validator(build_plugin_catalog(topology), topology=topology, preflight_checker=checker)
    report = validator.validate(intent)
    assert not report.is_valid and not report.preflight_executed
    assert transport.history == ()
    with pytest.raises(PreValidationFailedError):
        validator.require_valid(report)


def test_prevalidation_exposes_online_issues_and_is_repeatable() -> None:
    """Integra hallazgos online en el reporte y exige validez antes de continuar."""
    intent = _intent()
    transport = _transport(intent)
    transport.set_show_output(intent.provider_edge.node_id, "display ip vpn-instance", "")
    validator = build_pre_validator(preflight_checker=build_online_preflight_checker(transport=transport))
    first = validator.validate(intent)
    assert first.to_dict() == validator.validate(intent).to_dict()
    assert first.preflight_executed
    with pytest.raises(PreValidationFailedError) as caught:
        validator.validate_and_require(intent)
    assert caught.value.report.issues[0].code == "MISSING_BASE_VRF"
    assert not build_pre_validator().validate(intent).preflight_executed


def test_transport_failure_aborts_preflight_without_configuring_any_node() -> None:
    """Propaga un fallo de transporte y corta antes de consultar saltos posteriores."""
    intent = _intent()
    transport = SimulatedTransportAdapter(failing_nodes={intent.access.node_id: OSError("lab offline")})
    with pytest.raises(DeviceTransportError, match="lab offline"):
        build_online_preflight_checker(transport=transport).check_preflight(intent)
    assert transport.history == ()
