"""Modelos puros e inmutables del dominio, sin efectos externos."""

from intentfabric.domain.derivations import BandwidthRates, derive_bandwidth_rates
from intentfabric.domain.errors import IntentFabricError, PreValidationFailedError, TemplateRenderError
from intentfabric.domain.generation import (
    NodeConfigurationArtifact, ServiceGenerationPlan, compute_sha256, normalize_rendered_config,
)
from intentfabric.domain.validation import (
    ValidationIssue, ValidationReport, ValidationSeverity, ValidationStage,
)


__all__ = (
    "BandwidthRates", "derive_bandwidth_rates", "NodeConfigurationArtifact",
    "ServiceGenerationPlan", "compute_sha256", "normalize_rendered_config", "TemplateRenderError",
    "IntentFabricError", "PreValidationFailedError", "ValidationIssue",
    "ValidationReport", "ValidationSeverity", "ValidationStage",
)
