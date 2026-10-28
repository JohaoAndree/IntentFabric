"""Definición declarativa del vendor Huawei."""

from intentfabric.domain.vendor_definition import VendorDefinition
from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey

VENDOR_DEFINITION = VendorDefinition(vendor_id="huawei", templates={
    TemplateKey("DIA", operation, role): f"templates/dia/{operation.value}/{role.value}.j2"
    for operation in Operation for role in NodeRole
})


def build_huawei_qos_context(cir_kbps: int, pir_kbps: int) -> dict[str, object]:
    """Expresa las tasas QoS de Huawei en kilobits por segundo."""
    return {
        "rate_unit": "kbps", "cir_rate": cir_kbps, "pir_rate": pir_kbps,
        "cir_kbps": cir_kbps, "pir_kbps": pir_kbps,
    }
