"""Verifica el registro, despacho y consistencia de las combinaciones de plantilla."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from intentfabric.adapters.packaged_template_source import PackagedTemplateSource
from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.domain.errors import (
    IntentParseError, PluginConsistencyError, PluginRegistrationError,
    TemplateNotFoundError, UnsupportedCombinationError,
)
from intentfabric.domain.intent import ServiceIntent
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey
from intentfabric.domain.vendor_definition import VendorDefinition


class _Parser:
    """Simula un servicio registrado para verificar el despacho del catálogo."""

    def __init__(self, service_type: str = "DIA") -> None:
        self.service_type = service_type

    def parse(self, raw: Mapping[str, Any]) -> ServiceIntent:
        """Conserva la descripción recibida para identificar el resultado del despacho."""
        return ServiceIntent(raw["description"])


class _Source:
    """Simula contenido y errores de lectura sin acceder a archivos."""

    def __init__(self, content: Mapping[str, str | Exception]) -> None:
        self._content = content

    def read_text(self, vendor_id: str, resource_path: str) -> str:
        """Devuelve contenido o reproduce el error asociado al recurso solicitado."""
        value = self._content[resource_path]
        if isinstance(value, Exception):
            raise value
        return value


def _key(service_type: str = "DIA", role: NodeRole = NodeRole.ACCESS) -> TemplateKey:
    return TemplateKey(service_type, Operation.PROVISION, role)


def test_catalog_registers_and_resolves_declared_combination() -> None:
    """Resuelve solo las combinaciones declaradas y delega el parsing de servicios."""
    catalog = PluginCatalog()
    key = _key()
    catalog.register_vendor(VendorDefinition("acme", {key: "access.j2"}))
    catalog.register_service(_Parser())
    assert catalog.vendor_ids() == frozenset({"acme"})
    assert catalog.service_types() == frozenset({"DIA"})
    assert catalog.supports("acme", key)
    assert catalog.resolve_template("acme", key) == "access.j2"
    assert catalog.parse_intent({"service_type": "DIA", "description": "LAB"}) == ServiceIntent("LAB")
    assert catalog.verify_consistency(_Source({"access.j2": "plantilla de laboratorio"})) == ()
    assert catalog.assert_consistent(_Source({"access.j2": "contenido"})) is None


@pytest.mark.parametrize("registration", ["vendor", "service"])
def test_duplicate_registration_preserves_original_entry(registration: str) -> None:
    """Rechaza un registro duplicado sin reemplazar la capacidad original."""
    catalog = PluginCatalog()
    if registration == "vendor":
        catalog.register_vendor(VendorDefinition("acme", {_key(): "original.j2"}))
        with pytest.raises(PluginRegistrationError, match="vendor_id: registro duplicado 'acme'"):
            catalog.register_vendor(VendorDefinition("acme", {}))
        assert catalog.resolve_template("acme", _key()) == "original.j2"
    else:
        catalog.register_service(_Parser())
        with pytest.raises(PluginRegistrationError, match="service_type: registro duplicado 'DIA'"):
            catalog.register_service(_Parser())
        assert catalog.parse_intent({"service_type": "DIA", "description": "LAB"}) == ServiceIntent("LAB")


@pytest.mark.parametrize("vendor_id", ["acme", "unknown"])
def test_missing_combination_is_never_silently_omitted(vendor_id: str) -> None:
    """Devuelve falso al consultar y falla explícitamente al resolver una clave ausente."""
    catalog = PluginCatalog()
    catalog.register_vendor(VendorDefinition("acme", {}))
    assert not catalog.supports(vendor_id, _key())
    with pytest.raises(UnsupportedCombinationError) as error:
        catalog.resolve_template(vendor_id, _key())
    assert str(error.value) == f"{vendor_id}/DIA/provision/access/default: combinación no soportada"


def test_unknown_service_delegates_registry_diagnostic() -> None:
    """Conserva el error del registro al interpretar un servicio desconocido."""
    catalog = PluginCatalog()
    catalog.register_service(_Parser())
    with pytest.raises(IntentParseError) as error:
        catalog.parse_intent({"service_type": "OTHER"})
    assert str(error.value) == "service_type: servicio desconocido 'OTHER'; registrados: DIA"


@pytest.mark.parametrize("content", ["", " \n\t "])
def test_consistency_reports_empty_template(content: str) -> None:
    """Detecta una plantilla vacía incluso cuando contiene solo espacios en blanco."""
    catalog = PluginCatalog()
    catalog.register_vendor(VendorDefinition("acme", {_key(): "access.j2"}))
    catalog.register_service(_Parser())
    source = _Source({"access.j2": content})
    expected = "acme/DIA/provision/access/default: plantilla vacía 'access.j2'"
    assert catalog.verify_consistency(source) == (expected,)
    with pytest.raises(PluginConsistencyError) as error:
        catalog.assert_consistent(source)
    assert str(error.value) == expected


@pytest.mark.parametrize("failure", [TemplateNotFoundError(), PermissionError(), UnicodeError()])
def test_consistency_reports_unreadable_template(failure: Exception) -> None:
    """Convierte ausencia, fallo de acceso y fallo de codificación en inconsistencia."""
    catalog = PluginCatalog()
    catalog.register_vendor(VendorDefinition("acme", {_key(): "access.j2"}))
    catalog.register_service(_Parser())
    assert catalog.verify_consistency(_Source({"access.j2": failure})) == (
        "acme/DIA/provision/access/default: plantilla ilegible 'access.j2'",
    )


def test_consistency_collects_all_errors_in_stable_order() -> None:
    """Agrupa todos los errores con el mismo orden ante registros equivalentes."""
    definitions = [
        VendorDefinition("zeta", {_key(): "empty.j2"}),
        VendorDefinition("acme", {_key("LAB"): "missing.j2", _key(): "valid.j2"}),
    ]
    source = _Source({"empty.j2": " ", "missing.j2": TemplateNotFoundError(), "valid.j2": "contenido"})
    expected = (
        "acme/LAB/provision/access/default: plantilla ilegible 'missing.j2'",
        "acme/LAB/provision/access/default: servicio no registrado",
        "zeta/DIA/provision/access/default: plantilla vacía 'empty.j2'",
    )
    for order in [definitions, list(reversed(definitions))]:
        catalog = PluginCatalog()
        catalog.register_service(_Parser())
        for definition in order:
            catalog.register_vendor(definition)
        assert catalog.verify_consistency(source) == catalog.verify_consistency(source) == expected
        with pytest.raises(PluginConsistencyError) as error:
            catalog.assert_consistent(source)
        assert str(error.value) == "\n".join(expected)


def test_catalog_instances_and_identifier_snapshots_are_isolated() -> None:
    """Aísla registros entre catálogos y conserva las instantáneas ya consultadas."""
    catalog = PluginCatalog()
    vendors, services = catalog.vendor_ids(), catalog.service_types()
    catalog.register_vendor(VendorDefinition("acme", {}))
    catalog.register_service(_Parser())
    assert vendors == services == frozenset()
    assert PluginCatalog().vendor_ids() == PluginCatalog().service_types() == frozenset()


@pytest.mark.parametrize(
    "key", [TemplateKey("LAB", Operation.PROVISION, NodeRole.ACCESS),
            TemplateKey("DIA", Operation.TEARDOWN, NodeRole.ACCESS),
            TemplateKey("DIA", Operation.PROVISION, NodeRole.TRANSIT),
            TemplateKey("DIA", Operation.PROVISION, NodeRole.PROVIDER_EDGE),
            TemplateKey("DIA", Operation.PROVISION, NodeRole.ACCESS, "lab")],
)
def test_support_depends_on_every_template_key_field(key: TemplateKey) -> None:
    """Distingue servicio, operación, rol y variante al resolver combinaciones."""
    catalog = PluginCatalog()
    catalog.register_vendor(VendorDefinition("acme", {_key(): "access.j2"}))
    assert not catalog.supports("acme", key)
    with pytest.raises(UnsupportedCombinationError):
        catalog.resolve_template("acme", key)


def test_readable_template_still_requires_registered_service() -> None:
    """Detecta un servicio inexistente aunque su plantilla sea legible y no vacía."""
    catalog = PluginCatalog()
    catalog.register_vendor(VendorDefinition("acme", {_key("LAB"): "access.j2"}))
    assert catalog.verify_consistency(_Source({"access.j2": "contenido"})) == (
        "acme/LAB/provision/access/default: servicio no registrado",
    )


def test_template_declaration_order_does_not_change_diagnostics() -> None:
    """Mantiene los mensajes al invertir el orden de plantillas de un mismo vendor."""
    declarations = [(_key(role=NodeRole.TRANSIT), "transit.j2"), (_key(), "access.j2")]
    source = _Source({"transit.j2": " ", "access.j2": ""})
    results = []
    for order in [declarations, list(reversed(declarations))]:
        catalog = PluginCatalog()
        catalog.register_vendor(VendorDefinition("acme", dict(order)))
        catalog.register_service(_Parser())
        results.append(catalog.verify_consistency(source))
    assert results[0] == results[1] == (
        "acme/DIA/provision/access/default: plantilla vacía 'access.j2'",
        "acme/DIA/provision/transit/default: plantilla vacía 'transit.j2'",
    )


def test_invalid_utf8_resource_fails_consistency(tmp_path: Path) -> None:
    """Informa como ilegible una plantilla real que no contiene UTF-8 válido."""
    (tmp_path / "access.j2").write_bytes(b"\xff")
    catalog = PluginCatalog()
    catalog.register_vendor(VendorDefinition("acme", {_key(): "access.j2"}))
    catalog.register_service(_Parser())
    with pytest.raises(PluginConsistencyError) as error:
        catalog.assert_consistent(PackagedTemplateSource({"acme": tmp_path}))
    assert str(error.value) == "acme/DIA/provision/access/default: plantilla ilegible 'access.j2'"
