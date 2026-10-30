"""Modelos puros e inmutables del dominio, sin efectos externos."""

from intentfabric.domain.execution import CSV_HEADERS, ExecutionRecord, PhaseTimings, PipelineOutcome

from intentfabric.domain.derivations import (
    BandwidthRates, QosRates, WanAddresses, derive_bandwidth_rates, derive_qos_rates,
    derive_subinterface_name, derive_wan_addresses,
)
from intentfabric.domain.deployment import (
    CommandExecutionRecord, DeviceCredentials, NodeDeploymentResult, ServiceDeploymentReport,
    contains_cli_error, find_cli_error_line,
)
from intentfabric.domain.errors import CliCommandRejectedError, DeploymentError, DeviceTransportError
from intentfabric.domain.errors import EphemeralProbeCleanupError, PostValidationContractError, PostValidationFailedError
from intentfabric.domain.post_validation import (
    ExpectedState, ObservedState, PostValidationReport, ServiceOperationalStatus,
    TriageStepName, TriageStepResult, build_expected_state,
    build_ephemeral_svi_provision_commands, build_ephemeral_svi_teardown_commands,
)
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

from intentfabric.domain.intent import (
    AccessHop, DiaIntent, L2VpnIntent, L3VpnIntent, ProviderEdgeHop, ServiceHop, ServiceIntent,
    TransitHop, is_valid_asn, is_valid_evi_id, is_valid_pseudowire_id,
    is_valid_route_distinguisher_or_target,
)

__all__ = (
    "CSV_HEADERS", "ExecutionRecord", "PhaseTimings", "PipelineOutcome",
    "EphemeralProbeCleanupError", "PostValidationContractError", "PostValidationFailedError", "ExpectedState", "ObservedState",
    "PostValidationReport", "ServiceOperationalStatus", "TriageStepName", "TriageStepResult",
    "build_expected_state", "build_ephemeral_svi_provision_commands",
    "build_ephemeral_svi_teardown_commands",
    "CommandExecutionRecord", "DeviceCredentials", "NodeDeploymentResult", "ServiceDeploymentReport",
    "contains_cli_error", "find_cli_error_line", "CliCommandRejectedError", "DeploymentError",
    "DeviceTransportError",
    "AccessHop", "DiaIntent", "L2VpnIntent", "L3VpnIntent", "ProviderEdgeHop", "ServiceHop", "ServiceIntent",
    "is_valid_evi_id", "is_valid_pseudowire_id",
    "TransitHop", "is_valid_asn", "is_valid_route_distinguisher_or_target", "QosRates",
    "WanAddresses", "derive_qos_rates", "derive_subinterface_name", "derive_wan_addresses",
    "OsFamily", "TopologyCatalog", "TopologyLink", "TopologyNode",
    "InvalidInterfaceNameError", "TopologyPathResolutionError", "TopologyValidationError",
    "abbreviate_interface_name", "are_equivalent_interfaces", "normalize_interface_name",
    "split_subinterface",
    "BandwidthRates", "derive_bandwidth_rates", "NodeConfigurationArtifact",
    "ServiceGenerationPlan", "compute_sha256", "normalize_rendered_config", "TemplateRenderError",
    "IntentFabricError", "PreValidationFailedError", "ValidationIssue",
    "ValidationReport", "ValidationSeverity", "ValidationStage",
)
