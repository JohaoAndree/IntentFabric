"""Definición declarativa del vendor Cisco."""

from intentfabric.domain.vendor_definition import VendorDefinition

# ADR-006 agrega las plantillas y sus declaraciones.
VENDOR_DEFINITION = VendorDefinition(vendor_id="cisco", templates={})


def build_cisco_qos_context(cir_kbps: int, pir_kbps: int) -> dict[str, object]:
    """Expresa las tasas QoS de Cisco en bits por segundo."""
    return {
        "rate_unit": "bps", "cir_rate": cir_kbps * 1_000, "pir_rate": pir_kbps * 1_000,
        "cir_bps": cir_kbps * 1_000, "pir_bps": pir_kbps * 1_000,
    }
