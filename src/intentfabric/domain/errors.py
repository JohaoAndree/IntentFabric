"""Errores de interpretación de intenciones y de registro de plugins."""

from intentfabric.domain.validation import ValidationReport


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


class PreValidationFailedError(IntentFabricError):
    """Expone el reporte completo de una validacion previa rechazada."""

    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        super().__init__(
            f"service_id={report.service_id!r}: validacion previa rechazada; "
            f"codigos de error={[issue.code for issue in report.errors]!r}"
        )
