"""Garantiza despliegues deterministas y evidencia exacta ante fallos parciales."""

from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from intentfabric.adapters import SimulatedTransportAdapter
from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.application import DeploymentService
from intentfabric.bootstrap import (
    build_deployment_service, build_generator, build_plugin_catalog, load_default_topology,
)
from intentfabric.domain import CliCommandRejectedError, DeploymentError, DeviceTransportError, OsFamily
from intentfabric.domain.generation import ServiceGenerationPlan, compute_plan_sha256
from intentfabric.domain.template_key import Operation


_ROOT = Path(__file__).resolve().parents[2]
_CASES = (("dia", "default"), ("l3vpn", "default"), ("l2vpn", "default"),
          ("l2vpn", "evpn_vpws"), ("l2vpn", "martini_ldp"))


def _plan(service: str, variant: str, pe_vendor: str, operation: Operation) -> ServiceGenerationPlan:
    raw = dict(load_intent_mapping(_ROOT / f"examples/intents/{service}_valid.json"))
    if pe_vendor == "cisco":
        raw.update(access_node_id="S3-4505-TEST", pe_node_id="PE1-TEST", access_interface="GE0/0/1")
        if service == "l2vpn":
            raw["remote_pe_node_id"] = "PE2-TEST"
    intent = build_plugin_catalog().parse_intent(raw)
    return build_generator().generate(intent, operation=operation, variant=variant)


@pytest.mark.parametrize("service,variant", _CASES)
@pytest.mark.parametrize("pe_vendor", ["cisco", "huawei"])
@pytest.mark.parametrize("operation", tuple(Operation))
def test_deployment_preserves_plan_order_commands_hashes_and_report(
    service: str, variant: str, pe_vendor: str, operation: Operation,
) -> None:
    """Aplica provision y teardown de cada servicio en ambas rutas con resultados reproducibles."""
    plan = _plan(service, variant, pe_vendor, operation)
    topology = load_default_topology()
    transport = SimulatedTransportAdapter()
    report = build_deployment_service(topology, transport=transport).deploy(plan)
    repeated = build_deployment_service(transport=SimulatedTransportAdapter()).deploy(plan)
    assert report == repeated
    assert json.dumps(report.to_dict()) == json.dumps(repeated.to_dict())
    assert (report.service_id, report.service_type, report.operation, report.variant, report.plan_sha256) == (
        plan.service_id, plan.service_type, plan.operation, plan.variant, plan.plan_sha256,
    )
    assert report.is_successful
    assert len(report.results) == len(plan.artifacts) == len(transport.history)
    for result, artifact, record in zip(report.results, plan.artifacts, transport.history, strict=True):
        node = topology.get_node(artifact.node_id)
        assert (result.hop_index, result.node_id, result.management_ip, result.vendor, result.role, result.operation) == (
            artifact.hop_index, artifact.node_id, artifact.management_ip, artifact.vendor, artifact.role, artifact.operation,
        )
        assert result.os_family == node.os_family
        assert result.commands == artifact.commands == record.commands
        assert record.node_id == result.node_id
        assert result.sha256 == artifact.sha256
        assert result.raw_output == "\n".join(artifact.commands) + "\n"
        assert result.raw_output == record.raw_output
        assert result.committed is (node.os_family == OsFamily.HUAWEI_VRPV8)
        assert record.mode == "config"


@pytest.mark.parametrize("service,variant", _CASES)
@pytest.mark.parametrize("operation", tuple(Operation))
@pytest.mark.parametrize("failed_index", [0, 1, 2])
@pytest.mark.parametrize("failure_kind", ["transport", "cli"])
def test_deployment_fails_fast_at_each_hop_with_exact_partial_results(
    service: str, variant: str, operation: Operation, failed_index: int, failure_kind: str,
) -> None:
    """Corta inmediatamente ante fallo SSH o rechazo CLI conservando solo saltos completados."""
    plan = _plan(service, variant, "huawei", operation)
    failed = plan.artifacts[failed_index]
    failure = (
        DeviceTransportError("lab offline", node_id=failed.node_id)
        if failure_kind == "transport" else CliCommandRejectedError("rejected", node_id=failed.node_id, raw_output="Error:")
    )
    transport = SimulatedTransportAdapter(failing_nodes={failed.node_id: failure})
    observed = Mock(wraps=transport)
    deployment = DeploymentService(load_default_topology(), observed)
    with pytest.raises(DeploymentError) as caught:
        deployment.deploy(plan)
    error = caught.value
    assert error.__cause__ is failure
    assert (error.node_id, error.hop_index) == (failed.node_id, failed.hop_index)
    assert str(error) == f"{failed.node_id}: fallo de despliegue en salto {failed.hop_index}; {failure}"
    expected_report = build_deployment_service(transport=SimulatedTransportAdapter()).deploy(plan)
    assert error.partial_results == expected_report.results[:failed_index]
    assert [record.node_id for record in transport.history] == [artifact.node_id for artifact in plan.artifacts[:failed_index]]
    assert observed.push_configuration.call_count == failed_index + 1
    assert [call.args[0].node_id for call in observed.push_configuration.call_args_list] == [
        artifact.node_id for artifact in plan.artifacts[:failed_index + 1]
    ]


def test_deployment_keeps_transcript_and_uses_received_artifact_order() -> None:
    """Respeta incluso un orden explicito distinto y conserva las salidas inyectadas."""
    original = _plan("dia", "default", "huawei", Operation.TEARDOWN)
    artifacts = tuple(reversed(original.artifacts))
    plan = replace(original, artifacts=artifacts, plan_sha256=compute_plan_sha256(artifacts))
    outputs = {artifact.node_id: f"transcript {artifact.node_id}\r\n" for artifact in artifacts}
    transport = SimulatedTransportAdapter(config_outputs=outputs)
    report = build_deployment_service(transport=transport).deploy(plan)
    assert [result.node_id for result in report.results] == [artifact.node_id for artifact in artifacts]
    assert [result.raw_output for result in report.results] == [outputs[artifact.node_id].replace("\r\n", "\n") for artifact in artifacts]
