"""Errores de interpretación de intenciones estructuradas."""


class IntentParseError(Exception):
    """Indica una intención inválida mediante un mensaje con la ruta del campo."""
