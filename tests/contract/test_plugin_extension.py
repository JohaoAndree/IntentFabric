"""Demuestra la extensión declarativa con un vendor sintético y recursos temporales."""

from pathlib import Path

from intentfabric.adapters.packaged_template_source import PackagedTemplateSource
from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey
from intentfabric.domain.vendor_definition import VendorDefinition
from intentfabric.services.dia.intent_parser import DiaIntentParser


def test_new_vendor_resolves_and_verifies_without_core_changes(tmp_path: Path) -> None:
    """Registra acme y verifica su plantilla temporal usando los contratos existentes."""
    key = TemplateKey("DIA", Operation.PROVISION, NodeRole.ACCESS)
    resource_path = "templates/dia/provision/access.j2"
    path = tmp_path / resource_path
    path.parent.mkdir(parents=True)
    content = "plantilla sintética del laboratorio\n"
    path.write_text(content, encoding="utf-8", newline="\n")
    catalog = PluginCatalog()
    catalog.register_vendor(VendorDefinition("acme", {key: resource_path}))
    catalog.register_service(DiaIntentParser(known_vendors=catalog.vendor_ids()))
    source = PackagedTemplateSource({"acme": tmp_path})
    assert catalog.vendor_ids() == frozenset({"acme"})
    assert catalog.service_types() == frozenset({"DIA"})
    assert catalog.supports("acme", key)
    assert catalog.resolve_template("acme", key) == resource_path
    assert source.read_text("acme", catalog.resolve_template("acme", key)) == content
    assert catalog.verify_consistency(source) == ()
    assert catalog.assert_consistent(source) is None
