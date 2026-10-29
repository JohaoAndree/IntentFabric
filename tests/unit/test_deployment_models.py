"""Garantiza validaciones, inmutabilidad y serializacion del despliegue."""

from dataclasses import FrozenInstanceError, replace
from ipaddress import IPv4Address
import json

import pytest

from intentfabric.domain import (
    CliCommandRejectedError, CommandExecutionRecord, DeploymentError, DeviceCredentials,
    DeviceTransportError, IntentFabricError, NodeDeploymentResult, OsFamily,
    ServiceDeploymentReport, contains_cli_error, find_cli_error_line,
)
from intentfabric.domain.template_key import NodeRole, Operation


def _result() -> NodeDeploymentResult:
    return NodeDeploymentResult(
        0, "SW-LAB", IPv4Address("192.0.2.1"), "cisco", OsFamily.CISCO_XE,
        NodeRole.ACCESS, Operation.PROVISION, ("vlan 210",), "ok\n", False, "artifact-hash",
    )


@pytest.mark.parametrize("vendor,marker", [
    ("cisco", "% Invalid input detected"), ("cisco", "% Incomplete command"),
    ("cisco", "% Ambiguous command"), ("cisco", "% Authorization failed"),
    ("cisco", "% Error opening"), ("huawei", "Error: invalid"),
    ("huawei", "eRrOr[1]: invalid"), ("huawei", "Unrecognized command"),
    ("huawei", "Wrong parameter"), ("huawei", "Incomplete command"),
    ("huawei", "Ambiguous command"),
])
def test_cli_rejection_returns_first_matching_line(vendor: str, marker: str) -> None:
    """Detecta cada marcador prescrito y conserva solo el primer rechazo."""
    transcript = f"ok\r\n  {marker}  \r\nError: posterior\n"
    assert find_cli_error_line(transcript, vendor=vendor) == marker
    assert contains_cli_error(transcript)
    other_vendor = "huawei" if vendor == "cisco" else "cisco"
    assert find_cli_error_line(marker, vendor=other_vendor) is None


def test_successful_cli_output_has_no_error() -> None:
    """No confunde mensajes informativos con rechazos CLI."""
    assert not contains_cli_error("Error counters: 0\nInfo: configuration accepted\n")
    assert find_cli_error_line("") is None


@pytest.mark.parametrize("field,value", [
    ("username", " "), ("username", None), ("password", "\t"), ("password", 1),
    ("secret", " "), ("secret", 2), ("port", True), ("port", 0), ("port", 65536),
    ("timeout_seconds", True), ("timeout_seconds", 0), ("timeout_seconds", 601),
])
def test_credentials_reject_invalid_fields(field: str, value: object) -> None:
    """Rechaza credenciales y limites invalidos con el campo identificado."""
    with pytest.raises(ValueError, match=field):
        replace(DeviceCredentials("lab-user", "lab-password"), **{field: value})


def test_credentials_redact_secrets_and_are_immutable() -> None:
    """Oculta secretos de laboratorio y conserva los limites validos."""
    credentials = DeviceCredentials("lab-user", "lab-password", "lab-secret", 65535, 600)
    assert "lab-password" not in repr(credentials)
    assert "lab-secret" not in repr(credentials)
    assert "password='***', secret='***'" in repr(credentials)
    assert "secret=None" in repr(DeviceCredentials("lab-user", "lab-password"))
    with pytest.raises(FrozenInstanceError):
        credentials.port = 22


@pytest.mark.parametrize("field,value", [
    ("node_id", " "), ("os_family", "cisco_xe"), ("mode", "exec"),
    ("commands", []), ("commands", ()), ("raw_output", None), ("committed", 1),
])
def test_execution_record_rejects_invalid_fields(field: str, value: object) -> None:
    """Exige registros de ejecucion con tipos y modos validos."""
    record = CommandExecutionRecord("SW-LAB", OsFamily.CISCO_XE, "show", ("show vrf",), "")
    with pytest.raises(ValueError, match=field):
        replace(record, **{field: value})


@pytest.mark.parametrize("field,value", [
    ("hop_index", True), ("hop_index", -1), ("node_id", " "),
    ("management_ip", "192.0.2.1"), ("vendor", "other"), ("os_family", "cisco_xe"),
    ("role", "access"), ("operation", "provision"), ("commands", []),
    ("commands", ()), ("raw_output", None), ("committed", 1), ("sha256", " "),
])
def test_node_result_rejects_invalid_fields(field: str, value: object) -> None:
    """Impide resultados de salto con campos invalidos."""
    with pytest.raises(ValueError, match=field):
        replace(_result(), **{field: value})


@pytest.mark.parametrize("field,value", [
    ("service_id", " "), ("service_type", " "), ("operation", "provision"),
    ("variant", " "), ("plan_sha256", " "), ("results", []), ("results", ()),
])
def test_report_rejects_invalid_fields(field: str, value: object) -> None:
    """Impide reportes vacios o con metadatos invalidos."""
    report = ServiceDeploymentReport("lab", "DIA", Operation.PROVISION, "default", "plan", (_result(),))
    with pytest.raises(ValueError, match=field):
        replace(report, **{field: value})


def test_report_serialization_is_fixed_and_json_compatible() -> None:
    """Serializa identidades, enums y resultados en orden reproducible."""
    result = _result()
    report = ServiceDeploymentReport("lab", "DIA", Operation.PROVISION, "default", "plan", (result,))
    assert list(result.to_dict()) == [
        "hop_index", "node_id", "management_ip", "vendor", "os_family", "role",
        "operation", "commands", "raw_output", "committed", "sha256",
    ]
    assert result.to_dict()["management_ip"] == "192.0.2.1"
    assert list(report.to_dict()) == [
        "service_id", "service_type", "operation", "variant", "plan_sha256",
        "is_successful", "results",
    ]
    assert json.loads(json.dumps(report.to_dict()))["results"] == [result.to_dict()]
    assert report.is_successful
    with pytest.raises(FrozenInstanceError):
        report.service_id = "other"
    for model in (result, CommandExecutionRecord(
        "SW-LAB", OsFamily.CISCO_XE, "config", ("vlan 210",), ""
    )):
        with pytest.raises(FrozenInstanceError):
            model.node_id = "other"


def test_errors_preserve_transport_context_and_partial_results() -> None:
    """Conserva metadatos y resultados parciales en errores especificos."""
    rejected = CliCommandRejectedError("rejected", node_id="SW-LAB", command="vlan 210", raw_output="raw")
    assert isinstance(rejected, DeviceTransportError)
    assert isinstance(rejected, IntentFabricError)
    assert (rejected.node_id, rejected.command, rejected.raw_output) == ("SW-LAB", "vlan 210", "raw")
    completed = [_result()]
    failure = DeploymentError("failed", node_id="PE-LAB", hop_index=1, partial_results=completed)
    completed.clear()
    assert failure.partial_results == (_result(),)
    assert (failure.node_id, failure.hop_index) == ("PE-LAB", 1)
