"""Artefactos inmutables y huellas deterministas de configuracion generada."""

from dataclasses import dataclass
from hashlib import sha256
from ipaddress import IPv4Address

from intentfabric.domain.template_key import NodeRole, Operation, TemplateKey


def compute_sha256(content: str) -> str:
    """Calcula la huella SHA-256 del contenido codificado en UTF-8."""
    return sha256(content.encode("utf-8")).hexdigest()


def normalize_rendered_config(raw_text: str) -> str:
    """Normaliza terminadores y espacios finales conservando la indentacion CLI."""
    lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n" if lines else ""


@dataclass(frozen=True, slots=True)
class NodeConfigurationArtifact:
    """Conserva la configuracion normalizada de un salto y su huella verificable."""

    hop_index: int
    node_id: str
    management_ip: IPv4Address
    vendor: str
    role: NodeRole
    operation: Operation
    template_key: TemplateKey
    rendered_text: str
    commands: tuple[str, ...]
    sha256: str

    def __post_init__(self) -> None:
        if type(self.hop_index) is not int or self.hop_index < 0:
            raise ValueError("hop_index: se requiere un entero no negativo")
        if not self.node_id.strip():
            raise ValueError("node_id: se requiere texto no vacio")
        if not self.rendered_text or normalize_rendered_config(self.rendered_text) != self.rendered_text:
            raise ValueError("rendered_text: se requiere configuracion no vacia y normalizada")
        expected_commands = tuple(
            line for line in self.rendered_text.splitlines()
            if line.strip() and not line.lstrip().startswith(("!", "#"))
        )
        if self.commands != expected_commands:
            raise ValueError("commands: deben coincidir con las lineas CLI sin comentarios")
        if self.sha256 != compute_sha256(self.rendered_text):
            raise ValueError("sha256: debe corresponder al texto renderizado en UTF-8")


@dataclass(frozen=True, slots=True)
class ServiceGenerationPlan:
    """Agrupa los artefactos en orden de ruta con una huella global reproducible."""

    service_id: str
    service_type: str
    operation: Operation
    variant: str
    artifacts: tuple[NodeConfigurationArtifact, ...]
    plan_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.artifacts, tuple) or not self.artifacts:
            raise ValueError("artifacts: se requiere una tupla no vacia")
        expected_hash = compute_sha256("|".join(
            f"{artifact.hop_index}:{artifact.node_id}:{artifact.sha256}"
            for artifact in self.artifacts
        ))
        if self.plan_sha256 != expected_hash:
            raise ValueError("plan_sha256: debe corresponder a los artefactos en orden de ruta")

    def to_dict(self) -> dict[str, object]:
        """Serializa campos y artefactos en orden fijo con valores JSON compatibles."""
        return {
            "service_id": self.service_id,
            "service_type": self.service_type,
            "operation": self.operation.value,
            "variant": self.variant,
            "artifacts": [
                {
                    "hop_index": artifact.hop_index,
                    "node_id": artifact.node_id,
                    "management_ip": str(artifact.management_ip),
                    "vendor": artifact.vendor,
                    "role": artifact.role.value,
                    "operation": artifact.operation.value,
                    "template_key": {
                        "service_type": artifact.template_key.service_type,
                        "operation": artifact.template_key.operation.value,
                        "role": artifact.template_key.role.value,
                        "variant": artifact.template_key.variant,
                    },
                    "rendered_text": artifact.rendered_text,
                    "commands": list(artifact.commands),
                    "sha256": artifact.sha256,
                }
                for artifact in self.artifacts
            ],
            "plan_sha256": self.plan_sha256,
        }
