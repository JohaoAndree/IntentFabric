"""Garantiza invariantes y serializacion determinista del registro experimental."""

from dataclasses import FrozenInstanceError, fields, replace
import json

import pytest

from intentfabric.domain import CSV_HEADERS, ExecutionRecord, IntentFabricError, PhaseTimings, PipelineOutcome
from intentfabric.domain.template_key import Operation
from intentfabric.domain.validation import ValidationReport


def _record() -> ExecutionRecord:
    return ExecutionRecord("LAB-210", "DIA", Operation.PROVISION, "default",
                           PipelineOutcome.VALIDATED, True, PhaseTimings())


@pytest.mark.parametrize("name", [field.name for field in fields(PhaseTimings)])
@pytest.mark.parametrize("value", [-1, True, "1", None, float("nan")])
def test_timings_reject_invalid_values(name: str, value: object) -> None:
    """Exige numeros no negativos en cada duracion sin aceptar booleanos."""
    with pytest.raises(IntentFabricError, match=name) as captured:
        PhaseTimings(**{name: value})
    assert type(captured.value) is not IntentFabricError


def test_timings_round_and_preserve_field_order() -> None:
    """Normaliza enteros y redondea duraciones a tres decimales en orden fijo."""
    timings = PhaseTimings(1, 2.12345, 3.98765, 0, 9.11119)
    assert list(timings.to_dict().values()) == [1.0, 2.123, 3.988, 0.0, 9.111]
    assert tuple(timings.to_dict()) == CSV_HEADERS[8:13]
    assert all(type(value) is float for value in timings.to_dict().values())


@pytest.mark.parametrize("name,value", [
    ("service_id", " "), ("service_type", ""), ("variant", ""), ("service_id", None),
    ("operation", "provision"), ("outcome", "VALIDATED"), ("is_successful", 1),
    ("timings", {}), ("sdc", True), ("sdc", 1.0), ("sdc", 2), ("sdc", -1),
])
def test_execution_rejects_invalid_contract_fields(name: str, value: object) -> None:
    """Rechaza identidad vacia, enumerados ausentes y SDC fuera del contrato."""
    with pytest.raises(IntentFabricError, match=name) as captured:
        replace(_record(), **{name: value})
    assert type(captured.value) is not IntentFabricError


@pytest.mark.parametrize("sdc", [None, 0, 1])
def test_execution_serializes_fixed_json_and_csv_order(sdc: int | None) -> None:
    """Conserva claves JSON y CSV fijas y representa ausencias CSV como texto vacio."""
    report = ValidationReport("LAB-210", "DIA", ())
    record = replace(_record(), sdc=sdc, validation_report=report)
    serialized = record.to_dict()
    assert tuple(serialized) == (
        "service_id", "service_type", "operation", "variant", "outcome", "is_successful",
        "sdc", "plan_sha256", "timings", "failure_stage", "error_code", "root_cause_node_id",
        "validation_report", "generation_plan", "deployment_report", "post_validation_report",
    )
    assert serialized["validation_report"] == report.to_dict()
    assert serialized["operation"] == "provision" and serialized["outcome"] == "VALIDATED"
    assert json.loads(json.dumps(serialized)) == serialized
    row = record.to_csv_row()
    assert tuple(row) == CSV_HEADERS
    assert row["sdc"] == ("" if sdc is None else sdc)
    assert row["plan_sha256"] == row["failure_stage"] == row["error_code"] == row["root_cause_node_id"] == ""
    assert row["phase1_validation_ms"] == 0.0


def test_execution_models_are_frozen_and_slotted() -> None:
    """Impide alterar registros y tiempos tras su construccion."""
    for model in (_record(), PhaseTimings()):
        assert not hasattr(model, "__dict__")
        with pytest.raises(FrozenInstanceError):
            setattr(model, fields(model)[0].name, None)


def test_outcomes_match_all_lifecycle_results() -> None:
    """Expone los nueve resultados del ciclo de vida definidos por ADR-012."""
    assert [outcome.value for outcome in PipelineOutcome] == [
        "VALIDATED", "GENERATED", "DEPLOYED", "OPERATIONAL", "READY_FOR_SERVICE",
        "TEARDOWN_COMPLETED", "REJECTED_PRE_VALIDATION", "DEPLOYMENT_FAILED", "POST_VALIDATION_FAILED",
    ]
