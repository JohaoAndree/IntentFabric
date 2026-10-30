"""Conserva evidencia experimental inmutable y serializacion de orden fijo."""

from dataclasses import dataclass, fields
from enum import StrEnum

from intentfabric.domain.deployment import ServiceDeploymentReport
from intentfabric.domain.errors import IntentFabricError
from intentfabric.domain.generation import ServiceGenerationPlan
from intentfabric.domain.post_validation import PostValidationReport
from intentfabric.domain.template_key import Operation
from intentfabric.domain.validation import ValidationReport


class PipelineOutcome(StrEnum):
    """Identifica el resultado alcanzado por una ejecucion del pipeline."""

    VALIDATED = "VALIDATED"
    GENERATED = "GENERATED"
    DEPLOYED = "DEPLOYED"
    OPERATIONAL = "OPERATIONAL"
    READY_FOR_SERVICE = "READY_FOR_SERVICE"
    TEARDOWN_COMPLETED = "TEARDOWN_COMPLETED"
    REJECTED_PRE_VALIDATION = "REJECTED_PRE_VALIDATION"
    DEPLOYMENT_FAILED = "DEPLOYMENT_FAILED"
    POST_VALIDATION_FAILED = "POST_VALIDATION_FAILED"


CSV_HEADERS: tuple[str, ...] = (
    "service_id", "service_type", "operation", "variant", "outcome", "is_successful",
    "sdc", "plan_sha256", "phase1_validation_ms", "phase2_generation_ms",
    "phase3_deployment_ms", "phase4_post_validation_ms", "total_duration_ms",
    "failure_stage", "error_code", "root_cause_node_id",
)


@dataclass(frozen=True, slots=True)
class PhaseTimings:
    """Conserva duraciones no negativas en milisegundos con tres decimales."""

    phase1_validation_ms: float = 0.0
    phase2_generation_ms: float = 0.0
    phase3_deployment_ms: float = 0.0
    phase4_post_validation_ms: float = 0.0
    total_duration_ms: float = 0.0

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not value >= 0:
                raise IntentFabricError(f"{field.name}: se requiere un numero no negativo")
            object.__setattr__(self, field.name, round(float(value), 3))

    def to_dict(self) -> dict[str, float]:
        """Serializa las duraciones en orden de fases seguido del total."""
        return {field.name: getattr(self, field.name) for field in fields(self)}


@dataclass(frozen=True, slots=True)
class ExecutionRecord:
    """Agrupa resultados, tiempos y causa raiz de una ejecucion."""

    service_id: str
    service_type: str
    operation: Operation
    variant: str
    outcome: PipelineOutcome
    is_successful: bool
    timings: PhaseTimings
    sdc: int | None = None
    plan_sha256: str | None = None
    failure_stage: str | None = None
    error_code: str | None = None
    root_cause_node_id: str | None = None
    validation_report: ValidationReport | None = None
    generation_plan: ServiceGenerationPlan | None = None
    deployment_report: ServiceDeploymentReport | None = None
    post_validation_report: PostValidationReport | None = None

    def __post_init__(self) -> None:
        for name in ("service_id", "service_type", "variant"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise IntentFabricError(f"{name}: se requiere texto no vacio")
        for name, expected in (("operation", Operation), ("outcome", PipelineOutcome),
                               ("timings", PhaseTimings)):
            if not isinstance(getattr(self, name), expected):
                raise IntentFabricError(f"{name}: se requiere {expected.__name__}")
        if type(self.is_successful) is not bool:
            raise IntentFabricError("is_successful: se requiere bool")
        if self.sdc is not None and (type(self.sdc) is not int or self.sdc not in (0, 1)):
            raise IntentFabricError("sdc: se requiere None, 0 o 1")

    def to_dict(self) -> dict[str, object]:
        """Serializa el registro completo con claves fijas y reportes anidados."""
        return {
            "service_id": self.service_id,
            "service_type": self.service_type,
            "operation": self.operation.value,
            "variant": self.variant,
            "outcome": self.outcome.value,
            "is_successful": self.is_successful,
            "sdc": self.sdc,
            "plan_sha256": self.plan_sha256,
            "timings": self.timings.to_dict(),
            "failure_stage": self.failure_stage,
            "error_code": self.error_code,
            "root_cause_node_id": self.root_cause_node_id,
            "validation_report": self.validation_report.to_dict() if self.validation_report else None,
            "generation_plan": self.generation_plan.to_dict() if self.generation_plan else None,
            "deployment_report": self.deployment_report.to_dict() if self.deployment_report else None,
            "post_validation_report": self.post_validation_report.to_dict() if self.post_validation_report else None,
        }

    def to_csv_row(self) -> dict[str, object]:
        """Aplana las metricas en el orden CSV sustituyendo ausencias por texto vacio."""
        values = self.to_dict() | self.timings.to_dict()
        return {name: values[name] if values[name] is not None else "" for name in CSV_HEADERS}
