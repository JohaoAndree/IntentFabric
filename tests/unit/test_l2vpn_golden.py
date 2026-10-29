"""Verifica configuraciones L2VPN contra las dieciseis referencias de rutas aprobadas."""

from hashlib import sha256
from pathlib import Path

import pytest

from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.bootstrap import build_generator, build_plugin_catalog, build_template_source
from intentfabric.domain.intent import L2VpnIntent
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ROUTES = (("S3-9306-TEST", "PE2-TEST"), ("S3-4505-TEST", "PE1-TEST"))


def _reference_intent(access_node_id: str, pe_node_id: str) -> L2VpnIntent:
    raw = dict(load_intent_mapping(_PROJECT_ROOT / "examples/intents/l2vpn_valid.json"))
    if access_node_id == "S3-4505-TEST":
        raw.update(
            description="L2VPN-CORP-000002", vlan_id=410, pw_id=410, evi_id=410,
            bandwidth_mbps=200, qos_policy="QOS_L2VPN_200M", rd="65000:410",
            local_ac_id=3102, remote_ac_id=3101, remote_pe_node_id="PE2-TEST",
            access_node_id=access_node_id, pe_node_id=pe_node_id,
            access_interface="GigabitEthernet0/0/1",
        )
    return build_plugin_catalog().parse_intent(raw)


@pytest.mark.parametrize(("access_node_id", "pe_node_id"), _ROUTES)
@pytest.mark.parametrize("variant", ("default", "evpn_vpws", "martini_ldp"))
@pytest.mark.parametrize("operation", tuple(Operation))
def test_generation_matches_golden_bytes_and_hashes_for_every_vendor_path(
    access_node_id: str, pe_node_id: str, operation: Operation, variant: str,
) -> None:
    """Reproduce los Golden de ambas rutas con identidad, variantes y hashes estables."""
    intent = _reference_intent(access_node_id, pe_node_id)
    generator = build_generator()
    plan = generator.generate(intent, operation=operation.value, variant=variant)
    repeated = generator.generate(intent, operation=operation, variant=variant)
    assert plan == repeated
    assert plan.to_dict() == repeated.to_dict()
    assert len(plan.artifacts) == 3
    example = _PROJECT_ROOT / "examples/intents/l2vpn_valid"
    if access_node_id == "S3-9306-TEST":
        for suffix in ("json", "yaml"):
            equivalent = build_plugin_catalog().parse_intent(load_intent_mapping(example.with_suffix(f".{suffix}")))
            assert generator.generate(equivalent, operation=operation, variant=variant) == plan
    for index, artifact in enumerate(plan.artifacts):
        suffix = f"_{'martini_ldp' if variant == 'martini_ldp' else 'evpn_vpws'}" if artifact.role == NodeRole.PROVIDER_EDGE else ""
        path = _PROJECT_ROOT / "tests/golden/l2vpn" / f"{artifact.vendor}_{operation.value}_{artifact.role.value}{suffix}.txt"
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
        assert artifact.template_key == TemplateKey("L2VPN", operation, intent.hops[index].role, variant)
    expected_ids = (("S3-9306-TEST", "S1-9306-TEST", "PE2-TEST") if access_node_id == "S3-9306-TEST"
                    else ("S3-4505-TEST", "S1-4505-TEST", "PE1-TEST"))
    assert tuple(artifact.node_id for artifact in plan.artifacts) == expected_ids
    hash_input = "|".join(f"{artifact.hop_index}:{artifact.node_id}:{artifact.sha256}" for artifact in plan.artifacts)
    assert plan.plan_sha256 == sha256(hash_input.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("vendor_id", ("cisco", "huawei"))
@pytest.mark.parametrize("variant", ("default", "evpn_vpws", "martini_ldp"))
@pytest.mark.parametrize("operation", tuple(Operation))
@pytest.mark.parametrize("role", tuple(NodeRole))
def test_packaged_source_loads_every_declared_l2vpn_template(
    vendor_id: str, operation: Operation, role: NodeRole, variant: str,
) -> None:
    """Resuelve las 36 plantillas L2VPN en UTF-8 por su variante declarada."""
    catalog = build_plugin_catalog()
    key = TemplateKey("L2VPN", operation, role, variant)
    resource_path = catalog.resolve_template(vendor_id, key)
    suffix = "" if variant == "default" else f".{variant}"
    assert resource_path == f"templates/l2vpn/{operation.value}/{role.value}{suffix}.j2"
    assert build_template_source().read_text(vendor_id, resource_path).strip()


@pytest.mark.parametrize("vendor_id", ("cisco", "huawei"))
@pytest.mark.parametrize("operation", tuple(Operation))
@pytest.mark.parametrize("role", (NodeRole.ACCESS, NodeRole.TRANSIT))
@pytest.mark.parametrize("variant", ("default", "evpn_vpws", "martini_ldp"))
def test_transport_templates_match_approved_dia_and_l3vpn_bytes(
    vendor_id: str, operation: Operation, role: NodeRole, variant: str,
) -> None:
    """Conserva transporte L2 identico a DIA y L3VPN en las tres variantes."""
    directory = _PROJECT_ROOT / "src/intentfabric/vendors" / vendor_id / "templates"
    suffix = "" if variant == "default" else f".{variant}"
    relative = Path(operation.value) / f"{role.value}.j2"
    actual = (directory / "l2vpn" / operation.value / f"{role.value}{suffix}.j2").read_bytes()
    assert actual == (directory / "dia" / relative).read_bytes() == (directory / "l3vpn" / relative).read_bytes()


@pytest.mark.parametrize(("access_node_id", "pe_node_id"), _ROUTES)
@pytest.mark.parametrize("operation", tuple(Operation))
def test_default_and_explicit_evpn_have_identical_bytes_and_hashes(
    access_node_id: str, pe_node_id: str, operation: Operation,
) -> None:
    """Garantiza default como alias EVPN exacto en textos y hashes del plan."""
    intent = _reference_intent(access_node_id, pe_node_id)
    generator = build_generator()
    default = generator.generate(intent, operation=operation)
    evpn = generator.generate(intent, operation=operation, variant="evpn_vpws")
    assert default.plan_sha256 == evpn.plan_sha256
    assert tuple(item.rendered_text for item in default.artifacts) == tuple(item.rendered_text for item in evpn.artifacts)
    assert tuple(item.sha256 for item in default.artifacts) == tuple(item.sha256 for item in evpn.artifacts)


@pytest.mark.parametrize(("access_node_id", "pe_node_id"), _ROUTES)
@pytest.mark.parametrize("variant", ("default", "evpn_vpws", "martini_ldp"))
def test_pe_uses_variant_signaling_and_decimal_qos_without_customer_ip(
    access_node_id: str, pe_node_id: str, variant: str,
) -> None:
    """Aplica senalizacion elegida y QoS decimal al circuito sin direccionamiento IP."""
    intent = _reference_intent(access_node_id, pe_node_id)
    catalog = build_plugin_catalog()
    context = catalog.build_hop_context(intent, 2, Operation.PROVISION)
    text = build_generator(catalog).generate(intent, variant=variant).artifacts[-1].rendered_text
    if intent.provider_edge.vendor == "cisco":
        assert context["cir_bps"] == context["pir_bps"] == 200000000
        assert "  police rate 200000000 bps peak-rate 200000000 bps\n" in text
        signaling = " xconnect 10.255.0.2 410 encapsulation mpls\n" if variant == "martini_ldp" else "  service target 3101 source 3102\n"
    else:
        assert context["cir_kbps"] == context["pir_kbps"] == 100000
        assert " car cir 100000 pir 100000\n" in text
        signaling = " mpls l2vc 10.255.0.1 310\n" if variant == "martini_ldp" else " local-service-id 3101 remote-service-id 3102\n"
    assert signaling in text
    assert "ip address" not in text
    if variant == "martini_ldp":
        assert "evpn" not in text and "evpl" not in text
    else:
        assert "encapsulation mpls" not in text and "mpls l2vc" not in text
