"""Modelos puros e inmutables del dominio, sin efectos externos."""

from intentfabric.domain.errors import IntentFabricError, PreValidationFailedError
from intentfabric.domain.validation import (
    ValidationIssue, ValidationReport, ValidationSeverity, ValidationStage,
)


__all__ = (
    "IntentFabricError", "PreValidationFailedError", "ValidationIssue",
    "ValidationReport", "ValidationSeverity", "ValidationStage",
)
