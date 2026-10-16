"""Carga archivos JSON y YAML de intención como objetos estructurados."""

import json
from pathlib import Path
from typing import Any

import yaml

from intentfabric.domain.errors import IntentParseError


def load_intent_mapping(path: Path) -> dict[str, Any]:
    """Lee un objeto JSON o YAML UTF-8; rechaza sintaxis, extensión o raíz inválidas."""
    extension = path.suffix.lower()
    if extension not in (".json", ".yaml", ".yml"):
        raise IntentParseError(f"$: extensión no soportada {extension!r} en {path}")
    try:
        with path.open(encoding="utf-8", newline="\n") as stream:
            raw = json.load(stream) if extension == ".json" else yaml.safe_load(stream)
    except (json.JSONDecodeError, yaml.YAMLError) as error:
        raise IntentParseError(f"$: sintaxis inválida en {path}: {error}") from error
    if not isinstance(raw, dict):
        raise IntentParseError(f"$: se requiere un objeto en {path}")
    return raw
