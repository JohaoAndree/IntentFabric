"""Comprueba la composición de vendors, servicios y verificación al construir el catálogo."""

from pathlib import Path

import pytest

from intentfabric import bootstrap
from intentfabric.adapters.packaged_template_source import PackagedTemplateSource
from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.domain.errors import PluginConsistencyError, TemplateNotFoundError
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey
from intentfabric.domain.vendor_definition import VendorDefinition
from intentfabric.services.dia.intent_parser import DiaIntentParser


def test_verified_catalog_accepts_current_vendors_without_templates() -> None:
    """Verifica los vendors reales con DIA registrado y ninguna plantilla declarada aún."""
    catalog = bootstrap.build_verified_catalog()
    assert catalog.vendor_ids() == frozenset({"cisco", "huawei"})
    assert catalog.service_types() == frozenset({"DIA"})
    assert catalog.verify_consistency(bootstrap.build_template_source()) == ()
    key = TemplateKey("DIA", Operation.PROVISION, NodeRole.ACCESS)
    assert not catalog.supports("cisco", key)


def test_template_source_uses_registered_package_roots() -> None:
    """Ubica las raíces reales de Cisco y Huawei a partir de la tupla de paquetes."""
    source = bootstrap.build_template_source()
    for package in bootstrap.VENDOR_PACKAGES:
        vendor_id = package.VENDOR_DEFINITION.vendor_id
        text = source.read_text(vendor_id, "__init__.py")
        assert "VENDOR_DEFINITION" in text
    with pytest.raises(TemplateNotFoundError, match="raíz de recursos no registrada"):
        source.read_text("unknown", "missing.j2")


@pytest.mark.parametrize("content", [None, "", " \n\t", "plantilla de laboratorio\n"])
def test_verified_factory_checks_registered_service_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str | None,
) -> None:
    """Construye el catálogo solo si los recursos del servicio son legibles y no vacíos."""
    resource_path = "templates/dia/provision/access.j2"
    if content is not None:
        path = tmp_path / resource_path
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    catalog = PluginCatalog()
    key = TemplateKey("DIA", Operation.PROVISION, NodeRole.ACCESS)
    catalog.register_vendor(VendorDefinition("acme", {key: resource_path}))
    catalog.register_service(DiaIntentParser(catalog.vendor_ids()))
    source = PackagedTemplateSource({"acme": tmp_path})
    monkeypatch.setattr(bootstrap, "build_plugin_catalog", lambda: catalog)
    monkeypatch.setattr(bootstrap, "build_template_source", lambda: source)
    if content is None or not content.strip():
        with pytest.raises(PluginConsistencyError) as error:
            bootstrap.build_verified_catalog()
        assert "acme/DIA/provision/access/default" in str(error.value)
        expected = "plantilla ilegible" if content is None else "plantilla vacía"
        assert expected in str(error.value)
    else:
        assert bootstrap.build_verified_catalog() is catalog
