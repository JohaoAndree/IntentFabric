"""Errores de dominio (IntentFabricError), interpretacion, plugins y validacion previa (PreValidationFailedError)."""

from typing import TYPE_CHECKING

from intentfabric.domain.validation import ValidationReport
from intentfabric.domain.template_key import TemplateKey

if TYPE_CHECKING:
    from intentfabric.domain.deployment import NodeDeploymentResult
    from intentfabric.domain.post_validation import PostValidationReport


class IntentFabricError(Exception):
    """Agrupa los errores explicitos del framework."""


class PostValidationContractError(IntentFabricError):
    """Indica una violacion de las invariantes de validacion posdespliegue."""


class EphemeralProbeCleanupError(IntentFabricError):
    """Identifica una sonda SVI cuya eliminacion no pudo confirmarse."""

    def __init__(self, message: str, *, node_id: str, vlan_id: int) -> None:
        self.node_id = node_id
        self.vlan_id = vlan_id
        super().__init__(message)


class PostValidationFailedError(IntentFabricError):
    """Expone el reporte completo de una validacion posdespliegue rechazada."""

    def __init__(self, report: PostValidationReport) -> None:
        self.report = report
        super().__init__(
            f"service_id={report.service_id!r}: status={report.status.value}; "
            f"root_cause_step={report.root_cause_step}; "
            f"root_cause_node_id={report.root_cause_node_id!r}"
        )


class DeviceTransportError(IntentFabricError):
    """Expone el nodo y comando afectados por un fallo de transporte."""

    def __init__(self, message: str, *, node_id: str, command: str | None = None) -> None:
        self.node_id = node_id
        self.command = command
        super().__init__(message)


class CliCommandRejectedError(DeviceTransportError):
    """Conserva la transcripcion de un comando rechazado por el dispositivo."""

    def __init__(
        self, message: str, *, node_id: str, command: str | None = None, raw_output: str = ""
    ) -> None:
        self.raw_output = raw_output
        super().__init__(message, node_id=node_id, command=command)


class DeploymentError(IntentFabricError):
    """Conserva el salto fallido y los resultados previos al corte del despliegue."""

    def __init__(
        self, message: str, *, node_id: str, hop_index: int,
        partial_results: tuple[NodeDeploymentResult, ...] = (),
    ) -> None:
        self.node_id = node_id
        self.hop_index = hop_index
        self.partial_results = tuple(partial_results)
        super().__init__(message)


class InvalidInterfaceNameError(IntentFabricError):
    """Indica un prefijo, indice o sufijo de interfaz invalido."""


class TopologyValidationError(IntentFabricError):
    """Indica un catalogo topologico mal formado o inconsistente."""


class TopologyPathResolutionError(IntentFabricError):
    """Expone el motivo y nodo de una ruta topologica no resoluble."""

    def __init__(self, message: str, *, code: str, node_id: str | None = None) -> None:
        self.code = code
        self.node_id = node_id
        super().__init__(message)


class IntentParseError(IntentFabricError):
    """Indica una intención inválida mediante un mensaje con la ruta del campo."""


class PluginRegistrationError(IntentFabricError):
    """Indica un registro duplicado de vendor o servicio."""


class UnsupportedCombinationError(IntentFabricError):
    """Indica que un vendor no declara la combinación de plantilla solicitada."""


class PluginConsistencyError(IntentFabricError):
    """Agrupa los desajustes entre servicios registrados y plantillas declaradas."""


class TemplateNotFoundError(IntentFabricError):
    """Indica que una plantilla o la raíz de su vendor no está disponible."""


class TemplateRenderError(IntentFabricError):
    """Expone la plantilla y la causa de un fallo de renderizado estricto."""

    def __init__(self, template_key: TemplateKey, cause: str) -> None:
        self.template_key = template_key
        self.cause = cause
        super().__init__(f"{template_key}: error de renderizado; {cause}")


class PreValidationFailedError(IntentFabricError):
    """Expone el reporte completo de una validacion previa rechazada."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__(
            f"service_id={report.service_id!r}: validacion previa rechazada; "
            f"codigos de error={[issue.code for issue in report.errors]!r}"
        )
