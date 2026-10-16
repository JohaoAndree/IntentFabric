"""Comprueba las claves de plantilla y sus nombres permitidos."""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest

from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey


def test_key_preserves_operation_role_and_default_variant() -> None:
    """Conserva los discriminantes de plantilla y utiliza default cuando se omite."""
    key = TemplateKey("DIA", Operation.PROVISION, NodeRole.PROVIDER_EDGE)
    assert key.variant == "default"
    assert key.operation == "provision"
    assert key.role == "pe"
    assert set(Operation) == {Operation.PROVISION, Operation.TEARDOWN}
    assert set(NodeRole) == {NodeRole.ACCESS, NodeRole.TRANSIT, NodeRole.PROVIDER_EDGE}
    assert {key: "template"}[TemplateKey("DIA", Operation.PROVISION, NodeRole.PROVIDER_EDGE)] == "template"
    with pytest.raises(FrozenInstanceError):
        key.variant = "other"


@pytest.mark.parametrize("service_type", ["DIA", "L3VPN", "L2VPN", "LAB_SERVICE_1", "A"])
@pytest.mark.parametrize("variant", ["default", "lab_1", "a"])
def test_valid_service_and_variant_names(service_type: str, variant: str) -> None:
    """Admite nombres de servicio y variante conformes a las expresiones del ADR."""
    key = TemplateKey(service_type, Operation.TEARDOWN, NodeRole.TRANSIT, variant)
    assert (key.service_type, key.variant) == (service_type, variant)


@pytest.mark.parametrize("service_type", ["", "dia", "1DIA", "DIA-1", "DIA\n", None, 1])
def test_invalid_service_name_raises_value_error(service_type: Any) -> None:
    """Rechaza nombres de servicio ajenos al formato, incluido un salto de línea final."""
    with pytest.raises(ValueError, match="service_type:"):
        TemplateKey(service_type, Operation.PROVISION, NodeRole.ACCESS)


@pytest.mark.parametrize("variant", ["", "Default", "1lab", "lab-1", "lab\n", None, 1])
def test_invalid_variant_raises_value_error(variant: Any) -> None:
    """Rechaza variantes ajenas al formato con un error de campo."""
    with pytest.raises(ValueError, match="variant:"):
        TemplateKey("DIA", Operation.PROVISION, NodeRole.ACCESS, variant)
