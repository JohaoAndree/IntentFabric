"""Puerto de consultas operativas y envio de configuracion a dispositivos."""

from collections.abc import Sequence
from typing import Protocol

from intentfabric.domain.topology import TopologyNode


class DeviceTransportPort(Protocol):
    """Define las interacciones de transporte requeridas por las fases online."""

    def execute_show(self, node: TopologyNode, command: str) -> str:
        """Consulta un comando operativo y devuelve su salida textual normalizada."""
        ...

    def push_configuration(self, node: TopologyNode, commands: Sequence[str]) -> tuple[str, bool]:
        """Aplica comandos y devuelve la transcripcion y la confirmacion transaccional."""
        ...
