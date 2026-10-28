"""Modelos puros e inmutables del dominio, sin efectos externos."""

from intentfabric.domain.validation import (
    ValidationIssue, ValidationReport, ValidationSeverity, ValidationStage,
)


__all__ = ("ValidationIssue", "ValidationReport", "ValidationSeverity", "ValidationStage")
