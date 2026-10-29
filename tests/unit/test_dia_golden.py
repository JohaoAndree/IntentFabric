"""Verifica configuraciones DIA contra las doce referencias de rutas aprobadas."""

from hashlib import sha256
from pathlib import Path

import pytest

from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.bootstrap import build_generator, build_plugin_catalog, build_template_source
from intentfabric.domain.intent import DiaIntent
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ROUTES = (("S3-9306-TEST", "PE2-TEST"), ("S3-4505-TEST", "PE1-TEST"))


def _reference_intent(access_node_id: str, pe_node_id: str) -> DiaIntent:
    raw = dict(load_intent_mapping(_PROJECT_ROOT / "examples/intents/dia_valid.json"))
    raw.update(access_node_id=access_node_id, pe_node_id=pe_node_id,
               access_interface="Gi1/0/1" if access_node_id == "S3-9306-TEST" else "GE0/0/1")
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
    for index, artifact in enumerate(plan.artifacts):
        path = _PROJECT_ROOT / "tests/golden/dia" / f"{artifact.vendor}_{operation.value}_{artifact.role.value}.txt"
        golden_bytes = path.read_bytes()
        assert b"\r" not in golden_bytes
        assert golden_bytes.endswith(b"\n") and not golden_bytes.endswith(b"\n\n")
        assert artifact.rendered_text.encode("utf-8") == golden_bytes
        assert artifact.sha256 == sha256(golden_bytes).hexdigest()
        assert artifact.hop_index == index
        assert artifact.node_id == intent.hops[index].node_id
        assert artifact.management_ip == intent.hops[index].management_ip
        assert artifact.commands == tuple(golden_bytes.decode("utf-8").splitlines())
        assert artifact.template_key == TemplateKey("DIA", operation, intent.hops[index].role)
    expected_ids = (("S3-9306-TEST", "S1-9306-TEST", "PE2-TEST") if access_node_id == "S3-9306-TEST"
                    else ("S3-4505-TEST", "S1-4505-TEST", "PE1-TEST"))
    assert tuple(artifact.node_id for artifact in plan.artifacts) == expected_ids
    hash_input = "|".join(f"{artifact.hop_index}:{artifact.node_id}:{artifact.sha256}" for artifact in plan.artifacts)
    assert plan.plan_sha256 == sha256(hash_input.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("vendor_id", ("cisco", "huawei"))
@pytest.mark.parametrize("operation", tuple(Operation))
@pytest.mark.parametrize("role", tuple(NodeRole))
def test_packaged_source_loads_every_declared_dia_template(
    vendor_id: str, operation: Operation, role: NodeRole,
) -> None:
    """Resuelve y lee cada una de las doce plantillas reales en UTF-8."""
    catalog = build_plugin_catalog()
    key = TemplateKey("DIA", operation, role)
    resource_path = catalog.resolve_template(vendor_id, key)
    assert resource_path == f"templates/dia/{operation.value}/{role.value}.j2"
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
        assert "police rate 100000000 bps\n" in pe.rendered_text
    else:
        assert " car cir 100000 pir 100000\n" in pe.rendered_text
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
