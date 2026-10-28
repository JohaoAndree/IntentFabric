"""Verifica las configuraciones DIA contra las doce referencias aprobadas."""

from dataclasses import replace
from hashlib import sha256
from itertools import product
from pathlib import Path

import pytest

from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.bootstrap import build_generator, build_plugin_catalog, build_template_source
from intentfabric.domain.intent import DiaIntent
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey


_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def reference_intent() -> DiaIntent:
    """Proporciona la intencion de laboratorio a 100 Mbps definida en ADR-006."""
    catalog = build_plugin_catalog()
    intent = catalog.parse_intent(load_intent_mapping(_PROJECT_ROOT / "examples/intents/dia_valid.json"))
    return replace(intent, bandwidth_mbps=100, qos_policy_name="LAB_100MB_PARENT")


@pytest.mark.parametrize("vendors", tuple(product(("cisco", "huawei"), repeat=3)))
@pytest.mark.parametrize("operation", tuple(Operation))
def test_generation_matches_golden_bytes_and_hashes_for_every_vendor_path(
    reference_intent: DiaIntent, vendors: tuple[str, str, str], operation: Operation,
) -> None:
    """Reproduce los doce Golden en rutas homogeneas y mixtas con hashes estables."""
    intent = replace(
        reference_intent,
        access=replace(reference_intent.access, vendor=vendors[0]),
        transits=(replace(reference_intent.transits[0], vendor=vendors[1]),),
        provider_edge=replace(reference_intent.provider_edge, vendor=vendors[2]),
    )
    generator = build_generator()
    plan = generator.generate(intent, operation=operation.value)
    repeated = generator.generate(intent, operation=operation)
    assert plan == repeated
    assert plan.to_dict() == repeated.to_dict()
    assert len(plan.artifacts) == 3
    for index, artifact in enumerate(plan.artifacts):
        golden_path = _PROJECT_ROOT / "tests/golden/dia" / (
            f"{artifact.vendor}_{operation.value}_{artifact.role.value}.txt"
        )
        golden_bytes = golden_path.read_bytes()
        assert b"\r" not in golden_bytes
        assert golden_bytes.endswith(b"\n") and not golden_bytes.endswith(b"\n\n")
        assert artifact.rendered_text.encode("utf-8") == golden_bytes
        assert artifact.sha256 == sha256(golden_bytes).hexdigest()
        assert artifact.hop_index == index
        assert artifact.node_id == str(intent.hops[index].management_ip)
        assert artifact.management_ip == intent.hops[index].management_ip
        assert artifact.commands == tuple(golden_bytes.decode("utf-8").splitlines())
        assert artifact.template_key == TemplateKey("DIA", operation, intent.hops[index].role)
    hash_input = "|".join(
        f"{artifact.hop_index}:{artifact.node_id}:{artifact.sha256}"
        for artifact in plan.artifacts
    )
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


@pytest.mark.parametrize("vendor_id", ("cisco", "huawei"))
def test_access_and_transit_modes_and_native_pe_qos(
    reference_intent: DiaIntent, vendor_id: str,
) -> None:
    """Garantiza description unica, modos de puerto y escalado QoS del fabricante."""
    intent = replace(
        reference_intent,
        access=replace(reference_intent.access, vendor=vendor_id),
        transits=(replace(reference_intent.transits[0], vendor=vendor_id),),
        provider_edge=replace(reference_intent.provider_edge, vendor=vendor_id),
    )
    catalog = build_plugin_catalog()
    generator = build_generator(catalog)
    access, transit, pe = generator.generate(intent).artifacts
    for index in range(3):
        context = catalog.build_hop_context(intent, index, Operation.PROVISION)
        assert "vlan_name" not in context
        assert context["description"] == intent.description
    if vendor_id == "cisco":
        assert f" name {intent.description}\n" in access.rendered_text
        assert f" name {intent.description}\n" in transit.rendered_text
        assert " switchport mode access\n" in access.rendered_text
        assert " switchport mode trunk\n" in access.rendered_text
        assert transit.rendered_text.count(" switchport mode trunk\n") == 2
        assert "police rate 100000000 bps\n" in pe.rendered_text
    else:
        assert " port link-type access\n" in access.rendered_text
        assert " port link-type trunk\n" in access.rendered_text
        assert transit.rendered_text.count(" port link-type trunk\n") == 2
        assert f" description {intent.description}\n" in transit.rendered_text
        assert " car cir 100000 pir 100000\n" in pe.rendered_text
        assert f"traffic policy {intent.qos_policy_name}\n" in pe.rendered_text
    assert access.rendered_text.count(intent.description) == 2
    assert f" description {intent.description}\n" in pe.rendered_text
    teardown = generator.generate(intent, operation=Operation.TEARDOWN)
    assert " shutdown\n" in teardown.artifacts[0].rendered_text
    assert "shutdown" not in teardown.artifacts[1].rendered_text
