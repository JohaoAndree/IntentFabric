"""Modelos puros e inmutables del dominio, sin efectos externos."""

from intentfabric.domain.derivations import BandwidthRates, derive_bandwidth_rates
from intentfabric.domain.errors import IntentFabricError, PreValidationFailedError, TemplateRenderError
from intentfabric.domain.errors import (
    InvalidInterfaceNameError, TopologyPathResolutionError, TopologyValidationError,
)
from intentfabric.domain.interfaces import (
    abbreviate_interface_name, are_equivalent_interfaces, normalize_interface_name,
    split_subinterface,
)
from intentfabric.domain.generation import (
    NodeConfigurationArtifact, ServiceGenerationPlan, compute_sha256, normalize_rendered_config,
)
from intentfabric.domain.validation import (
    ValidationIssue, ValidationReport, ValidationSeverity, ValidationStage,
)
from intentfabric.domain.topology import OsFamily, TopologyCatalog, TopologyLink, TopologyNode


__all__ = (
    "OsFamily", "TopologyCatalog", "TopologyLink", "TopologyNode",
    "InvalidInterfaceNameError", "TopologyPathResolutionError", "TopologyValidationError",
    "abbreviate_interface_name", "are_equivalent_interfaces", "normalize_interface_name",
    "split_subinterface",
    "BandwidthRates", "derive_bandwidth_rates", "NodeConfigurationArtifact",
    "ServiceGenerationPlan", "compute_sha256", "normalize_rendered_config", "TemplateRenderError",
    "IntentFabricError", "PreValidationFailedError", "ValidationIssue",
    "ValidationReport", "ValidationSeverity", "ValidationStage",
)
