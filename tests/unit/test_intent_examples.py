"""Verifica la equivalencia de los ejemplos JSON y YAML de DIA."""

from ipaddress import IPv4Address, IPv4Network
from pathlib import Path

from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.bootstrap import build_intent_parser_registry
from intentfabric.domain.derivations import derive_qos_rates, derive_wan_addresses
from intentfabric.domain.intent import AccessHop, DiaIntent, ProviderEdgeHop, TransitHop


def test_json_and_yaml_examples_produce_same_reference_intent() -> None:
    """Produce la intención de referencia completa desde ambos formatos de ejemplo."""
    directory = Path(__file__).resolve().parents[2] / "examples" / "intents"
    registry = build_intent_parser_registry()
    json_raw = load_intent_mapping(directory / "dia_valid.json")
    yaml_raw = load_intent_mapping(directory / "dia_valid.yaml")
    expected = DiaIntent(
        description="LAB#INTE#0001", vlan_id=3001, vrf_name="LAB-INTERNET",
        wan_network=IPv4Network("10.255.0.0/30"), lan_network=IPv4Network("203.0.113.0/29"),
        bandwidth_mbps=50, qos_policy_name="LAB_50MB_PARENT",
        access=AccessHop(
            "huawei", IPv4Address("192.0.2.11"),
            "GigabitEthernet0/0/1", "GigabitEthernet0/0/24",
        ),
        transits=(TransitHop(
            "cisco", IPv4Address("192.0.2.12"),
            "GigabitEthernet1/0/23", "GigabitEthernet1/0/24",
        ),),
        provider_edge=ProviderEdgeHop(
            "huawei", IPv4Address("192.0.2.21"), "GigabitEthernet0/0/1",
        ),
    )
    assert json_raw == yaml_raw
    assert registry.parse(json_raw) == registry.parse(yaml_raw) == expected
    assert registry.parse(json_raw) == registry.parse(json_raw)
    assert derive_wan_addresses(expected.wan_network).pe_address == IPv4Address("10.255.0.1")
    assert derive_qos_rates(expected.bandwidth_mbps).cir_kbps == 5376
