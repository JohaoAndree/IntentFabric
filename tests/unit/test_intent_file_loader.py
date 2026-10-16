"""Comprueba la lectura segura de objetos de intención JSON y YAML."""

from pathlib import Path

import pytest

from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.domain.errors import IntentParseError


@pytest.mark.parametrize(
    ("extension", "content"),
    [(".json", '{"description": "laboratorio de validación", "schema_version": "1"}'),
     (".yaml", 'description: laboratorio de validación\nschema_version: "1"\n'),
     (".yml", 'description: laboratorio de validación\nschema_version: "1"\n')],
)
def test_loader_preserves_utf8_mapping(tmp_path: Path, extension: str, content: str) -> None:
    """Carga los mismos valores UTF-8 desde las tres extensiones admitidas."""
    path = tmp_path / f"intent{extension}"
    path.write_text(content, encoding="utf-8", newline="\n")
    expected = {"description": "laboratorio de validación", "schema_version": "1"}
    assert load_intent_mapping(path) == load_intent_mapping(path) == expected


def test_loader_rejects_unsupported_extension(tmp_path: Path) -> None:
    """Rechaza extensiones ajenas a JSON y YAML antes de leer el archivo."""
    with pytest.raises(IntentParseError) as error:
        load_intent_mapping(tmp_path / "intent.txt")
    assert str(error.value).startswith("$: extensión no soportada '.txt'")


@pytest.mark.parametrize(
    ("extension", "content"),
    [(".json", '{"vlan_id":'), (".yaml", "path: ["), (".yml", "qos: ["),
     (".yaml", "!!python/object/apply:builtins.print ['no ejecutar']")],
)
def test_loader_translates_syntax_errors(tmp_path: Path, extension: str, content: str) -> None:
    """Convierte errores de sintaxis y etiquetas YAML inseguras a IntentParseError."""
    path = tmp_path / f"intent{extension}"
    path.write_text(content, encoding="utf-8", newline="\n")
    with pytest.raises(IntentParseError) as error:
        load_intent_mapping(path)
    assert str(error.value).startswith(f"$: sintaxis inválida en {path}:")
    assert error.value.__cause__ is not None


@pytest.mark.parametrize(
    ("extension", "content"),
    [(".json", "[]"), (".json", "null"), (".yaml", ""), (".yml", "- item"),
     (".yaml", "text")],
)
def test_loader_requires_root_object(tmp_path: Path, extension: str, content: str) -> None:
    """Rechaza documentos vacíos, secuencias y escalares como raíz de intención."""
    path = tmp_path / f"intent{extension}"
    path.write_text(content, encoding="utf-8", newline="\n")
    with pytest.raises(IntentParseError) as error:
        load_intent_mapping(path)
    assert str(error.value) == f"$: se requiere un objeto en {path}"
