"""Modelos inmutables de transporte y despliegue con deteccion de rechazos CLI."""

from dataclasses import dataclass
from ipaddress import IPv4Address

from intentfabric.domain.template_key import NodeRole, Operation
from intentfabric.domain.topology import OsFamily


def find_cli_error_line(raw_output: str, *, vendor: str | None = None) -> str | None:
    """Devuelve el primer rechazo CLI reconocido para el fabricante indicado."""
    for raw_line in raw_output.splitlines():
        line = raw_line.strip()
        if vendor in (None, "cisco") and (
            any(marker in line for marker in (
                "% Invalid input", "% Incomplete command", "% Ambiguous command",
                "% Authorization failed",
            )) or line.startswith("% Error")
        ):
            return line
        if vendor in (None, "huawei") and line.lower().startswith((
            "error:", "error[", "unrecognized command", "wrong parameter",
            "incomplete command", "ambiguous command",
        )):
            return line
    return None


def contains_cli_error(raw_output: str, *, vendor: str | None = None) -> bool:
    """Indica si la transcripcion contiene un rechazo CLI reconocido."""
    return find_cli_error_line(raw_output, vendor=vendor) is not None


@dataclass(frozen=True, slots=True)
class DeviceCredentials:
    """Conserva credenciales SSH inyectadas sin exponer secretos en repr."""

    username: str
    password: str
    secret: str | None = None
    port: int = 22
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        for name in ("username", "password"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name}: se requiere texto no vacio")
        if self.secret is not None and (
            not isinstance(self.secret, str) or not self.secret.strip()
        ):
            raise ValueError("secret: se requiere None o texto no vacio")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("port: se requiere un entero en 1..65535")
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 600:
            raise ValueError("timeout_seconds: se requiere un entero en 1..600")

    def __repr__(self) -> str:
        secret = "'***'" if self.secret is not None else "None"
        return (
            f"DeviceCredentials(username={self.username!r}, password='***', "
            f"secret={secret}, port={self.port}, timeout_seconds={self.timeout_seconds})"
        )


@dataclass(frozen=True, slots=True)
class CommandExecutionRecord:
    """Conserva una interaccion de transporte en orden de ejecucion."""

    node_id: str
    os_family: OsFamily
    mode: str
    commands: tuple[str, ...]
    raw_output: str
    committed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("node_id: se requiere texto no vacio")
        if not isinstance(self.os_family, OsFamily):
            raise ValueError("os_family: se requiere OsFamily")
        if self.mode not in ("show", "config"):
            raise ValueError("mode: se requiere show o config")
        if not isinstance(self.commands, tuple) or not self.commands:
            raise ValueError("commands: se requiere una tupla no vacia")
        if not isinstance(self.raw_output, str):
            raise ValueError("raw_output: se requiere str")
        if type(self.committed) is not bool:
            raise ValueError("committed: se requiere bool")


@dataclass(frozen=True, slots=True)
class NodeDeploymentResult:
    """Conserva la transcripcion y la huella del artefacto aplicado en un salto."""

    hop_index: int
    node_id: str
    management_ip: IPv4Address
    vendor: str
    os_family: OsFamily
    role: NodeRole
    operation: Operation
    commands: tuple[str, ...]
    raw_output: str
    committed: bool
    sha256: str

    def __post_init__(self) -> None:
        if type(self.hop_index) is not int or self.hop_index < 0:
            raise ValueError("hop_index: se requiere un entero no negativo")
        for name in ("node_id", "sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name}: se requiere texto no vacio")
        if not isinstance(self.management_ip, IPv4Address):
            raise ValueError("management_ip: se requiere IPv4Address")
        if self.vendor not in ("cisco", "huawei"):
            raise ValueError("vendor: se requiere cisco o huawei")
        for name, expected in (("os_family", OsFamily), ("role", NodeRole), ("operation", Operation)):
            if not isinstance(getattr(self, name), expected):
                raise ValueError(f"{name}: se requiere {expected.__name__}")
        if not isinstance(self.commands, tuple) or not self.commands:
            raise ValueError("commands: se requiere una tupla no vacia")
        if not isinstance(self.raw_output, str):
            raise ValueError("raw_output: se requiere str")
        if type(self.committed) is not bool:
            raise ValueError("committed: se requiere bool")

    def to_dict(self) -> dict[str, object]:
        """Serializa el resultado con claves fijas y valores JSON compatibles."""
        return {
            "hop_index": self.hop_index,
            "node_id": self.node_id,
            "management_ip": str(self.management_ip),
            "vendor": self.vendor,
            "os_family": self.os_family.value,
            "role": self.role.value,
            "operation": self.operation.value,
            "commands": list(self.commands),
            "raw_output": self.raw_output,
            "committed": self.committed,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ServiceDeploymentReport:
    """Agrupa los resultados completados de un plan de despliegue."""

    service_id: str
    service_type: str
    operation: Operation
    variant: str
    plan_sha256: str
    results: tuple[NodeDeploymentResult, ...]

    def __post_init__(self) -> None:
        for name in ("service_id", "service_type", "variant", "plan_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name}: se requiere texto no vacio")
        if not isinstance(self.operation, Operation):
            raise ValueError("operation: se requiere Operation")
        if not isinstance(self.results, tuple) or not self.results:
            raise ValueError("results: se requiere una tupla no vacia")

    @property
    def is_successful(self) -> bool:
        """Indica que el reporte contiene resultados completados."""
        return len(self.results) > 0

    def to_dict(self) -> dict[str, object]:
        """Serializa el reporte y sus resultados en orden fijo."""
        return {
            "service_id": self.service_id,
            "service_type": self.service_type,
            "operation": self.operation.value,
            "variant": self.variant,
            "plan_sha256": self.plan_sha256,
            "is_successful": self.is_successful,
            "results": [result.to_dict() for result in self.results],
        }
