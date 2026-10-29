"""Verifica configuraciones L3VPN contra las doce referencias de rutas aprobadas."""

from hashlib import sha256
from pathlib import Path

import pytest

from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.bootstrap import build_generator, build_plugin_catalog, build_template_source
from intentfabric.domain.intent import L3VpnIntent
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ROUTES = (("S3-9306-TEST", "PE2-TEST"), ("S3-4505-TEST", "PE1-TEST"))


def _reference_intent(access_node_id: str, pe_node_id: str) -> L3VpnIntent:
    raw = dict(load_intent_mapping(_PROJECT_ROOT / "examples/intents/l3vpn_valid.json"))
    if access_node_id == "S3-4505-TEST":
        raw.update(
            description="L3VPN-CORP-000002", vlan_id=210, wan_network="172.16.20.0/30",
            bandwidth_mbps=200, qos_policy="QOS_L3VPN_200M", rd="65000:210", ce_asn=65210,
            access_node_id=access_node_id, pe_node_id=pe_node_id,
            access_interface="GigabitEthernet0/0/1",
        )
    return build_plugin_catalog().parse_intent(raw)


@pytest.mark.parametrize(("access_node_id", "pe_node_id"), _ROUTES)
@pytest.mark.parametrize("operation", tuple(Operation))
def test_generation_matches_golden_bytes_and_hashes_for_every_vendor_path(
    access_node_id: str, pe_node_id: str, operation: Operation,
) -> None:
    """Reproduce los doce Golden en las dos rutas reales con identidad y hashes estables."""
    intent = _reference_intent(access_node_id, pe_node_id)
    generator = build_generator()
    plan = generator.generate(intent, operation=operation.value)
    repeated = generator.generate(intent, operation=operation)
    assert plan == repeated
    assert plan.to_dict() == repeated.to_dict()
    assert len(plan.artifacts) == 3
    example = _PROJECT_ROOT / "examples/intents/l3vpn_valid"
    if access_node_id == "S3-9306-TEST":
        for suffix in ("json", "yaml"):
            equivalent = build_plugin_catalog().parse_intent(load_intent_mapping(example.with_suffix(f".{suffix}")))
            assert generator.generate(equivalent, operation=operation) == plan
    for index, artifact in enumerate(plan.artifacts):
        path = _PROJECT_ROOT / "tests/golden/l3vpn" / f"{artifact.vendor}_{operation.value}_{artifact.role.value}.txt"
        golden_bytes = path.read_bytes()
        assert b"\r" not in golden_bytes
        assert golden_bytes.endswith(b"\n") and not golden_bytes.endswith(b"\n\n")
        assert artifact.rendered_text.encode("utf-8") == golden_bytes
        assert artifact.sha256 == sha256(golden_bytes).hexdigest()
        assert artifact.hop_index == index
        assert artifact.node_id == intent.hops[index].node_id
        assert artifact.management_ip == intent.hops[index].management_ip
        expected_commands = tuple(
            line for line in golden_bytes.decode("utf-8").splitlines()
            if line.strip() not in ("!", "#")
        )
        assert artifact.commands == expected_commands
        assert artifact.template_key == TemplateKey("L3VPN", operation, intent.hops[index].role)
    expected_ids = (("S3-9306-TEST", "S1-9306-TEST", "PE2-TEST") if access_node_id == "S3-9306-TEST"
                    else ("S3-4505-TEST", "S1-4505-TEST", "PE1-TEST"))
    assert tuple(artifact.node_id for artifact in plan.artifacts) == expected_ids
    hash_input = "|".join(f"{artifact.hop_index}:{artifact.node_id}:{artifact.sha256}" for artifact in plan.artifacts)
    assert plan.plan_sha256 == sha256(hash_input.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("vendor_id", ("cisco", "huawei"))
@pytest.mark.parametrize("operation", tuple(Operation))
@pytest.mark.parametrize("role", tuple(NodeRole))
def test_packaged_source_loads_every_declared_l3vpn_template(
    vendor_id: str, operation: Operation, role: NodeRole,
) -> None:
    """Resuelve y lee cada una de las doce plantillas reales en UTF-8."""
    catalog = build_plugin_catalog()
    key = TemplateKey("L3VPN", operation, role)
    resource_path = catalog.resolve_template(vendor_id, key)
    assert resource_path == f"templates/l3vpn/{operation.value}/{role.value}.j2"
    assert build_template_source().read_text(vendor_id, resource_path).strip()


@pytest.mark.parametrize(("access_node_id", "pe_node_id"), _ROUTES)
def test_access_mode_existing_trunk_vlan_propagation_and_native_pe_qos(
    access_node_id: str, pe_node_id: str,
) -> None:
    """Garantiza acceso, propagacion VLAN sobre troncales existentes y QoS nativo."""
    intent = _reference_intent(access_node_id, pe_node_id)
    catalog = build_plugin_catalog()
    generator = build_generator(catalog)
    access, transit, pe = generator.generate(intent).artifacts
    for index in range(3):
        context = catalog.build_hop_context(intent, index, Operation.PROVISION)
        assert "vlan_name" not in context
        assert context["description"] == intent.description
        assert context["node_id"] == intent.hops[index].node_id
    access_command = "switchport mode access" if access.vendor == "cisco" else "port link-type access"
    access_trunk = "switchport trunk allowed vlan add" if access.vendor == "cisco" else "port trunk allow-pass vlan"
    transit_trunk = "switchport trunk allowed vlan add" if transit.vendor == "cisco" else "port trunk allow-pass vlan"
    assert f" {access_command}\n" in access.rendered_text
    assert f"interface {intent.access.uplink_interface}\n {access_trunk} {intent.vlan_id}\n" in access.rendered_text
    assert transit.rendered_text.count(f" {transit_trunk} {intent.vlan_id}\n") == 2
    if pe.vendor == "cisco":
        assert "  police rate 200000000 bps peak-rate 200000000 bps\n" in pe.rendered_text
        assert "vrf definition VRF_CORP_A\n" in pe.rendered_text
        assert "router bgp 65000\n address-family ipv4 vrf VRF_CORP_A\n  redistribute connected\n" in pe.rendered_text
        assert "  neighbor 172.16.20.2 remote-as 65210\n" in pe.rendered_text
        assert "  neighbor 172.16.20.2 activate\n" in pe.rendered_text
    else:
        assert " car cir 100000 pir 100000\n" in pe.rendered_text
        assert "ip vpn-instance VRF_CORP_A\n" in pe.rendered_text
        assert "bgp 65000\n ipv4-family vpn-instance VRF_CORP_A\n  import-route direct\n" in pe.rendered_text
        assert "  peer 172.16.10.2 as-number 65110\n" in pe.rendered_text
        assert f"traffic policy {intent.qos_policy_name}\n" in pe.rendered_text
    assert access.rendered_text.count(intent.description) == 2
    assert f" description {intent.description}\n" in pe.rendered_text
    teardown = generator.generate(intent, operation=Operation.TEARDOWN)
    for artifact in (access, transit, *teardown.artifacts[:2]):
        assert "switchport mode trunk" not in artifact.rendered_text
        assert "port link-type trunk" not in artifact.rendered_text
    for index, artifact in enumerate(teardown.artifacts[:2]):
        removal = "switchport trunk allowed vlan remove" if artifact.vendor == "cisco" else "undo port trunk allow-pass vlan"
        assert artifact.rendered_text.count(f" {removal} {intent.vlan_id}\n") == index + 1
    assert " shutdown\n" in teardown.artifacts[0].rendered_text
    assert "shutdown" not in teardown.artifacts[1].rendered_text


@pytest.mark.parametrize("vendor_id", ("cisco", "huawei"))
@pytest.mark.parametrize("operation", tuple(Operation))
@pytest.mark.parametrize("role", (NodeRole.ACCESS, NodeRole.TRANSIT))
def test_l2_templates_are_identical_to_approved_dia_templates(
    vendor_id: str, operation: Operation, role: NodeRole,
) -> None:
    """Conserva exactamente el transporte L2 de las plantillas DIA aprobadas."""
    directory = _PROJECT_ROOT / "src/intentfabric/vendors" / vendor_id / "templates"
    relative = Path(operation.value) / f"{role.value}.j2"
    assert (directory / "l3vpn" / relative).read_bytes() == (directory / "dia" / relative).read_bytes()


@pytest.mark.parametrize(("access_node_id", "pe_node_id"), _ROUTES)
def test_teardown_removes_vrf_family_interface_and_qos_in_approved_order(
    access_node_id: str, pe_node_id: str,
) -> None:
    """Retira familia BGP, subinterfaz, QoS y VRF en el orden aprobado."""
    intent = _reference_intent(access_node_id, pe_node_id)
    rendered = build_generator().generate(intent, operation=Operation.TEARDOWN).artifacts[-1].rendered_text
    if intent.provider_edge.vendor == "cisco":
        removals = (
            " no address-family ipv4 vrf VRF_CORP_A", "no interface GigabitEthernet0/0/4.210",
            "no policy-map QOS_L3VPN_200M", "no vrf definition VRF_CORP_A",
        )
    else:
        removals = (
            " undo ipv4-family vpn-instance VRF_CORP_A", "undo interface GigabitEthernet0/0/0.110",
            "undo traffic policy QOS_L3VPN_100M", "undo traffic behavior QOS_L3VPN_100M_BEHAVIOR",
            "undo traffic classifier QOS_L3VPN_100M_CLASS", "undo ip vpn-instance VRF_CORP_A",
        )
    offsets = [rendered.index(command + "\n") for command in removals]
    assert offsets == sorted(offsets)
