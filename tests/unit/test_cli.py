"""Verifica la CLI y su composicion completa sin hardware ni credenciales."""

from dataclasses import replace
from io import StringIO
from itertools import count
from pathlib import Path
from unittest.mock import Mock
import json
import tomllib

import pytest

from intentfabric import bootstrap
from intentfabric.application import NoOpExecutionLogger
from intentfabric.cli import build_argument_parser, main
from intentfabric.domain import PhaseTimings, PipelineOutcome, TopologyCatalog, TopologyNode
from intentfabric.domain.errors import DeviceTransportError


_ROOT = Path(__file__).resolve().parents[2]


def _arguments(command: str, service: str = "dia", suffix: str = "yaml") -> list[str]:
    return [command, "-i", str(_ROOT / f"examples/intents/{service}_valid.{suffix}"),
            "-t", str(_ROOT / "inventory/topology.yaml")]


@pytest.mark.parametrize("service", ["dia", "l3vpn", "l2vpn"])
@pytest.mark.parametrize("suffix", ["json", "yaml"])
@pytest.mark.parametrize("command,outcome", [
    ("validate", "VALIDATED"), ("generate", "GENERATED"), ("deploy", "DEPLOYED"),
    ("verify", "OPERATIONAL"), ("run", "OPERATIONAL"), ("teardown", "TEARDOWN_COMPLETED"),
])
def test_cli_executes_all_official_examples(service: str, suffix: str, command: str, outcome: str) -> None:
    """Completa los seis casos con ejemplos JSON/YAML y transportes predeterminados."""
    output, errors = StringIO(), StringIO()
    assert main(_arguments(command, service, suffix), stdout=output, stderr=errors) == 0
    record = json.loads(output.getvalue())
    assert record["outcome"] == outcome and record["is_successful"]
    assert record["service_type"] == service.upper()
    assert record["sdc"] == (1 if command in ("verify", "run") else None)
    assert errors.getvalue() == ""
    if command in ("deploy", "run"):
        assert record["validation_report"]["preflight_executed"]
    elif command in ("validate", "generate", "teardown"):
        assert not record["validation_report"]["preflight_executed"]


@pytest.mark.parametrize("service", ["dia", "l3vpn", "l2vpn"])
def test_cli_online_validate_has_clean_preflight(service: str) -> None:
    """Permite validacion online simulada con recursos libres para los tres servicios."""
    output, errors = StringIO(), StringIO()
    assert main(_arguments("validate", service) + ["--transport", "simulated"],
                stdout=output, stderr=errors) == 0
    assert json.loads(output.getvalue())["validation_report"]["preflight_executed"]
    assert not errors.getvalue()


@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
@pytest.mark.parametrize("variant", ["default", "evpn_vpws", "martini_ldp"])
@pytest.mark.parametrize("command", ["run", "verify", "teardown"])
def test_l2vpn_variants_support_both_vendors_and_parameterized_ids(
    tmp_path: Path, vendor: str, variant: str, command: str,
) -> None:
    """Conserva conformidad con circuitos e interfaces parametrizados en ambos PE."""
    raw = bootstrap.load_intent_file(_ROOT / "examples/intents/l2vpn_valid.json")
    raw.update(vlan_id=777, pw_id=778, evi_id=779, local_ac_id=780, remote_ac_id=781)
    if vendor == "cisco":
        raw.update(access_node_id="S3-4505-TEST", access_interface="GE0/0/1",
                   pe_node_id="PE1-TEST", remote_pe_node_id="PE2-TEST")
    path = tmp_path / "intent.json"
    path.write_text(json.dumps(raw), encoding="utf-8", newline="\n")
    output, errors = StringIO(), StringIO()
    assert main([command, "-i", str(path), "-t", str(_ROOT / "inventory/topology.yaml"),
                 "-v", variant], stdout=output, stderr=errors) == 0
    record = json.loads(output.getvalue())
    assert record["variant"] == variant
    if command != "teardown":
        assert record["sdc"] == 1
        assert record["post_validation_report"]["expected_state"]["evi_id"] == 779
    assert not errors.getvalue()


@pytest.mark.parametrize("service", ["dia", "l3vpn"])
@pytest.mark.parametrize("vendor", ["cisco", "huawei"])
def test_bootstrap_uses_custom_inventory_and_networks(service: str, vendor: str) -> None:
    """Parametriza identidad, ASN, VRF y redes sin acoplar respuestas al inventario base."""
    original = bootstrap.load_default_topology()
    topology = TopologyCatalog(
        tuple(replace(node, node_id=f"LAB-{node.node_id}", hostname=f"LAB-{node.hostname}",
                      asn=64512 if node.asn is not None else None) for node in original.nodes),
        tuple(replace(link, source_node_id=f"LAB-{link.source_node_id}",
                      target_node_id=f"LAB-{link.target_node_id}") for link in original.links),
    )
    raw = bootstrap.load_intent_file(_ROOT / f"examples/intents/{service}_valid.json")
    raw.update(vlan_id=777, vrf_name="LAB-CUSTOM")
    if service == "dia":
        raw.update(wan_subnet="198.51.100.0/30", lan_subnet="203.0.113.0/24")
    else:
        raw.update(wan_network="198.51.100.0/30", ce_asn=64513)
    raw.update(access_node_id="LAB-S3-9306-TEST", pe_node_id="LAB-PE2-TEST")
    if vendor == "cisco":
        raw.update(access_node_id="LAB-S3-4505-TEST", pe_node_id="LAB-PE1-TEST", access_interface="GE0/0/1")
    catalog = bootstrap.build_plugin_catalog(topology)
    intent = catalog.parse_intent(raw)
    transport = bootstrap.build_simulated_transport_for_intent(intent, topology=topology)
    ticks = count()
    orchestrator = bootstrap.build_orchestrator(topology=topology, catalog=catalog,
                                               transport=transport, clock=lambda: next(ticks) / 1000)
    record = orchestrator.run(intent)
    assert record.outcome == PipelineOutcome.OPERATIONAL and record.sdc == 1
    assert record.timings == PhaseTimings(1, 1, 1, 1, 9)
    assert all(result.node_id.startswith("LAB-") for result in record.deployment_report.results)
    assert record.post_validation_report.expected_state.ping_target_ip == "198.51.100.1"
    assert record.post_validation_report.observed_state.svi_cleaned_up


def test_cli_exports_json_and_accumulative_csv(tmp_path: Path) -> None:
    """Exporta el mismo registro impreso y acumula una fila por invocacion."""
    json_path, csv_path = tmp_path / "out/execution.json", tmp_path / "out/summary.csv"
    arguments = _arguments("run") + ["--json-out", str(json_path), "--csv-out", str(csv_path)]
    for _ in range(2):
        output, errors = StringIO(), StringIO()
        assert main(arguments, stdout=output, stderr=errors) == 0
        assert json.loads(json_path.read_text(encoding="utf-8")) == json.loads(output.getvalue())
        assert not errors.getvalue()
    assert len(csv_path.read_text(encoding="utf-8").splitlines()) == 3
    assert b"\r" not in json_path.read_bytes() and b"\r" not in csv_path.read_bytes()


@pytest.mark.parametrize("command", ["validate", "generate", "deploy", "run", "teardown"])
def test_cli_returns_one_for_semantic_rejection(tmp_path: Path, command: str) -> None:
    """Devuelve uno y un registro estructurado cuando la validacion rechaza capacidad."""
    raw = bootstrap.load_intent_file(_ROOT / "examples/intents/dia_valid.json")
    raw["bandwidth_mbps"] = 1001
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(raw), encoding="utf-8", newline="\n")
    output, errors = StringIO(), StringIO()
    assert main([command, "-i", str(path)], stdout=output, stderr=errors) == 1
    record = json.loads(output.getvalue())
    assert record["outcome"] == "REJECTED_PRE_VALIDATION"
    assert record["error_code"] == "BANDWIDTH_EXCEEDS_PORT_CAPACITY"
    assert record["generation_plan"] is record["deployment_report"] is None
    assert not errors.getvalue()


def test_cli_preflight_collision_prevents_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """No envia configuracion ni genera un plan cuando Pre-Flight detecta una colision."""
    catalog = bootstrap.build_plugin_catalog()
    intent = catalog.parse_intent(bootstrap.load_intent_file(_ROOT / "examples/intents/dia_valid.json"))
    transport = bootstrap.build_simulated_transport_for_intent(intent)
    fixture = (_ROOT / "tests/fixtures/preflight/cisco_show_vlan_brief_clean.txt").read_text(encoding="utf-8")
    transport.set_show_output(intent.access.node_id, "show vlan brief", fixture.replace("1    default", "10   default"))
    monkeypatch.setattr(bootstrap, "build_simulated_transport_for_intent", lambda *args, **kwargs: transport)
    output, errors = StringIO(), StringIO()
    assert main(_arguments("run"), stdout=output, stderr=errors) == 1
    record = json.loads(output.getvalue())
    assert record["failure_stage"] == "preflight_online" and record["error_code"] == "VLAN_COLLISION"
    assert record["generation_plan"] is record["post_validation_report"] is None
    assert transport.history and all(item.mode == "show" for item in transport.history)


def test_cli_deployment_failure_retains_generated_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Devuelve uno con evidencia del plan al fallar el transporte de configuracion."""
    catalog = bootstrap.build_plugin_catalog()
    intent = catalog.parse_intent(bootstrap.load_intent_file(_ROOT / "examples/intents/dia_valid.json"))
    transport = bootstrap.build_simulated_transport_for_intent(intent)
    transport.push_configuration = Mock(side_effect=DeviceTransportError("Fallo simulado", node_id=intent.access.node_id))
    monkeypatch.setattr(bootstrap, "build_simulated_transport_for_intent", lambda *args, **kwargs: transport)
    output, errors = StringIO(), StringIO()
    assert main(_arguments("run"), stdout=output, stderr=errors) == 1
    record = json.loads(output.getvalue())
    assert record["outcome"] == "DEPLOYMENT_FAILED" and record["plan_sha256"]
    assert record["root_cause_node_id"] == intent.access.node_id
    assert record["post_validation_report"] is None


@pytest.mark.parametrize("command", ["verify", "run"])
def test_cli_post_validation_failure_returns_one(monkeypatch: pytest.MonkeyPatch, command: str) -> None:
    """Devuelve SDC cero y la causa raiz ante evidencia operativa ausente."""
    catalog = bootstrap.build_plugin_catalog()
    intent = catalog.parse_intent(bootstrap.load_intent_file(_ROOT / "examples/intents/dia_valid.json"))
    transport = bootstrap.build_simulated_transport_for_intent(intent)
    execute_show = transport.execute_show

    def missing_interface(node: TopologyNode, query: str) -> str:
        output = execute_show(node, query)
        return "" if node.node_id == intent.provider_edge.node_id and query == "display interface brief" else output

    transport.execute_show = missing_interface
    monkeypatch.setattr(bootstrap, "build_simulated_transport_for_intent", lambda *args, **kwargs: transport)
    output, errors = StringIO(), StringIO()
    assert main(_arguments(command), stdout=output, stderr=errors) == 1
    record = json.loads(output.getvalue())
    assert record["outcome"] == "POST_VALIDATION_FAILED" and record["sdc"] == 0
    assert record["failure_stage"] == "pe_interface_state"


@pytest.mark.parametrize("arguments", [[], ["unknown"], ["run"], ["run", "-i", "x", "--transport", "invalid"]])
def test_cli_argument_errors_return_two_on_injected_stderr(arguments: list[str]) -> None:
    """Retorna dos con ayuda de argparse en el canal de errores indicado."""
    output, errors = StringIO(), StringIO()
    assert main(arguments, stdout=output, stderr=errors) == 2
    assert not output.getvalue() and "usage:" in errors.getvalue()


def test_cli_help_returns_zero_on_injected_stdout() -> None:
    """Entrega la ayuda en stdout y termina correctamente sin cargar archivos."""
    output, errors = StringIO(), StringIO()
    assert main(["--help"], stdout=output, stderr=errors) == 0
    assert "teardown" in output.getvalue() and not errors.getvalue()


@pytest.mark.parametrize("failure", ["missing_intent", "missing_topology", "syntax", "credentials", "output_path"])
def test_cli_file_and_credential_errors_return_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    """Devuelve dos sin JSON de exito ante errores de archivos o credenciales."""
    arguments = _arguments("run")
    if failure == "missing_intent":
        arguments[2] = str(tmp_path / "missing.json")
    elif failure == "missing_topology":
        arguments[4] = str(tmp_path / "missing.yaml")
    elif failure == "syntax":
        malformed = tmp_path / "malformed.json"
        malformed.write_text("{", encoding="utf-8", newline="\n")
        arguments[2] = str(malformed)
    elif failure == "credentials":
        monkeypatch.delenv("INTENTFABRIC_SSH_USERNAME", raising=False)
        monkeypatch.delenv("INTENTFABRIC_SSH_PASSWORD", raising=False)
        arguments += ["--transport", "ssh"]
    else:
        arguments += ["--json-out", str(tmp_path)]
    output, errors = StringIO(), StringIO()
    assert main(arguments, stdout=output, stderr=errors) == 2
    assert errors.getvalue() and not output.getvalue()


@pytest.mark.parametrize("command", ["deploy", "verify", "run", "teardown"])
def test_cli_none_transport_requires_online_services(command: str) -> None:
    """Informa servicios ausentes cuando se solicita una operacion online sin transporte."""
    output, errors = StringIO(), StringIO()
    assert main(_arguments(command) + ["--transport", "none"], stdout=output, stderr=errors) == 2
    assert "inyecte" in errors.getvalue() and not output.getvalue()


def test_cli_resolves_ssh_through_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delega la seleccion SSH a la raiz de composicion sin abrir conexiones en pruebas."""
    catalog = bootstrap.build_plugin_catalog()
    intent = catalog.parse_intent(bootstrap.load_intent_file(_ROOT / "examples/intents/dia_valid.json"))
    factory = Mock(return_value=bootstrap.build_simulated_transport_for_intent(intent))
    monkeypatch.setattr(bootstrap, "build_ssh_transport", factory)
    assert main(_arguments("run") + ["--transport", "ssh"], stdout=StringIO(), stderr=StringIO()) == 0
    factory.assert_called_once_with()


def test_generate_teardown_is_offline_and_preserves_operation() -> None:
    """Genera el plan de retiro sin desplegarlo aun si se solicita transporte simulado."""
    output = StringIO()
    assert main(_arguments("generate") + ["--operation", "teardown", "--transport", "simulated"],
                stdout=output, stderr=StringIO()) == 0
    record = json.loads(output.getvalue())
    assert record["operation"] == record["generation_plan"]["operation"] == "teardown"
    assert not record["validation_report"]["preflight_executed"]
    assert record["deployment_report"] is record["post_validation_report"] is None


def test_bootstrap_disables_preflight_without_disabling_deployment() -> None:
    """Permite omitir Pre-Flight manteniendo disponibles despliegue y triage."""
    catalog = bootstrap.build_plugin_catalog()
    intent = catalog.parse_intent(bootstrap.load_intent_file(_ROOT / "examples/intents/dia_valid.json"))
    transport = bootstrap.build_simulated_transport_for_intent(intent)
    record = bootstrap.build_orchestrator(transport=transport, enable_online_preflight=False).run(intent)
    assert record.is_successful and not record.validation_report.preflight_executed
    assert record.deployment_report and record.post_validation_report
    assert isinstance(bootstrap.build_execution_logger(), NoOpExecutionLogger)


def test_entrypoint_and_parser_defaults_match_specification() -> None:
    """Registra el entrypoint y conserva los valores predeterminados declarados."""
    project = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["scripts"]["intentfabric"] == "intentfabric.cli:main"
    for command in ("validate", "generate", "deploy", "verify", "run", "teardown"):
        arguments = build_argument_parser().parse_args([command, "-i", "lab.json"])
        assert arguments.topology == "inventory/topology.yaml" and arguments.variant == "default"
        assert arguments.transport == ("none" if command in ("validate", "generate") else "simulated")
