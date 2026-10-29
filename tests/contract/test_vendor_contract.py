"""Comprueba la correspondencia entre declaraciones de vendor y recursos existentes."""

from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
import re
from types import ModuleType

import pytest

from intentfabric.adapters.packaged_template_source import PackagedTemplateSource
from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.application.template_source import TemplateSource
from intentfabric.bootstrap import VENDOR_PACKAGES, build_plugin_catalog, build_template_source
from intentfabric.domain.errors import TemplateNotFoundError
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey
from intentfabric.domain.vendor_definition import VendorDefinition


def _template_paths(root: Traversable, prefix: str = "templates") -> set[str]:
    paths: set[str] = set()
    for resource in sorted(root.iterdir(), key=lambda item: item.name):
        path = f"{prefix}/{resource.name}"
        if resource.is_dir():
            paths.update(_template_paths(resource, path))
        elif resource.is_file() and resource.name.endswith(".j2"):
            paths.add(path)
    return paths


def _assert_vendor_contract(
    definition: VendorDefinition, catalog: PluginCatalog,
    source: TemplateSource, root: Traversable,
) -> None:
    assert re.fullmatch(r"[a-z][a-z0-9_]{1,31}", definition.vendor_id)
    assert definition.vendor_id in catalog.vendor_ids(), "vendor no registrado"
    for key, resource_path in definition.templates.items():
        suffix = "" if key.variant == "default" else f".{key.variant}"
        expected = f"templates/{key.service_type.lower()}/{key.operation}/{key.role}{suffix}.j2"
        assert resource_path == expected, "ruta fuera de la convención"
        assert catalog.supports(definition.vendor_id, key)
        assert catalog.resolve_template(definition.vendor_id, key) == resource_path
        assert source.read_text(definition.vendor_id, resource_path).strip(), "plantilla vacía"
    template_root = root.joinpath("templates")
    actual = _template_paths(template_root) if template_root.is_dir() else set()
    assert actual == set(definition.templates.values()), "archivos .j2 sin declarar"


def test_catalog_contains_exactly_the_explicit_vendor_packages() -> None:
    """Comprueba que cada paquete explícito está representado en el catálogo."""
    assert build_plugin_catalog().vendor_ids() == frozenset(
        package.VENDOR_DEFINITION.vendor_id for package in VENDOR_PACKAGES
    )


@pytest.mark.parametrize(
    "package", VENDOR_PACKAGES,
    ids=[package.VENDOR_DEFINITION.vendor_id for package in VENDOR_PACKAGES],
)
def test_vendor_declarations_match_packaged_resources(package: ModuleType) -> None:
    """Exige identidad válida, recursos legibles, rutas convencionales y archivos declarados."""
    _assert_vendor_contract(
        package.VENDOR_DEFINITION, build_plugin_catalog(), build_template_source(), files(package),
    )


@pytest.mark.parametrize("variant", ["default", "lab"])
def test_contract_accepts_conventional_declared_resources(tmp_path: Path, variant: str) -> None:
    """Acepta la convención de rutas con y sin sufijo de variante en un vendor sintético."""
    key = TemplateKey("LAB", Operation.TEARDOWN, NodeRole.PROVIDER_EDGE, variant)
    filename = "pe.j2" if variant == "default" else "pe.lab.j2"
    resource_path = f"templates/lab/teardown/{filename}"
    path = tmp_path / resource_path
    path.parent.mkdir(parents=True)
    path.write_text("plantilla sintética\n", encoding="utf-8", newline="\n")
    definition = VendorDefinition("acme", {key: resource_path})
    catalog = PluginCatalog()
    catalog.register_vendor(definition)
    _assert_vendor_contract(definition, catalog, PackagedTemplateSource({"acme": tmp_path}), tmp_path)


@pytest.mark.parametrize("fault", ["path", "undeclared", "missing", "empty", "unregistered"])
def test_contract_detects_synthetic_resource_mismatches(tmp_path: Path, fault: str) -> None:
    """Detecta desajustes de rutas, archivos y registro aunque los vendors reales estén vacíos."""
    key = TemplateKey("DIA", Operation.PROVISION, NodeRole.ACCESS)
    resource_path = "templates/dia/provision/access.j2"
    if fault == "path":
        resource_path = "templates/dia/provision/custom.j2"
    path = tmp_path / resource_path
    path.parent.mkdir(parents=True)
    if fault != "missing":
        path.write_text(" \n" if fault == "empty" else "contenido\n", encoding="utf-8", newline="\n")
    if fault == "undeclared":
        path.with_name("orphan.j2").write_text("sin declaración\n", encoding="utf-8", newline="\n")
    definition = VendorDefinition("acme", {key: resource_path})
    catalog = PluginCatalog()
    if fault != "unregistered":
        catalog.register_vendor(definition)
    source = PackagedTemplateSource({"acme": tmp_path})
    with pytest.raises((AssertionError, TemplateNotFoundError)):
        _assert_vendor_contract(definition, catalog, source, tmp_path)


@pytest.mark.parametrize("package", VENDOR_PACKAGES)
def test_vendors_declare_complete_service_and_variant_matrix(package: ModuleType) -> None:
    """Declara DIA y L3VPN mas las dieciocho combinaciones L2VPN por fabricante."""
    assert set(package.VENDOR_DEFINITION.templates) == {
        TemplateKey(service_type, operation, role)
        for service_type in ("DIA", "L3VPN") for operation in Operation for role in NodeRole
    } | {
        TemplateKey("L2VPN", operation, role, variant)
        for operation in Operation for role in NodeRole
        for variant in ("default", "evpn_vpws", "martini_ldp")
    }
