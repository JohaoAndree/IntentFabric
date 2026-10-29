"""Definición declarativa del vendor Cisco."""

from intentfabric.domain.vendor_definition import VendorDefinition
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey

VENDOR_DEFINITION = VendorDefinition(vendor_id="cisco", templates={
    TemplateKey(service_type, operation, role): f"templates/{service_type.lower()}/{operation.value}/{role.value}.j2"
    for service_type in ("DIA", "L3VPN") for operation in Operation for role in NodeRole
})


def build_cisco_qos_context(cir_kbps: int, pir_kbps: int) -> dict[str, object]:
    """Expresa las tasas QoS de Cisco en bits por segundo."""
    return {
        "rate_unit": "bps", "cir_rate": cir_kbps * 1_000, "pir_rate": pir_kbps * 1_000,
        "cir_bps": cir_kbps * 1_000, "pir_bps": pir_kbps * 1_000,
    }
