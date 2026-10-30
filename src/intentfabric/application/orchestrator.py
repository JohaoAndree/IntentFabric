"""Coordina fases secuenciales con corte temprano y evidencia experimental."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
import time
from typing import Any, Protocol, cast

from intentfabric.application.deployment import DeploymentService
from intentfabric.application.generation import DeterministicGeneratorService
from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.application.post_validation import PostValidationTriageService
from intentfabric.application.pre_validation import PreValidationService
from intentfabric.domain.errors import DeploymentError, PluginRegistrationError
from intentfabric.domain.execution import ExecutionRecord, PhaseTimings, PipelineOutcome
from intentfabric.domain.intent import DiaIntent, L2VpnIntent, L3VpnIntent, ServiceIntent
from intentfabric.domain.post_validation import PostValidationReport, ServiceOperationalStatus
from intentfabric.domain.template_key import Operation
from intentfabric.domain.validation import ValidationReport


class ExecutionLoggerPort(Protocol):
    """Define la persistencia de evidencia de una ejecucion completa."""

    def record(self, execution: ExecutionRecord) -> None:
        """Registra una ejecucion una vez concluido el caso de uso."""
        ...


class NoOpExecutionLogger:
    """Omite persistencia cuando no se solicita un registro externo."""

    def record(self, execution: ExecutionRecord) -> None:
        """Acepta el registro sin producir efectos externos."""
        return None


class PipelineOrchestrator:
    """Expone el ciclo de vida con tiempos inyectables y un registro por llamada."""

    def __init__(
        self, catalog: PluginCatalog, pre_validator: PreValidationService,
        generator: DeterministicGeneratorService, *,
        deployment_service: DeploymentService | None = None,
        post_validator: PostValidationTriageService | None = None,
        logger: ExecutionLoggerPort | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._catalog = catalog
        self._pre_validator = pre_validator
        self._static_pre_validator = PreValidationService(catalog, topology=pre_validator._topology)
        self._generator = generator
        self._deployment_service = deployment_service
        self._post_validator = post_validator
        self._logger = logger if logger is not None else NoOpExecutionLogger()
        self._clock = clock

    def _resolve_intent(
        self, intent_or_raw: ServiceIntent | Mapping[str, Any],
    ) -> DiaIntent | L3VpnIntent | L2VpnIntent:
        if isinstance(intent_or_raw, Mapping):
            return self._catalog.parse_intent(intent_or_raw)
        return cast(DiaIntent | L3VpnIntent | L2VpnIntent, intent_or_raw)

    def validate(
        self, intent_or_raw: ServiceIntent | Mapping[str, Any], *,
        operations: Sequence[str] = ("provision", "teardown"), variant: str = "default",
    ) -> ExecutionRecord:
        """Ejecuta validacion previa y conserva el primer error taxonomico."""
        intent = self._resolve_intent(intent_or_raw)
        started = self._clock()
        durations: dict[str, float] = {}
        report = self._measure(
            lambda: self._pre_validator.validate(intent, operations=operations, variant=variant),
            durations, "phase1_validation_ms",
        )
        execution = self._new_record(intent, Operation.PROVISION, variant)
        execution = replace(execution, validation_report=report)
        if not report.is_valid:
            execution = _reject(execution, report)
        return self._finish(execution, started, durations)

    def generate(
        self, intent_or_raw: ServiceIntent | Mapping[str, Any], *,
        operation: Operation | str = Operation.PROVISION, variant: str = "default",
    ) -> ExecutionRecord:
        """Valida estaticamente y genera sin consultar dispositivos."""
        return self._execute_plan(intent_or_raw, Operation(operation), variant, final_phase=2)

    def deploy(
        self, intent_or_raw: ServiceIntent | Mapping[str, Any], *,
        operation: Operation | str = Operation.PROVISION, variant: str = "default",
    ) -> ExecutionRecord:
        """Valida, genera y despliega conservando evidencia ante DeploymentError."""
        self._require_deployment_service()
        return self._execute_plan(intent_or_raw, Operation(operation), variant, final_phase=3)

    def verify(
        self, intent_or_raw: ServiceIntent | Mapping[str, Any], *, variant: str = "default",
    ) -> ExecutionRecord:
        """Audita el estado operativo sin generar ni desplegar el servicio."""
        post_validator = self._require_post_validator()
        intent = self._resolve_intent(intent_or_raw)
        started = self._clock()
        durations: dict[str, float] = {}
        report = self._measure(lambda: post_validator.validate(intent, variant=variant),
                               durations, "phase4_post_validation_ms")
        execution = _with_post_report(self._new_record(intent, Operation.PROVISION, variant), report)
        return self._finish(execution, started, durations)

    def run(
        self, intent_or_raw: ServiceIntent | Mapping[str, Any], *, variant: str = "default",
    ) -> ExecutionRecord:
        """Ejecuta las cuatro fases y corta tras rechazo previo o fallo de despliegue."""
        self._require_deployment_service()
        self._require_post_validator()
        return self._execute_plan(intent_or_raw, Operation.PROVISION, variant, final_phase=4)

    def teardown(
        self, intent_or_raw: ServiceIntent | Mapping[str, Any], *, variant: str = "default",
    ) -> ExecutionRecord:
        """Retira el servicio mediante generacion y despliegue sin Pre-Flight online."""
        return self.deploy(intent_or_raw, operation=Operation.TEARDOWN, variant=variant)

    def _execute_plan(
        self, intent_or_raw: ServiceIntent | Mapping[str, Any], operation: Operation,
        variant: str, *, final_phase: int,
    ) -> ExecutionRecord:
        intent = self._resolve_intent(intent_or_raw)
        started = self._clock()
        durations: dict[str, float] = {}
        execution = self._new_record(intent, operation, variant)
        validator = (self._static_pre_validator if final_phase == 2 or operation == Operation.TEARDOWN
                     else self._pre_validator)
        report = self._measure(
            lambda: validator.validate(intent, operations=(operation.value,), variant=variant),
            durations, "phase1_validation_ms",
        )
        execution = replace(execution, validation_report=report)
        if not report.is_valid:
            return self._finish(_reject(execution, report), started, durations)
        plan = self._measure(
            lambda: self._generator.generate(intent, operation=operation, variant=variant),
            durations, "phase2_generation_ms",
        )
        execution = replace(execution, outcome=PipelineOutcome.GENERATED,
                            plan_sha256=plan.plan_sha256, generation_plan=plan)
        if final_phase == 2:
            return self._finish(execution, started, durations)
        deployment_service = self._require_deployment_service()
        try:
            deployment = self._measure(lambda: deployment_service.deploy(plan),
                                       durations, "phase3_deployment_ms")
        except DeploymentError as error:
            execution = replace(execution, outcome=PipelineOutcome.DEPLOYMENT_FAILED,
                                is_successful=False, failure_stage="deployment",
                                error_code="DEPLOYMENT_ERROR", root_cause_node_id=error.node_id)
            return self._finish(execution, started, durations)
        execution = replace(
            execution, deployment_report=deployment,
            outcome=(PipelineOutcome.TEARDOWN_COMPLETED if operation == Operation.TEARDOWN
                     else PipelineOutcome.DEPLOYED),
        )
        if final_phase == 4:
            post_validator = self._require_post_validator()
            post_report = self._measure(lambda: post_validator.validate(intent, variant=variant),
                                        durations, "phase4_post_validation_ms")
            execution = _with_post_report(execution, post_report)
        return self._finish(execution, started, durations)

    def _new_record(
        self, intent: DiaIntent | L3VpnIntent | L2VpnIntent, operation: Operation, variant: str,
    ) -> ExecutionRecord:
        return ExecutionRecord(
            service_id=getattr(intent, "service_id", None) or intent.description,
            service_type=intent.service_type, operation=operation, variant=variant,
            outcome=PipelineOutcome.VALIDATED, is_successful=True, timings=PhaseTimings(),
        )

    def _measure[T](
        self, action: Callable[[], T], durations: dict[str, float], phase: str,
    ) -> T:
        started = self._clock()
        try:
            return action()
        finally:
            durations[phase] = (self._clock() - started) * 1000

    def _finish(
        self, execution: ExecutionRecord, started: float, durations: dict[str, float],
    ) -> ExecutionRecord:
        timings = PhaseTimings(**durations, total_duration_ms=(self._clock() - started) * 1000)
        execution = replace(execution, timings=timings)
        self._logger.record(execution)
        return execution

    def _require_deployment_service(self) -> DeploymentService:
        if self._deployment_service is None:
            raise PluginRegistrationError("deployment_service: inyecte un DeploymentService para desplegar")
        return self._deployment_service

    def _require_post_validator(self) -> PostValidationTriageService:
        if self._post_validator is None:
            raise PluginRegistrationError("post_validator: inyecte un PostValidationTriageService para verificar")
        return self._post_validator


def _reject(execution: ExecutionRecord, report: ValidationReport) -> ExecutionRecord:
    first_error = report.errors[0]
    return replace(execution, outcome=PipelineOutcome.REJECTED_PRE_VALIDATION,
                   is_successful=False, failure_stage=first_error.stage.value,
                   error_code=first_error.code, root_cause_node_id=first_error.node_id)


def _with_post_report(execution: ExecutionRecord, report: PostValidationReport) -> ExecutionRecord:
    outcome = (PipelineOutcome.POST_VALIDATION_FAILED if report.status == ServiceOperationalStatus.FAILED
               else PipelineOutcome(report.status.value))
    return replace(execution, outcome=outcome, is_successful=report.is_compliant, sdc=report.sdc,
                   failure_stage=report.root_cause_step.value if not report.is_compliant else None,
                   error_code="POST_VALIDATION_FAILED" if not report.is_compliant else None,
                   root_cause_node_id=report.root_cause_node_id, post_validation_report=report)
