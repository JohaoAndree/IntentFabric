"""Definición declarativa del vendor Cisco."""

from intentfabric.domain.vendor_definition import VendorDefinition

# ADR-006 agrega las plantillas y sus declaraciones.
VENDOR_DEFINITION = VendorDefinition(vendor_id="cisco", templates={})
