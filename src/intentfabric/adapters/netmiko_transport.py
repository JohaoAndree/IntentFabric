"""Transporte SSH con confirmacion exclusiva de Huawei VRPv8 y errores explicitos."""

from collections.abc import Callable, Mapping, Sequence
import os
from typing import Any

from intentfabric.domain.deployment import DeviceCredentials, find_cli_error_line
from intentfabric.domain.errors import CliCommandRejectedError, DeviceTransportError
from intentfabric.domain.topology import OsFamily, TopologyNode


def load_credentials_from_env(
    env: Mapping[str, str] | None = None, *, prefix: str = "INTENTFABRIC_SSH_",
) -> DeviceCredentials:
    """Carga credenciales SSH del entorno con limites validados por el dominio."""
    environment = os.environ if env is None else env
    username = environment.get(f"{prefix}USERNAME", "")
    password = environment.get(f"{prefix}PASSWORD", "")
    if not username.strip() or not password.strip():
        raise DeviceTransportError(
            "credenciales SSH ausentes: defina INTENTFABRIC_SSH_USERNAME e INTENTFABRIC_SSH_PASSWORD",
            node_id="env",
        )
    try:
        port = int(environment.get(f"{prefix}PORT", "22"))
        timeout = int(environment.get(f"{prefix}TIMEOUT", "30"))
    except ValueError as error:
        raise DeviceTransportError("PORT y TIMEOUT: se requieren enteros", node_id="env") from error
    try:
        return DeviceCredentials(username, password, environment.get(f"{prefix}SECRET"), port, timeout)
    except ValueError as error:
        raise DeviceTransportError(str(error), node_id="env") from error


def _transport_error_types() -> tuple[type[Exception], ...]:
    try:
        from netmiko.exceptions import NetmikoBaseException
        from paramiko.ssh_exception import SSHException
    except ModuleNotFoundError as error:
        if error.name not in ("netmiko", "paramiko"):
            raise
        return OSError, EOFError
    return OSError, EOFError, NetmikoBaseException, SSHException


class NetmikoTransportAdapter:
    """Abre una sesion por interaccion y comprueba rechazos antes de confirmar."""

    def __init__(
        self, credentials: DeviceCredentials, *, connect_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._credentials = credentials
        self._connect_factory = connect_factory

    def _connect(self, node: TopologyNode) -> Any:
        factory = self._connect_factory
        if factory is None:
            try:
                from netmiko import ConnectHandler
            except ModuleNotFoundError as error:
                if error.name != "netmiko":
                    raise
                raise DeviceTransportError(
                    "netmiko: instale las dependencias SSH declaradas", node_id=node.node_id,
                ) from error
            factory = ConnectHandler
        return factory(
            device_type=node.os_family.value, host=str(node.management_ip),
            username=self._credentials.username, password=self._credentials.password,
            secret=self._credentials.secret or "", port=self._credentials.port,
            timeout=self._credentials.timeout_seconds,
        )

    @staticmethod
    def _require_accepted(output: str, node: TopologyNode, command: str) -> None:
        error_line = find_cli_error_line(output, vendor=node.vendor)
        if error_line is not None:
            raise CliCommandRejectedError(
                error_line, node_id=node.node_id, command=command, raw_output=output,
            )

    def execute_show(self, node: TopologyNode, command: str) -> str:
        """Ejecuta una consulta operativa y traduce fallos SSH al error del dominio."""
        try:
            with self._connect(node) as connection:
                output = connection.send_command(
                    command, strip_prompt=True, strip_command=True,
                ).replace("\r\n", "\n")
                self._require_accepted(output, node, command)
                return output
        except _transport_error_types() as error:
            raise DeviceTransportError(str(error), node_id=node.node_id, command=command) from error

    def push_configuration(self, node: TopologyNode, commands: Sequence[str]) -> tuple[str, bool]:
        """Envia configuracion y ejecuta commit solo en la familia Huawei VRPv8."""
        commands = tuple(commands)
        command_block = "\n".join(commands)
        if not commands:
            raise DeviceTransportError("commands: se requiere una secuencia no vacia", node_id=node.node_id)
        committed = node.os_family == OsFamily.HUAWEI_VRPV8
        try:
            with self._connect(node) as connection:
                output = connection.send_config_set(
                    list(commands), exit_config_mode=not committed,
                ).replace("\r\n", "\n")
                self._require_accepted(output, node, command_block)
                if committed:
                    commit_output = connection.commit().replace("\r\n", "\n")
                    connection.exit_config_mode()
                    output += commit_output
                    self._require_accepted(output, node, command_block)
                return output, committed
        except _transport_error_types() as error:
            raise DeviceTransportError(str(error), node_id=node.node_id, command=command_block) from error
