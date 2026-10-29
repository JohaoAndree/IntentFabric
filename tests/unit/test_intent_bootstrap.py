"""Comprueba la composicion DIA con inventario y vendors registrados."""

from dataclasses import replace
from pathlib import Path
from types import ModuleType

import pytest

from intentfabric import bootstrap
from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.domain.errors import IntentParseError, PreValidationFailedError, TopologyValidationError
from intentfabric.domain.intent import DiaIntent
from intentfabric.domain.topology import TopologyCatalog
from intentfabric.domain.vendor_definition import VendorDefinition
from intentfabric.vendors import cisco, huawei


def _raw() -> dict[str, object]:
    return dict(load_intent_mapping(Path(__file__).resolve().parents[2] / "examples/intents/dia_valid.json"))


def test_bootstrap_registers_dia_with_default_vendors() -> None:
    """Interpreta la ruta inventariada con Cisco y Huawei registrados por defecto."""
    intent = bootstrap.build_plugin_catalog().parse_intent(_raw())
    assert isinstance(intent, DiaIntent)
    assert intent.access.vendor == "cisco"
    assert intent.provider_edge.vendor == "huawei"
    assert intent.access.node_id == "S3-9306-TEST"


def test_bootstrap_accepts_new_vendor_without_core_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conserva el registro extensible de fabricantes junto con los nodos inventariados."""
    package = ModuleType("lab_vendor")
    package.VENDOR_DEFINITION = VendorDefinition("lab", {})
    monkeypatch.setattr(bootstrap, "VENDOR_PACKAGES", (package, cisco, huawei))
    catalog = bootstrap.build_plugin_catalog()
    assert catalog.vendor_ids() == frozenset({"lab", "cisco", "huawei"})
    assert catalog.parse_intent(_raw()).access.vendor == "cisco"
    monkeypatch.setattr(bootstrap, "VENDOR_PACKAGES", (package, cisco))
    with pytest.raises(IntentParseError, match=r"hops\[1\].vendor: vendor no registrado"):
        bootstrap.build_plugin_catalog().parse_intent(_raw())


def test_bootstrap_does_not_share_custom_vendors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aisla los fabricantes personalizados de los registros construidos despues."""
    package = ModuleType("lab_vendor")
    package.VENDOR_DEFINITION = VendorDefinition("lab", {})
    with monkeypatch.context() as context:
        context.setattr(bootstrap, "VENDOR_PACKAGES", (package,))
        assert bootstrap.build_plugin_catalog().vendor_ids() == frozenset({"lab"})
    assert bootstrap.build_plugin_catalog().parse_intent(_raw()).access.vendor == "cisco"


def test_bootstrap_keeps_unknown_service_diagnostic() -> None:
    """Informa DIA como registrado cuando se solicita un servicio desconocido."""
    with pytest.raises(IntentParseError) as error:
        bootstrap.build_plugin_catalog().parse_intent({"service_type": "OTHER"})
    assert str(error.value) == "service_type: servicio desconocido 'OTHER'; registrados: DIA"


def test_bootstrap_injects_the_same_custom_inventory_into_parser_and_validator() -> None:
    """Resuelve y valida contra el inventario suministrado en lugar del predeterminado."""
    original = bootstrap.load_default_topology()
    modified_access = replace(original.get_node("S3-9306-TEST"), interfaces=("Gi1/0/2", "Gi1/0/10"))
    topology = TopologyCatalog(tuple(modified_access if node.node_id == modified_access.node_id else node for node in original.nodes), original.links)
    catalog = bootstrap.create_default_catalog(topology)
    raw = _raw() | {"access_interface": "Gi1/0/2"}
    intent = catalog.parse_intent(raw)
    assert bootstrap.create_default_generator(catalog, topology=topology).generate(intent).artifacts[0].node_id == modified_access.node_id
    with pytest.raises(PreValidationFailedError) as error:
        bootstrap.create_default_generator(catalog, topology=topology).generate(replace(intent, access=replace(intent.access, customer_port="Gi1/0/1")))
    assert "TOPOLOGY_INTERFACE_NOT_FOUND" in {issue.code for issue in error.value.report.errors}


def test_default_inventory_can_be_loaded_from_an_explicit_path(tmp_path: Path) -> None:
    """Permite elegir la ruta del catalogo y traduce archivos ausentes sin fallback."""
    with pytest.raises(TopologyValidationError):
        bootstrap.load_default_topology(tmp_path / "missing.yaml")
    path = Path(__file__).resolve().parents[2] / "inventory/topology.yaml"
    assert bootstrap.load_default_topology(path) == bootstrap.load_default_topology()
