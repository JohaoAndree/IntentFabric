"""Transporte determinista en memoria para consultas y despliegues sin red."""

from collections.abc import Mapping, Sequence

from intentfabric.domain.deployment import CommandExecutionRecord, find_cli_error_line
from intentfabric.domain.errors import CliCommandRejectedError, DeviceTransportError
from intentfabric.domain.topology import OsFamily, TopologyNode


class SimulatedTransportAdapter:
    """Responde desde salidas inyectadas y conserva las interacciones completadas."""

    def __init__(
        self, show_outputs: Mapping[tuple[str, str], str] | None = None, *,
        default_show_outputs: Mapping[str, str] | None = None,
        config_outputs: Mapping[str, str] | None = None,
        failing_nodes: Mapping[str, Exception] | None = None,
    ) -> None:
        self._show_outputs = {
            (node_id, command.strip()): output
            for (node_id, command), output in (show_outputs or {}).items()
        }
        self._default_show_outputs = {
            command.strip(): output for command, output in (default_show_outputs or {}).items()
        }
        self._config_outputs = dict(config_outputs or {})
        self._failing_nodes: dict[str | tuple[str, str], Exception] = dict(failing_nodes or {})
        self._history: list[CommandExecutionRecord] = []

    @property
    def history(self) -> tuple[CommandExecutionRecord, ...]:
        """Devuelve una instantanea inmutable del historial en orden de ejecucion."""
        return tuple(self._history)

    def set_show_output(self, node_id: str, command: str, output: str) -> None:
        """Actualiza la respuesta operativa de un nodo y comando normalizado."""
        self._show_outputs[node_id, command.strip()] = output

    def execute_show(self, node: TopologyNode, command: str) -> str:
        """Consulta una salida simulada y registra la interaccion si tiene exito."""
        failure = self._failing_nodes.get((node.node_id, command.strip()))
        if failure is None:
            failure = self._failing_nodes.get(node.node_id)
        self._raise_failure(failure, node.node_id, command)
        output = self._show_outputs.get(
            (node.node_id, command.strip()), self._default_show_outputs.get(command.strip(), "")
        ).replace("\r\n", "\n")
        error_line = find_cli_error_line(output, vendor=node.vendor)
        if error_line is not None:
            raise CliCommandRejectedError(
                error_line, node_id=node.node_id, command=command, raw_output=output,
            )
        self._history.append(CommandExecutionRecord(
            node.node_id, node.os_family, "show", (command,), output, False,
        ))
        return output

    def push_configuration(self, node: TopologyNode, commands: Sequence[str]) -> tuple[str, bool]:
        """Simula el bloque de configuracion y confirma solo para Huawei VRPv8."""
        commands = tuple(commands)
        if not commands:
            raise DeviceTransportError("commands: se requiere una secuencia no vacia", node_id=node.node_id)
        self._raise_failure(self._failing_nodes.get(node.node_id), node.node_id, "\n".join(commands))
        output = self._config_outputs.get(node.node_id, "\n".join(commands) + "\n").replace("\r\n", "\n")
        error_line = find_cli_error_line(output, vendor=node.vendor)
        if error_line is not None:
            raise CliCommandRejectedError(
                error_line, node_id=node.node_id, command="\n".join(commands), raw_output=output,
            )
        committed = node.os_family == OsFamily.HUAWEI_VRPV8
        self._history.append(CommandExecutionRecord(
            node.node_id, node.os_family, "config", commands, output, committed,
        ))
        return output, committed

    @staticmethod
    def _raise_failure(failure: Exception | None, node_id: str, command: str) -> None:
        if failure is not None:
            if isinstance(failure, DeviceTransportError):
                raise failure
            raise DeviceTransportError(str(failure), node_id=node_id, command=command) from failure
