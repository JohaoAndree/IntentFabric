"""Garantiza renderizado estricto, contextos aislados y artefactos reproducibles."""

from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, dataclass, fields, replace
from ipaddress import IPv4Address, IPv4Network
import json
from pathlib import Path

import jinja2
import pytest

from intentfabric.adapters.jinja_renderer import JinjaTemplateRenderer
from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.application.generation import DeterministicGeneratorService
from intentfabric.application.pre_validation import PreValidationService
from intentfabric.bootstrap import (
    build_generator, build_plugin_catalog, create_default_catalog, create_default_generator,
    load_default_topology,
)
from intentfabric.domain.errors import (
    PluginRegistrationError, PreValidationFailedError, TemplateNotFoundError, TemplateRenderError,
    UnsupportedCombinationError,
)
from intentfabric.domain.generation import (
    NodeConfigurationArtifact, ServiceGenerationPlan, compute_plan_sha256, compute_sha256,
    extract_commands, normalize_rendered_config,
)
from intentfabric.domain.intent import AccessHop, DiaIntent, ProviderEdgeHop, TransitHop
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey
from intentfabric.domain.topology import TopologyLink
from intentfabric.domain.validation import ValidationIssue, ValidationReport
from intentfabric.domain.vendor_definition import VendorDefinition
from intentfabric.services.dia.context_builder import build_dia_hop_context
from intentfabric.services.dia.intent_parser import DiaIntentParser
from intentfabric.vendors.cisco import build_cisco_qos_context
from intentfabric.vendors.huawei import build_huawei_qos_context


def _intent(vendor_id: str = "cisco") -> DiaIntent:
    return DiaIntent(
        description="LAB#INTE#0001", vlan_id=3001, vrf_name="LAB-INTERNET",
        wan_network=IPv4Network("10.255.0.0/30"),
        lan_network=IPv4Network("203.0.113.0/29"), bandwidth_mbps=100,
        qos_policy_name="LAB_100MB_PARENT",
        access=AccessHop("LAB-ACCESS", vendor_id, IPv4Address("192.0.2.11"), "GigabitEthernet0/0/1", "GigabitEthernet0/0/24"),
        transits=(TransitHop("LAB-TRANSIT", vendor_id, IPv4Address("192.0.2.12"), "GigabitEthernet1/0/23", "GigabitEthernet1/0/24"),),
        provider_edge=ProviderEdgeHop("LAB-PE", vendor_id, IPv4Address("192.0.2.21"), "GigabitEthernet0/0/1"),
    )


def _key() -> TemplateKey:
    return TemplateKey("DIA", Operation.PROVISION, NodeRole.ACCESS)


def _catalog() -> PluginCatalog:
    catalog = PluginCatalog()
    for vendor_id in ("cisco", "huawei"):
        catalog.register_vendor(VendorDefinition(vendor_id, {_key(): f"{vendor_id}/access.j2"}))
    catalog.register_service(DiaIntentParser(catalog.vendor_ids()))
    return catalog


def _context_catalog() -> PluginCatalog:
    catalog = _catalog()
    catalog.register_context_builder("DIA", build_dia_hop_context)
    catalog.register_vendor_qos_builder("cisco", build_cisco_qos_context)
    catalog.register_vendor_qos_builder("huawei", build_huawei_qos_context)
    return catalog


class _TemplateSource:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, str]] = []

    def read_text(self, vendor_id: str, resource_path: str) -> str:
        """Conserva el recurso solicitado y devuelve la plantilla de laboratorio."""
        self.calls.append((vendor_id, resource_path))
        return self.content


def _artifact() -> NodeConfigurationArtifact:
    return NodeConfigurationArtifact(
        hop_index=0, node_id="192.0.2.11", management_ip=IPv4Address("192.0.2.11"),
        vendor="cisco", role=NodeRole.ACCESS, operation=Operation.PROVISION,
        template_key=_key(), rendered_text="! laboratorio\ninterface client\n shutdown\n",
        commands=("interface client", " shutdown"),
        sha256=compute_sha256("! laboratorio\ninterface client\n shutdown\n"),
    )


@pytest.mark.parametrize(
    ("raw_text", "expected"),
    [("", ""), (" \t\r\n\r", ""),
     ("\r\n interface client \t\r shutdown\t\r\n\r\n", " interface client\n shutdown\n"),
     ("first\n \t\n second", "first\n\n second\n"),
     ("line\n", "line\n")],
)
def test_normalization_preserves_cli_indentation_and_internal_blank_lines(
    raw_text: str, expected: str,
) -> None:
    """Elimina bordes vacios y espacios finales con terminadores LF idempotentes."""
    assert normalize_rendered_config(raw_text) == expected
    assert normalize_rendered_config(expected) == expected


def test_sha256_matches_known_utf8_vector() -> None:
    """Produce el vector SHA-256 conocido sin agregar terminadores ni metadatos."""
    assert compute_sha256("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert compute_sha256("abc\n") != compute_sha256("abc")


@pytest.mark.parametrize(
    ("rendered_text", "expected"),
    [("", ()), ("\n \t\n", ()),
     ("! comentario\n# comentario\n \t! indentado\n\t# indentado\n", ()),
     ("interface client\n shutdown\n\tdescription LAB#DIA!\n",
      ("interface client", " shutdown", "\tdescription LAB#DIA!")),
     ("\n! inicio\ninterface client\n \n  # comentario\n shutdown\n\n",
      ("interface client", " shutdown"))],
)
def test_extract_commands_filters_comments_and_blank_lines_preserving_cli(
    rendered_text: str, expected: tuple[str, ...],
) -> None:
    """Omite comentarios y lineas vacias conservando orden, indentacion y texto CLI."""
    assert extract_commands(rendered_text) == expected


def test_compute_plan_sha256_preserves_artifact_order_and_identity() -> None:
    """Incluye indice, identidad y huella de cada artefacto en el orden recibido."""
    first = _artifact()
    second = replace(first, hop_index=1, node_id="LAB-TRANSIT")
    expected_content = f"0:192.0.2.11:{first.sha256}|1:LAB-TRANSIT:{second.sha256}"
    expected_reverse = f"1:LAB-TRANSIT:{second.sha256}|0:192.0.2.11:{first.sha256}"
    assert compute_plan_sha256((first, second)) == compute_sha256(expected_content)
    assert compute_plan_sha256((second, first)) == compute_sha256(expected_reverse)
    assert compute_plan_sha256((first, second)) != compute_plan_sha256((second, first))
    assert compute_plan_sha256((first,)) != compute_plan_sha256((replace(first, hop_index=1),))
    assert compute_plan_sha256((first,)) != compute_plan_sha256((replace(first, node_id="LAB-ACCESS"),))
    changed_text = "interface uplink\n shutdown\n"
    changed = replace(
        first, rendered_text=changed_text, commands=("interface uplink", " shutdown"),
        sha256=compute_sha256(changed_text),
    )
    assert compute_plan_sha256((first,)) != compute_plan_sha256((changed,))
    assert compute_plan_sha256(()) == compute_sha256("")


def test_renderer_resolves_vendor_resources_and_normalizes_without_escaping() -> None:
    """Respeta vendor, variables literales e indentacion al normalizar el renderizado."""
    source = _TemplateSource("\r\n{% if enabled %}\r\n interface {{ name }}  \r\n{% endif %}\r\n")
    renderer = JinjaTemplateRenderer(_catalog(), source)
    context: Mapping[str, object] = {"enabled": True, "name": "LAB<&>"}
    for vendor_id in ("cisco", "huawei"):
        assert renderer.render(vendor_id, _key(), context) == " interface LAB<&>\n"
    assert source.calls == [("cisco", "cisco/access.j2"), ("huawei", "huawei/access.j2")]
    assert context == {"enabled": True, "name": "LAB<&>"}


@pytest.mark.parametrize("template", ["{{ missing }}", "{% if missing %}yes{% endif %}", "{% if %}"])
def test_renderer_wraps_undefined_variables_and_invalid_syntax(template: str) -> None:
    """Expone clave y causa Jinja2 sin ocultar variables faltantes ni sintaxis invalida."""
    renderer = JinjaTemplateRenderer(_catalog(), _TemplateSource(template))
    with pytest.raises(TemplateRenderError) as error:
        renderer.render("cisco", _key(), {})
    assert error.value.template_key == _key()
    assert error.value.cause
    assert isinstance(error.value.__cause__, jinja2.TemplateError)
    assert error.value.cause in str(error.value)


def test_renderer_preserves_unsupported_combination_error_before_reading() -> None:
    """Rechaza una combinacion no declarada sin leer recursos."""
    source = _TemplateSource("unused")
    with pytest.raises(UnsupportedCombinationError):
        JinjaTemplateRenderer(_catalog(), source).render("unknown", _key(), {})
    assert source.calls == []


def test_renderer_preserves_missing_resource_error() -> None:
    """Conserva TemplateNotFoundError cuando falla el puerto de lectura."""
    class MissingSource:
        """Representa un recurso declarado que no esta disponible."""

        def read_text(self, vendor_id: str, resource_path: str) -> str:
            """Informa la ausencia del recurso solicitado."""
            raise TemplateNotFoundError(resource_path)

    with pytest.raises(TemplateNotFoundError, match="cisco/access.j2"):
        JinjaTemplateRenderer(_catalog(), MissingSource()).render("cisco", _key(), {})


@pytest.mark.parametrize("operation", list(Operation))
def test_service_context_exposes_common_fields_and_role_interfaces(operation: Operation) -> None:
    """Unifica description y asigna interfaces y redes sin depender de vendors."""
    intent = _intent()
    contexts = [build_dia_hop_context(intent, index, operation) for index in range(3)]
    for hop, context in zip(intent.hops, contexts, strict=True):
        assert {name: context[name] for name in (
            "service_type", "operation", "description", "vlan_id", "vendor", "role", "management_ip",
        )} == {
            "service_type": "DIA", "operation": operation.value,
            "description": "LAB#INTE#0001", "vlan_id": 3001, "vendor": "cisco",
            "role": hop.role.value, "management_ip": str(hop.management_ip),
        }
        assert "vlan_name" not in context
        assert "cir_bps" not in context and "cir_kbps" not in context
    assert contexts[0]["client_interface"] == "GigabitEthernet0/0/1"
    assert contexts[0]["uplink_interface"] == "GigabitEthernet0/0/24"
    assert contexts[1]["downstream_interface"] == contexts[1]["ingress_interface"] == "GigabitEthernet1/0/23"
    assert contexts[1]["upstream_interface"] == contexts[1]["egress_interface"] == "GigabitEthernet1/0/24"
    assert {key: value for key, value in contexts[2].items() if key not in contexts[0]} == {
        "pe_interface": "GigabitEthernet0/0/1", "pe_subinterface": "GigabitEthernet0/0/1.3001",
        "vrf_name": "LAB-INTERNET", "qos_policy": "LAB_100MB_PARENT", "bandwidth_mbps": 100,
        "wan_network": "10.255.0.0/30", "wan_netmask": "255.255.255.252", "wan_prefixlen": 30,
        "wan_pe_ip": "10.255.0.1", "wan_ce_ip": "10.255.0.2", "lan_network": "203.0.113.0/29",
        "lan_network_address": "203.0.113.0", "lan_netmask": "255.255.255.248", "lan_prefixlen": 29,
    }


@pytest.mark.parametrize("hop_index", [-1, 3, True, 1.5])
def test_service_context_rejects_indices_outside_the_path(hop_index: int) -> None:
    """Impide seleccionar indices negativos, inexistentes o de otro tipo."""
    with pytest.raises(ValueError, match="hop_index:"):
        build_dia_hop_context(_intent(), hop_index, Operation.PROVISION)


@pytest.mark.parametrize("vendor_id", ["cisco", "huawei"])
def test_catalog_adds_native_qos_units_only_to_provider_edge(vendor_id: str) -> None:
    """Compone QoS en bps para Cisco y kbps para Huawei sin contaminar otros roles."""
    catalog = _context_catalog()
    intent = _intent(vendor_id)
    for index in (0, 1):
        assert "rate_unit" not in catalog.build_hop_context(intent, index, Operation.PROVISION)
    context = catalog.build_hop_context(intent, 2, Operation.PROVISION)
    if vendor_id == "cisco":
        expected = {
            "rate_unit": "bps", "cir_rate": 100_000_000, "pir_rate": 100_000_000,
            "cir_bps": 100_000_000, "pir_bps": 100_000_000,
        }
        assert "cir_kbps" not in context
    else:
        expected = {
            "rate_unit": "kbps", "cir_rate": 100_000, "pir_rate": 100_000,
            "cir_kbps": 100_000, "pir_kbps": 100_000,
        }
        assert "cir_bps" not in context
    assert context == build_dia_hop_context(intent, 2, Operation.PROVISION) | expected


def test_context_without_vendor_builder_stays_service_specific() -> None:
    """Admite un contexto de servicio sin escalado QoS registrado."""
    catalog = _catalog()
    catalog.register_context_builder("DIA", build_dia_hop_context)
    assert catalog.build_hop_context(_intent(), 2, Operation.PROVISION) == (
        build_dia_hop_context(_intent(), 2, Operation.PROVISION)
    )


def test_catalog_rejects_unknown_or_duplicate_context_registrations() -> None:
    """Rechaza registros invalidos y conserva los constructores originales."""
    catalog = _catalog()
    with pytest.raises(PluginRegistrationError, match="vendor no registrado"):
        catalog.register_vendor_qos_builder("unknown", build_cisco_qos_context)
    with pytest.raises(PluginRegistrationError, match="servicio no registrado"):
        catalog.register_context_builder("UNKNOWN", build_dia_hop_context)
    catalog.register_vendor_qos_builder("cisco", build_cisco_qos_context)
    catalog.register_context_builder("DIA", build_dia_hop_context)
    with pytest.raises(PluginRegistrationError, match="duplicado"):
        catalog.register_vendor_qos_builder("cisco", build_huawei_qos_context)
    with pytest.raises(PluginRegistrationError, match="duplicado"):
        catalog.register_context_builder("DIA", lambda *arguments: {})
    assert catalog.build_hop_context(_intent(), 2, Operation.PROVISION)["cir_bps"] == 100_000_000


def test_catalog_reports_missing_builders_and_keeps_instances_isolated() -> None:
    """Informa registros faltantes sin compartir constructores entre catalogos."""
    _context_catalog()
    catalog = _catalog()
    with pytest.raises(PluginRegistrationError, match="registre un constructor QoS"):
        catalog.build_vendor_qos_context("cisco", 100_000, 100_000)
    with pytest.raises(PluginRegistrationError, match="registre un constructor"):
        catalog.build_hop_context(_intent(), 0, Operation.PROVISION)


@pytest.mark.parametrize(
    "overrides",
    [{"hop_index": -1}, {"node_id": " "}, {"rendered_text": ""},
     {"rendered_text": "interface client\r\n"}, {"commands": ("! laboratorio",)},
     {"sha256": "0" * 64}],
)
def test_artifact_rejects_invalid_configuration_or_fingerprint(overrides: dict[str, object]) -> None:
    """Exige identidad, texto normalizado, comandos consistentes y huella correspondiente."""
    with pytest.raises(ValueError):
        replace(_artifact(), **overrides)


def test_generation_models_are_frozen_slotted_and_serialize_as_json() -> None:
    """Conserva artefactos inmutables y serializa valores completos en orden fijo."""
    artifact = _artifact()
    plan = ServiceGenerationPlan(
        "LAB#INTE#0001", "DIA", Operation.PROVISION, "default", (artifact,),
        compute_sha256(f"0:192.0.2.11:{artifact.sha256}"),
    )
    for model, field in ((artifact, "node_id"), (plan, "service_id")):
        assert not hasattr(model, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(model, field, "changed")
    serialized = plan.to_dict()
    assert list(serialized) == [
        "service_id", "service_type", "operation", "variant", "artifacts", "plan_sha256",
    ]
    assert json.loads(json.dumps(serialized)) == {
        "service_id": "LAB#INTE#0001", "service_type": "DIA", "operation": "provision",
        "variant": "default", "plan_sha256": plan.plan_sha256,
        "artifacts": [{
            "hop_index": 0, "node_id": "192.0.2.11", "management_ip": "192.0.2.11",
            "vendor": "cisco", "role": "access", "operation": "provision",
            "template_key": {
                "service_type": "DIA", "operation": "provision", "role": "access", "variant": "default",
            },
            "rendered_text": artifact.rendered_text, "commands": list(artifact.commands),
            "sha256": artifact.sha256,
        }],
    }
    serialized["artifacts"].clear()
    assert plan.artifacts == (artifact,)
    with pytest.raises(ValueError, match="artifacts:"):
        replace(plan, artifacts=())
    with pytest.raises(ValueError, match="plan_sha256:"):
        replace(plan, plan_sha256="0" * 64)


class _RecordingRenderer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, TemplateKey, Mapping[str, object]]] = []

    def render(self, vendor_id: str, key: TemplateKey, context: Mapping[str, object]) -> str:
        """Registra el salto y devuelve texto CLI con comentarios y lineas vacias."""
        self.calls.append((vendor_id, key, dict(context)))
        return "! laboratorio\n # comentario indentado\ninterface client\n\n shutdown\n"


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [({"vlan_id": 0}, "INVALID_VLAN_RANGE"),
     ({"vlan_id": 1002}, "RESERVED_CISCO_VLAN"),
     ({"bandwidth_mbps": 1001}, "BANDWIDTH_EXCEEDS_PORT_CAPACITY"),
     ({"wan_network": IPv4Network("192.0.2.8/30")}, "MANAGEMENT_IP_OVERLAPS_SERVICE_NETWORK")],
)
@pytest.mark.parametrize("operation", tuple(Operation))
def test_generator_aborts_semantic_errors_before_any_rendering(
    overrides: dict[str, object], expected_code: str, operation: Operation,
) -> None:
    """Bloquea la Fase 2 ante reglas semanticas invalidadas en provision y teardown."""
    catalog = build_plugin_catalog()
    renderer = _RecordingRenderer()
    generator = DeterministicGeneratorService(catalog, renderer, PreValidationService(catalog))
    with pytest.raises(PreValidationFailedError) as error:
        generator.generate(replace(_intent(), **overrides), operation=operation)
    assert expected_code in {issue.code for issue in error.value.report.errors}
    assert renderer.calls == []


def test_default_factory_runs_prevalidation_before_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    """La composicion por defecto impide renderizar cuando se repite una IP de gestion."""
    renderer = _RecordingRenderer()
    monkeypatch.setattr(JinjaTemplateRenderer, "render", renderer.render)
    intent = _intent()
    intent = replace(intent, provider_edge=replace(
        intent.provider_edge, management_ip=intent.access.management_ip,
    ))
    with pytest.raises(PreValidationFailedError) as error:
        build_generator().generate(intent)
    assert "DUPLICATE_MANAGEMENT_IP" in {issue.code for issue in error.value.report.errors}
    assert renderer.calls == []


def test_generator_forwards_variant_and_blocks_missing_templates() -> None:
    """Valida la variante solicitada antes de generar el primer artefacto."""
    catalog = build_plugin_catalog()
    renderer = _RecordingRenderer()
    generator = DeterministicGeneratorService(catalog, renderer, PreValidationService(catalog))
    with pytest.raises(PreValidationFailedError) as error:
        generator.generate(_intent(), variant="lab")
    assert all(issue.code == "MISSING_TEMPLATE_KEY" for issue in error.value.report.errors)
    assert len(error.value.report.errors) == 3
    assert all("/lab" in issue.message for issue in error.value.report.errors)
    assert renderer.calls == []


def test_generator_keeps_route_order_filters_comments_and_hashes_full_text() -> None:
    """Conserva el orden de transitos y el texto completo al extraer comandos CLI."""
    intent = _intent()
    second_transit = replace(intent.transits[0], node_id="LAB-TRANSIT-2", management_ip=IPv4Address("192.0.2.13"))
    intent = replace(intent, transits=(second_transit, intent.transits[0]))
    catalog = build_plugin_catalog()
    renderer = _RecordingRenderer()
    plan = DeterministicGeneratorService(catalog, renderer, PreValidationService(catalog)).generate(
        intent, operation="teardown",
    )
    assert plan.operation is Operation.TEARDOWN
    assert tuple(artifact.node_id for artifact in plan.artifacts) == (
        "LAB-ACCESS", "LAB-TRANSIT-2", "LAB-TRANSIT", "LAB-PE",
    )
    for index, artifact in enumerate(plan.artifacts):
        assert artifact.hop_index == index
        assert artifact.commands == ("interface client", " shutdown")
        assert artifact.sha256 == compute_sha256(artifact.rendered_text)
        assert artifact.sha256 != compute_sha256("\n".join(artifact.commands))
        vendor_id, key, context = renderer.calls[index]
        assert vendor_id == intent.hops[index].vendor
        assert key.operation is Operation.TEARDOWN
        assert context["operation"] == "teardown"


@dataclass(frozen=True)
class _IdentifiedAccess(AccessHop):
    hostname: str | None = None


@dataclass(frozen=True)
class _IdentifiedIntent(DiaIntent):
    service_id: str | None = None


@pytest.mark.parametrize(
    ("node_id", "hostname", "expected_id"),
    [("LAB-ACCESS", "LAB-HOST", "LAB-ACCESS"), ("LAB-OTHER", "LAB-HOST", "LAB-OTHER"),
     ("LAB-ACCESS", None, "LAB-ACCESS")],
)
def test_generator_uses_explicit_service_and_node_identity_when_available(
    node_id: str | None, hostname: str | None, expected_id: str,
) -> None:
    """Conserva service_id y la identidad logica requerida de cada salto."""
    base = _intent()
    intent = _IdentifiedIntent(
        **{field.name: getattr(base, field.name) for field in fields(base)},
        service_id="LAB-SERVICE",
    )
    intent = replace(intent, access=_IdentifiedAccess(
        node_id, "cisco", base.access.management_ip, "GigabitEthernet0/0/1", "GigabitEthernet0/0/24", hostname,
    ))
    generator = build_generator(pre_validator=PreValidationService(build_plugin_catalog()))
    plan = generator.generate(intent)
    assert plan.service_id == "LAB-SERVICE"
    assert plan.artifacts[0].node_id == expected_id
    assert generator.generate(base).service_id == base.description


def test_factory_honors_injected_catalog_source_and_prevalidator(monkeypatch: pytest.MonkeyPatch) -> None:
    """Usa los componentes suministrados y propaga operacion y variante al validador."""
    class RecordingPreValidator(PreValidationService):
        """Conserva la solicitud de validacion ademas de ejecutar las reglas reales."""

        def validate_and_require(
            self, intent: DiaIntent, *, operations: Sequence[str] = ("provision", "teardown"),
            variant: str = "default",
        ) -> ValidationReport:
            """Registra la solicitud y exige que la intencion sea valida."""
            calls.append((intent, tuple(operations), variant))
            return super().validate_and_require(intent, operations=operations, variant=variant)

    catalog = build_plugin_catalog()
    calls: list[tuple[DiaIntent, tuple[str, ...], str]] = []
    source = _TemplateSource("{{ operation }} {{ description }}\n")
    def reject_inventory_read() -> None:
        raise AssertionError("La composicion completamente inyectada no requiere leer el inventario")
    monkeypatch.setattr("intentfabric.bootstrap.load_default_topology", reject_inventory_read)
    generator = build_generator(catalog, source, RecordingPreValidator(catalog))
    intent = _intent()
    plan = generator.generate(intent, operation="teardown")
    assert calls == [(intent, ("teardown",), "default")]
    assert len(source.calls) == 3
    assert all(artifact.rendered_text == "teardown LAB#INTE#0001\n" for artifact in plan.artifacts)
    assert create_default_catalog is build_plugin_catalog
    assert create_default_generator is build_generator


@pytest.mark.parametrize("operation", tuple(Operation))
@pytest.mark.parametrize("reverse_links", (False, True))
@pytest.mark.parametrize("customer_port", ("Gi1/0/10", "Gi1/0/2"))
def test_programmatic_client_trunks_block_preflight_and_generation(
    operation: Operation, reverse_links: bool, customer_port: str,
) -> None:
    """Rechaza generar sobre cualquier troncal de cliente antes de Pre-Flight y renderizado."""
    topology = load_default_topology()
    links = (*topology.links, TopologyLink("S3-9306-TEST", "Gi1/0/2", "S3-4505-TEST", "GE0/0/2"))
    if reverse_links:
        links = tuple(TopologyLink(link.target_node_id, link.target_interface, link.source_node_id, link.source_interface)
                      for link in reversed(links))
    topology = replace(topology, links=links)
    catalog = build_plugin_catalog(topology)
    path = Path(__file__).resolve().parents[2] / "examples/intents/dia_valid.json"
    intent = catalog.parse_intent(load_intent_mapping(path))
    intent = replace(intent, access=replace(intent.access, customer_port=customer_port))
    preflight_calls: list[DiaIntent] = []

    class PreFlightRecorder:
        """Registra cualquier invocacion indebida a Pre-Flight."""

        def check_preflight(self, candidate: DiaIntent) -> tuple[ValidationIssue, ...]:
            """Conserva la intencion recibida sin emitir hallazgos adicionales."""
            preflight_calls.append(candidate)
            return ()

    source = _TemplateSource("{{ node_id }}\n")
    validator = PreValidationService(catalog, PreFlightRecorder(), topology=topology)
    generator = build_generator(catalog, source, validator, topology=topology)
    with pytest.raises(PreValidationFailedError) as error:
        generator.generate(intent, operation=operation)
    report = error.value.report
    assert not report.is_valid
    assert not report.preflight_executed
    assert [(issue.code, issue.stage.value, issue.field_path, issue.node_id) for issue in report.errors] == [
        ("TOPOLOGY_CLIENT_INTERFACE_IS_TRUNK", "static_offline", "hops[0].customer_port", intent.access.node_id),
    ]
    assert preflight_calls == []
    assert source.calls == []
