"""Garantiza reportes inmutables y acumulativos de validacion previa."""

from dataclasses import FrozenInstanceError
from itertools import permutations
import json

import pytest

from intentfabric.domain import (
    IntentFabricError, PreValidationFailedError, ValidationIssue,
    ValidationReport, ValidationSeverity, ValidationStage,
)
from intentfabric.domain.errors import (
    IntentParseError, PluginConsistencyError, PluginRegistrationError,
    TemplateNotFoundError, UnsupportedCombinationError,
)


def _issue(**overrides: object) -> ValidationIssue:
    fields = {
        "code": "UNSUPPORTED_VENDOR",
        "message": "Registre un vendor soportado para el salto.",
        "stage": ValidationStage.STATIC_OFFLINE,
    }
    return ValidationIssue(**(fields | overrides))


@pytest.mark.parametrize("code", [None, 3, "", " \n\t", "lower_case", "BAD-CODE", " BAD", "1_BAD"])
def test_issue_rejects_invalid_codes(code: object) -> None:
    """Rechaza codigos vacios o ajenos al formato UPPER_SNAKE_CASE."""
    with pytest.raises(ValueError, match="code:"):
        _issue(code=code)


@pytest.mark.parametrize("message", [None, 3, "", " \n\t"])
def test_issue_rejects_empty_or_non_text_messages(message: object) -> None:
    """Exige un mensaje textual no vacio para cada hallazgo."""
    with pytest.raises(ValueError, match="message:"):
        _issue(message=message)


def test_issue_preserves_taxonomy_and_default_severity() -> None:
    """Conserva los campos de entrada y asigna ERROR por defecto."""
    issue = _issue(code="VLAN_802_1Q", field_path="vlan_id", node_id="LAB-PE")
    assert issue.severity is ValidationSeverity.ERROR
    assert issue.sort_key() == ("static_offline", "error", "VLAN_802_1Q", "LAB-PE", "vlan_id")
    assert _issue().sort_key() == ("static_offline", "error", "UNSUPPORTED_VENDOR", "", "")
    assert ValidationStage.PREFLIGHT_ONLINE.value == "preflight_online"
    assert ValidationSeverity.WARNING.value == "warning"


@pytest.mark.parametrize("model", [_issue(), ValidationReport("LAB-001", "DIA", ())])
def test_validation_models_are_frozen_and_slotted(
    model: ValidationIssue | ValidationReport,
) -> None:
    """Impide mutar campos y agregar atributos a los modelos de validacion."""
    field = "code" if isinstance(model, ValidationIssue) else "service_id"
    with pytest.raises(FrozenInstanceError):
        setattr(model, field, "CHANGED")
    assert not hasattr(model, "__dict__")


def test_report_canonically_orders_every_sort_dimension() -> None:
    """Ordena por subfase, severidad, codigo, nodo y campo sin depender de la insercion."""
    expected = (
        _issue(stage=ValidationStage.PREFLIGHT_ONLINE),
        _issue(code="DUPLICATE_NODE_HOP"),
        _issue(node_id="LAB-A", field_path="hops[0]"),
        _issue(node_id="LAB-A", field_path="hops[1]"),
        _issue(node_id="LAB-B"),
        _issue(severity=ValidationSeverity.WARNING),
    )
    serialized = json.dumps(ValidationReport("LAB-001", "DIA", expected).to_dict())
    for issue_order in permutations(expected):
        report = ValidationReport("LAB-001", "DIA", issue_order)
        assert report.issues == expected
        assert json.dumps(report.to_dict()) == serialized


def test_report_filters_errors_and_warnings_in_canonical_order() -> None:
    """Clasifica todos los hallazgos y solo considera invalidantes los errores."""
    error = _issue()
    warning = _issue(code="CHECK_POLICY", severity=ValidationSeverity.WARNING)
    report = ValidationReport("LAB-001", "DIA", (warning, error))
    assert report.errors == (error,)
    assert report.warnings == (warning,)
    assert not report.is_valid
    assert not report.preflight_executed
    assert ValidationReport("LAB-001", "DIA", (warning,)).is_valid
    assert ValidationReport("LAB-001", "DIA", ()).is_valid


def test_report_orders_messages_when_taxonomy_and_location_match() -> None:
    """Resuelve empates de la clave canonica sin depender del orden de llegada."""
    first = _issue(message="Declare la plantilla provision.")
    second = _issue(message="Declare la plantilla teardown.")
    assert first.sort_key() == second.sort_key()
    for issue_order in [(first, second), (second, first)]:
        assert ValidationReport("LAB-001", "DIA", issue_order).issues == (first, second)


@pytest.mark.parametrize("error_type", [
    IntentParseError, PluginConsistencyError, PluginRegistrationError,
    TemplateNotFoundError, UnsupportedCombinationError,
])
def test_existing_errors_inherit_the_framework_base(error_type: type[Exception]) -> None:
    """Conserva compatibilidad con Exception y permite capturar errores del framework."""
    assert issubclass(error_type, IntentFabricError)
    assert issubclass(error_type, Exception)


def test_pre_validation_error_preserves_the_report_and_error_codes() -> None:
    """Expone el reporte original y detalla servicio y errores en el mensaje."""
    warning = _issue(code="CHECK_POLICY", severity=ValidationSeverity.WARNING)
    report = ValidationReport("LAB-001", "DIA", (_issue(), warning))
    error = PreValidationFailedError(report)
    assert isinstance(error, IntentFabricError)
    assert error.report is report
    assert "LAB-001" in str(error)
    assert "['UNSUPPORTED_VENDOR']" in str(error)
    assert "CHECK_POLICY" not in str(error)


def test_report_serializes_explicit_values_and_fixed_field_order() -> None:
    """Expone conteos, subfase ejecutada y campos completos en orden fijo."""
    issue = _issue(field_path="hops[0].vendor", node_id="LAB-A")
    report = ValidationReport("LAB-001", "DIA", (issue,), preflight_executed=True)
    serialized = report.to_dict()
    assert list(serialized) == [
        "service_id", "service_type", "is_valid", "preflight_executed",
        "error_count", "warning_count", "issues",
    ]
    assert serialized == {
        "service_id": "LAB-001", "service_type": "DIA", "is_valid": False,
        "preflight_executed": True, "error_count": 1, "warning_count": 0,
        "issues": [{
            "code": "UNSUPPORTED_VENDOR", "message": issue.message,
            "stage": "static_offline", "severity": "error",
            "field_path": "hops[0].vendor", "node_id": "LAB-A",
        }],
    }
    assert list(serialized["issues"][0]) == [
        "code", "message", "stage", "severity", "field_path", "node_id",
    ]
    serialized["issues"].clear()
    assert report.issues == (issue,)
