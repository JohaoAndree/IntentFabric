"""Comprueba la lectura de recursos desde directorios y contenedores empaquetados."""

from pathlib import Path
import zipfile

import pytest

from intentfabric.adapters.packaged_template_source import PackagedTemplateSource
from intentfabric.domain.errors import TemplateNotFoundError


def _write_template(root: Path, resource_path: str, content: str) -> None:
    path = root / resource_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def test_source_reads_nested_utf8_resource(tmp_path: Path) -> None:
    """Conserva el contenido UTF-8 al leer una ruta de varios segmentos."""
    resource_path = "templates/dia/provision/access.j2"
    content = "plantilla de laboratorio con validación\n"
    _write_template(tmp_path, resource_path, content)
    source = PackagedTemplateSource({"acme": tmp_path})
    assert source.read_text("acme", resource_path) == source.read_text("acme", resource_path) == content


def test_source_reads_traversable_inside_archive(tmp_path: Path) -> None:
    """Navega recursos empaquetados sin convertir Traversable en una ruta de disco."""
    archive_path = tmp_path / "resources.zip"
    resource_path = "templates/dia/provision/access.j2"
    content = "recurso empaquetado de laboratorio\n"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(resource_path, content.encode("utf-8"))
    with zipfile.ZipFile(archive_path) as archive:
        source = PackagedTemplateSource({"acme": zipfile.Path(archive)})
        assert source.read_text("acme", resource_path) == content


@pytest.mark.parametrize("resource_path", ["missing.j2", "templates/dia/provision/missing.j2"])
def test_source_rejects_missing_file(tmp_path: Path, resource_path: str) -> None:
    """Traduce un archivo ausente a TemplateNotFoundError con vendor y ruta."""
    source = PackagedTemplateSource({"acme": tmp_path})
    with pytest.raises(TemplateNotFoundError) as error:
        source.read_text("acme", resource_path)
    assert str(error.value) == f"acme: plantilla inexistente {resource_path!r}"


def test_source_rejects_unknown_vendor(tmp_path: Path) -> None:
    """Rechaza la lectura de un vendor sin raíz registrada."""
    with pytest.raises(TemplateNotFoundError) as error:
        PackagedTemplateSource({"acme": tmp_path}).read_text("unknown", "access.j2")
    assert str(error.value) == "unknown: raíz de recursos no registrada"


def test_source_does_not_read_directory_as_template(tmp_path: Path) -> None:
    """Rechaza directorios aunque tengan extensión .j2."""
    (tmp_path / "directory.j2").mkdir()
    with pytest.raises(TemplateNotFoundError):
        PackagedTemplateSource({"acme": tmp_path}).read_text("acme", "directory.j2")


def test_source_snapshots_root_mapping(tmp_path: Path) -> None:
    """Conserva las raíces iniciales cuando cambia el mapa externo."""
    _write_template(tmp_path, "access.j2", "contenido")
    roots = {"acme": tmp_path}
    source = PackagedTemplateSource(roots)
    roots.clear()
    assert source.read_text("acme", "access.j2") == "contenido"
