"""Definición declarativa del vendor Huawei."""

from intentfabric.domain.vendor_definition import VendorDefinition

# ADR-006 agrega las plantillas y sus declaraciones.
VENDOR_DEFINITION = VendorDefinition(vendor_id="huawei", templates={})


def build_huawei_qos_context(cir_kbps: int, pir_kbps: int) -> dict[str, object]:
    """Expresa las tasas QoS de Huawei en kilobits por segundo."""
    return {
        "rate_unit": "kbps", "cir_rate": cir_kbps, "pir_rate": pir_kbps,
        "cir_kbps": cir_kbps, "pir_kbps": pir_kbps,
    }
