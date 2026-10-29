"""Raíz de composición: único módulo que nombra implementaciones concretas."""

from importlib.resources import files
from pathlib import Path
from types import ModuleType

from intentfabric.adapters.packaged_template_source import PackagedTemplateSource
from intentfabric.adapters.jinja_renderer import JinjaTemplateRenderer
from intentfabric.adapters.yaml_topology_repository import YamlTopologyRepository
from intentfabric.application.generation import DeterministicGeneratorService
from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.application.pre_validation import PreValidationService
from intentfabric.application.template_source import TemplateSource
from intentfabric.domain.topology import TopologyCatalog
from intentfabric.services.dia.context_builder import build_dia_hop_context
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


def load_default_topology(path: Path | str | None = None) -> TopologyCatalog:
    """Carga el inventario por defecto o la ruta indicada por el consumidor."""
    return YamlTopologyRepository(path if path is not None else Path("inventory/topology.yaml")).load_catalog()


def build_plugin_catalog(topology: TopologyCatalog | None = None) -> PluginCatalog:
    """Registra los vendors y deriva de ellos los vendors conocidos del parser DIA."""
    catalog = PluginCatalog()
    for package in VENDOR_PACKAGES:
        catalog.register_vendor(package.VENDOR_DEFINITION)
    topology = topology if topology is not None else load_default_topology()
    catalog.register_service(DiaIntentParser(known_vendors=catalog.vendor_ids(), topology=topology))
    catalog.register_service_validator(DiaIntentParser.service_type, validate_dia_intent_semantics)
    catalog.register_context_builder(DiaIntentParser.service_type, build_dia_hop_context)
    if "cisco" in catalog.vendor_ids():
        catalog.register_vendor_qos_builder("cisco", cisco.build_cisco_qos_context)
    if "huawei" in catalog.vendor_ids():
        catalog.register_vendor_qos_builder("huawei", huawei.build_huawei_qos_context)
    return catalog


def build_verified_catalog() -> PluginCatalog:
    """Construye el catálogo y exige consistencia con los recursos empaquetados."""
    catalog = build_plugin_catalog()
    catalog.assert_consistent(build_template_source())
    return catalog


def build_generator(
    catalog: PluginCatalog | None = None, template_source: TemplateSource | None = None,
    pre_validator: PreValidationService | None = None,
    topology: TopologyCatalog | None = None,
) -> DeterministicGeneratorService:
    """Compone el generador con recursos empaquetados y validacion previa por defecto."""
    if topology is None and (catalog is None or pre_validator is None):
        topology = load_default_topology()
    if catalog is None:
        catalog = build_plugin_catalog(topology)
    if template_source is None:
        template_source = build_template_source()
    if pre_validator is None:
        pre_validator = PreValidationService(catalog, topology=topology)
    return DeterministicGeneratorService(
        catalog, JinjaTemplateRenderer(catalog, template_source), pre_validator,
    )


create_default_catalog = build_plugin_catalog
create_default_generator = build_generator
