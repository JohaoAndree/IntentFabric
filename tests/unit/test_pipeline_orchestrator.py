"""Verifica orden, cortes, tiempos exactos y persistencia del pipeline."""

from dataclasses import replace
from itertools import count
from pathlib import Path
from typing import Any
from unittest.mock import Mock
import csv
import json

import pytest

from intentfabric.adapters import FileExecutionLogger, SimulatedTransportAdapter
from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.application import ExecutionLoggerPort, NoOpExecutionLogger, PipelineOrchestrator
from intentfabric.application.pre_validation import PreValidationService
from intentfabric.bootstrap import build_deployment_service, build_generator, build_plugin_catalog, load_default_topology
from intentfabric.domain import (
    CSV_HEADERS, DeploymentError, DiaIntent, ExecutionRecord, L2VpnIntent, L3VpnIntent,
    ObservedState, PhaseTimings, PipelineOutcome, PostValidationReport, ServiceOperationalStatus,
    ServiceDeploymentReport, ServiceGenerationPlan, TriageStepName, TriageStepResult,
    ValidationIssue, ValidationReport, ValidationStage, build_expected_state,
)
from intentfabric.domain.errors import PluginRegistrationError
from intentfabric.domain.template_key import Operation


_ROOT = Path(__file__).resolve().parents[2]


def _post_report(
    intent: DiaIntent | L3VpnIntent | L2VpnIntent, status: ServiceOperationalStatus,
) -> PostValidationReport:
    expected = build_expected_state(intent)
    passed = status != ServiceOperationalStatus.FAILED
    observed = ObservedState(passed, expected.expected_lldp_ports, expected.l2_node_ids,
                             expected.l2_node_ids, None, True, passed)
    step = TriageStepResult(TriageStepName.PE_INTERFACE_STATE, passed, expected.pe_node_id,
                            "Estado de laboratorio", ("display interface brief",))
    return PostValidationReport(
        expected.service_id, expected.service_type, "default", status, int(passed), expected,
        observed, (step,), root_cause_step=None if passed else step.step,
        root_cause_node_id=None if passed else expected.pe_node_id,
    )


def _pipeline(
    service: str = "dia", status: ServiceOperationalStatus = ServiceOperationalStatus.OPERATIONAL,
    *, preflight_error: bool = False,
) -> tuple[PipelineOrchestrator, DiaIntent | L3VpnIntent | L2VpnIntent, list[str], Mock]:
    topology = load_default_topology()
    catalog = build_plugin_catalog(topology)
    intent = catalog.parse_intent(load_intent_mapping(_ROOT / f"examples/intents/{service}_valid.json"))
    events: list[str] = []
    checker = None
    if preflight_error:
        checker = Mock()
        checker.check_preflight.return_value = (ValidationIssue(
            "VLAN_COLLISION", "VLAN ocupada en laboratorio", ValidationStage.PREFLIGHT_ONLINE,
            node_id=intent.access.node_id,
        ),)
    pre = PreValidationService(catalog, topology=topology, preflight_checker=checker)
    generator = build_generator(catalog, topology=topology)
    deployment = build_deployment_service(topology, transport=SimulatedTransportAdapter())
    post = Mock()

    def validate(*args: Any, **kwargs: Any) -> ValidationReport:
        events.append("phase1")
        return pre.validate(*args, **kwargs)

    def generate(*args: Any, **kwargs: Any) -> ServiceGenerationPlan:
        events.append("phase2")
        return generator.generate(*args, **kwargs)

    def deploy(*args: Any, **kwargs: Any) -> ServiceDeploymentReport:
        events.append("phase3")
        return deployment.deploy(*args, **kwargs)

    def verify(*args: Any, **kwargs: Any) -> PostValidationReport:
        events.append("phase4")
        return _post_report(intent, status)

    pre_mock = Mock(wraps=pre)
    pre_mock._topology = topology
    pre_mock.validate.side_effect = validate
    generator_mock = Mock(wraps=generator)
    generator_mock.generate.side_effect = generate
    deployment_mock = Mock(wraps=deployment)
    deployment_mock.deploy.side_effect = deploy
    post.validate.side_effect = verify
    logger = Mock(spec=ExecutionLoggerPort)
    ticks = count()
    orchestrator = PipelineOrchestrator(
        catalog, pre_mock, generator_mock, deployment_service=deployment_mock,
        post_validator=post, logger=logger, clock=lambda: next(ticks) / 1000,
    )
    return orchestrator, intent, events, logger


@pytest.mark.parametrize("service", ["dia", "l3vpn", "l2vpn"])
@pytest.mark.parametrize("status", list(ServiceOperationalStatus))
def test_run_orders_four_phases_and_records_exact_evidence(service: str, status: ServiceOperationalStatus) -> None:
    """Ejecuta cuatro fases en orden y registra una sola evidencia con tiempos exactos."""
    orchestrator, intent, events, logger = _pipeline(service, status)
    record = orchestrator.run(intent)
    assert events == ["phase1", "phase2", "phase3", "phase4"]
    logger.record.assert_called_once_with(record)
    assert record.timings == PhaseTimings(1, 1, 1, 1, 9)
    assert record.outcome == (PipelineOutcome.POST_VALIDATION_FAILED if status == ServiceOperationalStatus.FAILED
                              else PipelineOutcome(status.value))
    assert record.sdc == int(status != ServiceOperationalStatus.FAILED)
    assert record.is_successful == bool(record.sdc)
    assert record.plan_sha256 == record.generation_plan.plan_sha256
    assert len(record.deployment_report.results) == len(intent.hops)
    serialized = record.to_dict()
    for field in ("validation_report", "generation_plan", "deployment_report", "post_validation_report"):
        assert serialized[field] == getattr(record, field).to_dict()
    if record.sdc == 0:
        assert record.error_code == "POST_VALIDATION_FAILED"
        assert record.failure_stage == "pe_interface_state"
        assert record.root_cause_node_id == intent.provider_edge.node_id
    else:
        assert record.error_code is record.failure_stage is record.root_cause_node_id is None


@pytest.mark.parametrize("online", [False, True])
def test_run_rejects_phase1_without_generating_or_deploying(online: bool) -> None:
    """Corta ante errores estaticos o de Pre-Flight conservando su taxonomia."""
    orchestrator, intent, events, logger = _pipeline(preflight_error=online)
    if not online:
        intent = replace(intent, vlan_id=0)
    record = orchestrator.run(intent)
    assert events == ["phase1"]
    assert record.outcome == PipelineOutcome.REJECTED_PRE_VALIDATION
    assert not record.is_successful
    assert record.failure_stage == ("preflight_online" if online else "static_offline")
    assert record.error_code == record.validation_report.errors[0].code
    assert record.root_cause_node_id == record.validation_report.errors[0].node_id
    assert record.timings == PhaseTimings(1, 0, 0, 0, 3)
    assert record.generation_plan is record.deployment_report is record.post_validation_report is None
    assert record.sdc is record.plan_sha256 is None
    orchestrator._generator.generate.assert_not_called()
    orchestrator._deployment_service.deploy.assert_not_called()
    orchestrator._post_validator.validate.assert_not_called()
    logger.record.assert_called_once_with(record)


@pytest.mark.parametrize("method", ["deploy", "run"])
def test_deployment_failure_keeps_plan_and_skips_post_validation(method: str) -> None:
    """Conserva plan y nodo del fallo sin ejecutar la cuarta fase."""
    orchestrator, intent, events, logger = _pipeline()

    def fail(plan: object) -> None:
        events.append("phase3")
        raise DeploymentError("Fallo de laboratorio", node_id=intent.transits[0].node_id, hop_index=1)

    orchestrator._deployment_service.deploy.side_effect = fail
    record = getattr(orchestrator, method)(intent)
    assert events == ["phase1", "phase2", "phase3"]
    assert record.outcome == PipelineOutcome.DEPLOYMENT_FAILED
    assert (record.failure_stage, record.error_code, record.root_cause_node_id) == (
        "deployment", "DEPLOYMENT_ERROR", intent.transits[0].node_id,
    )
    assert record.timings == PhaseTimings(1, 1, 1, 0, 7)
    assert record.plan_sha256 == record.generation_plan.plan_sha256
    assert record.deployment_report is record.post_validation_report is record.sdc is None
    orchestrator._post_validator.validate.assert_not_called()
    logger.record.assert_called_once_with(record)


@pytest.mark.parametrize("method,outcome,phases", [
    ("validate", PipelineOutcome.VALIDATED, ["phase1"]),
    ("generate", PipelineOutcome.GENERATED, ["phase2"]),
    ("deploy", PipelineOutcome.DEPLOYED, ["phase1", "phase2", "phase3"]),
    ("verify", PipelineOutcome.OPERATIONAL, ["phase4"]),
    ("teardown", PipelineOutcome.TEARDOWN_COMPLETED, ["phase2", "phase3"]),
])
def test_independent_use_cases_register_once(method: str, outcome: PipelineOutcome, phases: list[str]) -> None:
    """Ejecuta cada caso de uso con las fases y la operacion correspondientes."""
    orchestrator, intent, events, logger = _pipeline()
    record = getattr(orchestrator, method)(intent)
    assert record.outcome == outcome and record.is_successful
    assert events == phases
    assert record.operation == (Operation.TEARDOWN if method == "teardown" else Operation.PROVISION)
    assert record.sdc == (1 if method == "verify" else None)
    if method in ("generate", "teardown"):
        assert record.validation_report.is_valid and not record.validation_report.preflight_executed
        assert record.timings.phase1_validation_ms == 1
    logger.record.assert_called_once_with(record)


@pytest.mark.parametrize("method", ["generate", "teardown"])
def test_offline_paths_bypass_online_rejection(method: str) -> None:
    """Generacion offline y retiro omiten colisiones de recursos ya aprovisionados."""
    orchestrator, intent, events, _ = _pipeline(preflight_error=True)
    record = getattr(orchestrator, method)(intent)
    assert record.is_successful and "phase1" not in events
    orchestrator._pre_validator.validate.assert_not_called()


@pytest.mark.parametrize("method", ["validate", "generate", "deploy", "teardown"])
def test_each_validating_use_case_cuts_on_static_errors(method: str) -> None:
    """Impide generar o desplegar desde cualquier entrada con errores estaticos."""
    orchestrator, intent, _, logger = _pipeline()
    record = getattr(orchestrator, method)(replace(intent, vlan_id=0))
    assert record.outcome == PipelineOutcome.REJECTED_PRE_VALIDATION
    orchestrator._generator.generate.assert_not_called()
    orchestrator._deployment_service.deploy.assert_not_called()
    logger.record.assert_called_once_with(record)


def test_raw_intent_and_teardown_generation_preserve_operation() -> None:
    """Parsea mappings y conserva operacion teardown en el plan y el registro."""
    orchestrator, _, _, _ = _pipeline()
    raw = load_intent_mapping(_ROOT / "examples/intents/dia_valid.json")
    record = orchestrator.generate(raw, operation="teardown")
    assert record.operation == record.generation_plan.operation == Operation.TEARDOWN


@pytest.mark.parametrize("method,missing", [
    ("deploy", "deployment_service"), ("teardown", "deployment_service"),
    ("verify", "post_validator"), ("run", "deployment_service"), ("run", "post_validator"),
])
def test_required_services_fail_before_running_phases(method: str, missing: str) -> None:
    """Exige servicios inyectados antes de validar o modificar equipos."""
    orchestrator, intent, events, logger = _pipeline()
    setattr(orchestrator, f"_{missing}", None)
    with pytest.raises(PluginRegistrationError, match=missing):
        getattr(orchestrator, method)(intent)
    assert events == []
    logger.record.assert_not_called()


@pytest.mark.parametrize("preexisting_empty", [False, True])
def test_logger_writes_exact_json_and_accumulates_csv(tmp_path: Path, preexisting_empty: bool) -> None:
    """Escribe UTF-8 con LF, reemplaza JSON y anexa CSV sin repetir encabezados."""
    json_path = tmp_path / "reports" / "execution.json"
    csv_path = tmp_path / "metrics" / "summary.csv"
    if preexisting_empty:
        csv_path.parent.mkdir()
        csv_path.write_text("", encoding="utf-8", newline="\n")
    logger = FileExecutionLogger(json_path=str(json_path), csv_path=csv_path)
    record = ExecutionRecord("LAB-ñ", "DIA", Operation.PROVISION, "default",
                              PipelineOutcome.VALIDATED, True, PhaseTimings(1))
    logger.record(record)
    last = replace(record, service_id="LAB-211", outcome=PipelineOutcome.GENERATED)
    logger.record(last)
    assert json_path.read_bytes() == (json.dumps(last.to_dict(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    content = csv_path.read_bytes()
    assert b"\r" not in content and "LAB-ñ".encode("utf-8") in content
    assert content.count((",".join(CSV_HEADERS) + "\n").encode()) == 1
    with csv_path.open(encoding="utf-8", newline="\n") as stream:
        rows = list(csv.DictReader(stream))
    assert [row["service_id"] for row in rows] == ["LAB-ñ", "LAB-211"]
    assert rows[0]["sdc"] == rows[0]["plan_sha256"] == ""


@pytest.mark.parametrize("destination", ["json_path", "csv_path"])
def test_logger_supports_single_destination(tmp_path: Path, destination: str) -> None:
    """Exporta solo el formato solicitado sin requerir el otro camino."""
    orchestrator, intent, _, _ = _pipeline()
    record = orchestrator.validate(intent)
    target = tmp_path / "execution"
    FileExecutionLogger(**{destination: target}).record(record)
    assert target.exists()
    assert NoOpExecutionLogger().record(record) is None
    FileExecutionLogger().record(record)
