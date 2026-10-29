"""Errores de dominio (IntentFabricError), interpretacion, plugins y validacion previa (PreValidationFailedError)."""

from intentfabric.domain.validation import ValidationReport
from intentfabric.domain.template_key import TemplateKey


class IntentFabricError(Exception):
    """Agrupa los errores explicitos del framework."""


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
