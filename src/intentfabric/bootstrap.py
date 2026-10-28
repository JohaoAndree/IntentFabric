"""Raíz de composición: único módulo que nombra implementaciones concretas."""

from importlib.resources import files
from types import ModuleType

from intentfabric.adapters.packaged_template_source import PackagedTemplateSource
from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.services.dia.intent_parser import DiaIntentParser
from intentfabric.services.dia.validator import validate_dia_intent_semantics
from intentfabric.vendors import cisco, huawei


VENDOR_PACKAGES: tuple[ModuleType, ...] = (cisco, huawei)


def build_template_source() -> PackagedTemplateSource:
    """Construye las raíces de recursos a partir de los paquetes de vendor registrados."""
    return PackagedTemplateSource({
        package.VENDOR_DEFINITION.vendor_id: files(package)
        for package in VENDOR_PACKAGES
    })


def build_plugin_catalog() -> PluginCatalog:
    """Registra los vendors y deriva de ellos los vendors conocidos del parser DIA."""
    catalog = PluginCatalog()
    for package in VENDOR_PACKAGES:
        catalog.register_vendor(package.VENDOR_DEFINITION)
    catalog.register_service(DiaIntentParser(known_vendors=catalog.vendor_ids()))
    catalog.register_service_validator(DiaIntentParser.service_type, validate_dia_intent_semantics)
    return catalog


def build_verified_catalog() -> PluginCatalog:
    """Construye el catálogo y exige consistencia con los recursos empaquetados."""
    catalog = build_plugin_catalog()
    catalog.assert_consistent(build_template_source())
    return catalog
