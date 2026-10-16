"""Errores de interpretación de intenciones y de registro de plugins."""


class IntentParseError(Exception):
    """Indica una intención inválida mediante un mensaje con la ruta del campo."""


class PluginRegistrationError(Exception):
    """Indica un registro duplicado de vendor o servicio."""


class UnsupportedCombinationError(Exception):
    """Indica que un vendor no declara la combinación de plantilla solicitada."""


class PluginConsistencyError(Exception):
    """Agrupa los desajustes entre servicios registrados y plantillas declaradas."""


class TemplateNotFoundError(Exception):
    """Indica que una plantilla o la raíz de su vendor no está disponible."""
