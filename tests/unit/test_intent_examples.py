"""Verifica la equivalencia de los ejemplos JSON y YAML de DIA."""

from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.bootstrap import build_plugin_catalog
from intentfabric.domain.derivations import derive_qos_rates, derive_wan_addresses
from intentfabric.domain.intent import AccessHop, DiaIntent, L3VpnIntent, ProviderEdgeHop, TransitHop


def test_json_and_yaml_examples_produce_same_reference_intent() -> None:
    """Produce la intención de referencia completa desde ambos formatos de ejemplo."""
    directory = Path(__file__).resolve().parents[2] / "examples" / "intents"
    catalog = build_plugin_catalog()
    json_raw = load_intent_mapping(directory / "dia_valid.json")
    yaml_raw = load_intent_mapping(directory / "dia_valid.yaml")
    expected = DiaIntent(
        description="TEST-0000000001", vlan_id=10, vrf_name="TEST-INTERNET",
        wan_network=IPv4Network("192.168.10.0/30"), lan_network=IPv4Network("10.50.1.8/29"),
        bandwidth_mbps=100, qos_policy_name="TEST_POLICY",
        access=AccessHop(
            "S3-9306-TEST", "cisco", IPv4Address("192.168.56.101"),
            "GigabitEthernet1/0/1", "GigabitEthernet1/0/10",
        ),
        transits=(TransitHop(
            "S1-9306-TEST", "huawei", IPv4Address("192.168.56.102"),
            "GigabitEthernet1/0/24", "GigabitEthernet1/0/25",
        ),),
        provider_edge=ProviderEdgeHop(
            "PE2-TEST", "huawei", IPv4Address("192.168.56.103"), "GigabitEthernet0/0/0",
        ),
    )
    assert json_raw == yaml_raw
    assert catalog.parse_intent(json_raw) == catalog.parse_intent(yaml_raw) == expected
    assert catalog.parse_intent(json_raw) == catalog.parse_intent(json_raw)
    assert derive_wan_addresses(expected.wan_network).pe_address == IPv4Address("192.168.10.1")
    assert derive_qos_rates(expected.bandwidth_mbps).cir_kbps == 100_000
    assert derive_qos_rates(expected.bandwidth_mbps).pir_kbps == 100_000


def test_examples_contain_only_service_parameters_and_demarcations() -> None:
    """Excluye gestion, fabricantes y saltos fisicos de ambos ejemplos declarativos."""
    directory = Path(__file__).resolve().parents[2] / "examples/intents"
    for suffix in ("json", "yaml"):
        raw = load_intent_mapping(directory / f"dia_valid.{suffix}")
        assert set(raw) == {"service_type", "description", "vlan_id", "vrf_name", "wan_subnet", "lan_subnet", "bandwidth_mbps", "qos_policy_name", "access_node_id", "access_interface", "pe_node_id"}


def test_l3vpn_json_yaml_examples_match_the_approved_inventory_endpoint() -> None:
    """Produce el extremo L3VPN aprobado con identidades topologicas y ASN derivados."""
    directory = Path(__file__).resolve().parents[2] / "examples/intents"
    catalog = build_plugin_catalog()
    json_raw = load_intent_mapping(directory / "l3vpn_valid.json")
    yaml_raw = load_intent_mapping(directory / "l3vpn_valid.yaml")
    expected = L3VpnIntent(
        description="L3VPN-CORP-000001", vlan_id=110, vrf_name="VRF_CORP_A",
        wan_network=IPv4Network("172.16.10.0/30"), bandwidth_mbps=100,
        qos_policy_name="QOS_L3VPN_100M", rd="65000:110", rt_import="65000:110",
        rt_export="65000:110", pe_asn=65000, ce_asn=65110,
        access=AccessHop("S3-9306-TEST", "cisco", IPv4Address("192.168.56.101"), "GigabitEthernet1/0/1", "GigabitEthernet1/0/10"),
        transits=(TransitHop("S1-9306-TEST", "huawei", IPv4Address("192.168.56.102"), "GigabitEthernet1/0/24", "GigabitEthernet1/0/25"),),
        provider_edge=ProviderEdgeHop("PE2-TEST", "huawei", IPv4Address("192.168.56.103"), "GigabitEthernet0/0/0"),
    )
    assert json_raw == yaml_raw
    assert set(json_raw) == {
        "service_type", "description", "vlan_id", "wan_network", "bandwidth_mbps",
        "vrf_name", "qos_policy", "rd", "rt_import", "rt_export", "ce_asn",
        "access_node_id", "access_interface", "pe_node_id",
    }
    assert catalog.parse_intent(json_raw) == catalog.parse_intent(yaml_raw) == expected
