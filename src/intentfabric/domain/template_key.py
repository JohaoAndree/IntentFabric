"""Claves inmutables de plantillas por servicio, operación, rol y variante."""

from dataclasses import dataclass
from enum import StrEnum
import re


class Operation(StrEnum):
    """Identifica las operaciones de aprovisionamiento y retiro de un servicio."""

    PROVISION = "provision"
    TEARDOWN = "teardown"


class NodeRole(StrEnum):
    """Identifica la posición funcional de un nodo en la ruta del servicio."""

    ACCESS = "access"
    TRANSIT = "transit"
    PROVIDER_EDGE = "pe"


@dataclass(frozen=True)
class TemplateKey:
    """Identifica una plantilla con nombres de servicio y variante válidos."""

    service_type: str
    operation: Operation
    role: NodeRole
    variant: str = "default"

    def __post_init__(self) -> None:
        if not isinstance(self.service_type, str) or re.fullmatch(
            r"[A-Z][A-Z0-9_]*", self.service_type
        ) is None:
            raise ValueError("service_type: se requiere el formato ^[A-Z][A-Z0-9_]*$")
        if not isinstance(self.variant, str) or re.fullmatch(
            r"[a-z][a-z0-9_]*", self.variant
        ) is None:
            raise ValueError("variant: se requiere el formato ^[a-z][a-z0-9_]*$")
