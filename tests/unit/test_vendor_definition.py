"""Comprueba la identidad del vendor y la inmutabilidad de sus declaraciones."""

from dataclasses import FrozenInstanceError
from types import MappingProxyType
from typing import Any

import pytest

from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey
from intentfabric.domain.vendor_definition import VendorDefinition


def _key() -> TemplateKey:
    return TemplateKey("DIA", Operation.PROVISION, NodeRole.ACCESS)


@pytest.mark.parametrize("vendor_id", ["cisco", "huawei", "acme", "a1", "a_", "a" * 32])
def test_vendor_id_accepts_declared_format(vendor_id: str) -> None:
    """Admite identificadores de vendor de dos a treinta y dos caracteres."""
    assert VendorDefinition(vendor_id, {}).vendor_id == vendor_id


@pytest.mark.parametrize("vendor_id", ["", "a", "A1", "1a", "a-b", "a" * 33, "acme\n", None, 1])
def test_vendor_id_rejects_invalid_format(vendor_id: Any) -> None:
    """Rechaza identificadores fuera del formato del contrato."""
    with pytest.raises(ValueError, match="vendor_id:"):
        VendorDefinition(vendor_id, {})


@pytest.mark.parametrize(
    "resource_path", ["", "/templates/access.j2", "templates\\access.j2", "../access.j2",
                      "templates/../access.j2", "templates/access.txt", None, 1],
)
def test_vendor_rejects_invalid_resource_path(resource_path: Any) -> None:
    """Rechaza rutas vacías, absolutas, ascendentes, inversas o sin extensión .j2."""
    with pytest.raises(ValueError, match="templates:"):
        VendorDefinition("acme", {_key(): resource_path})


def test_vendor_snapshots_mapping_and_prevents_mutation() -> None:
    """Aísla las declaraciones de cambios del mapa original y bloquea su escritura."""
    key = _key()
    templates = {key: "templates/dia/provision/access.j2"}
    definition = VendorDefinition("acme", templates)
    templates.clear()
    assert definition.templates[key] == "templates/dia/provision/access.j2"
    assert isinstance(definition.templates, MappingProxyType)
    with pytest.raises(TypeError):
        definition.templates[key] = "changed.j2"
    with pytest.raises(FrozenInstanceError):
        definition.vendor_id = "other"
