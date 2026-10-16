"""Raíz de composición: único módulo que nombra implementaciones concretas."""

from intentfabric.application.intent_parsing import IntentParserRegistry
from intentfabric.services.dia.intent_parser import DiaIntentParser


def build_intent_parser_registry(
    known_vendors: frozenset[str] = frozenset({"cisco", "huawei"}),
) -> IntentParserRegistry:
    """Construye un registro de DIA con los vendors conocidos de la composición."""
    registry = IntentParserRegistry()
    registry.register(DiaIntentParser(known_vendors))
    return registry
