"""Garantiza contratos de transporte, confirmacion y fallos sin abrir sockets."""

import builtins
from typing import Any
from unittest.mock import MagicMock

import pytest

from intentfabric.adapters import (
    NetmikoTransportAdapter, SimulatedTransportAdapter, load_credentials_from_env,
)
from intentfabric.bootstrap import load_default_topology
from intentfabric.domain import (
    CliCommandRejectedError, DeviceCredentials, DeviceTransportError, OsFamily,
    TopologyNode,
)


def _node(node_id: str = "PE2-TEST") -> TopologyNode:
    return load_default_topology().get_node(node_id)


def _netmiko(node_id: str = "PE2-TEST") -> tuple[NetmikoTransportAdapter, MagicMock, MagicMock, TopologyNode]:
    factory = MagicMock()
    connection = factory.return_value.__enter__.return_value
    connection.send_command.return_value = "operational\r\n"
    connection.send_config_set.return_value = "configured\r\n"
    connection.commit.return_value = "committed\r\n"
    credentials = DeviceCredentials("lab-user", "lab-password", "lab-secret", 2222, 40)
    return NetmikoTransportAdapter(credentials, connect_factory=factory), factory, connection, _node(node_id)


@pytest.mark.parametrize("node_id", ["PE1-TEST", "S1-9306-TEST", "PE2-TEST"])
def test_transport_commit_is_exclusive_to_vrpv8(node_id: str) -> None:
    """Confirma unicamente VRPv8 y conserva comandos y transcripciones normalizadas."""
    adapter, factory, connection, node = _netmiko(node_id)
    expected = node.os_family == OsFamily.HUAWEI_VRPV8
    commands = ("vlan 210",)
    output, committed = adapter.push_configuration(node, commands)
    assert committed is expected
    assert output == ("configured\ncommitted\n" if expected else "configured\n")
    connection.send_config_set.assert_called_once_with(list(commands), exit_config_mode=not expected)
    assert connection.commit.call_count == int(expected)
    assert connection.exit_config_mode.call_count == int(expected)
    assert [call[0] for call in connection.method_calls] == (
        ["send_config_set", "commit", "exit_config_mode"] if expected else ["send_config_set"]
    )
    factory.assert_called_once_with(
        device_type=node.os_family.value, host=str(node.management_ip), username="lab-user",
        password="lab-password", secret="lab-secret", port=2222, timeout=40,
    )
    simulated = SimulatedTransportAdapter(config_outputs={node_id: "configured\r\n"})
    assert simulated.push_configuration(node, commands) == ("configured\n", expected)
    assert simulated.history[0].commands == commands
    assert simulated.history[0].committed is expected


def test_netmiko_show_uses_operational_session_and_normalizes_output() -> None:
    """Usa send_command con prompt y eco retirados y cierra la sesion."""
    adapter, factory, connection, node = _netmiko()
    assert adapter.execute_show(node, "display vlan") == "operational\n"
    connection.send_command.assert_called_once_with("display vlan", strip_prompt=True, strip_command=True)
    factory.return_value.__exit__.assert_called_once()
    connection.send_config_set.assert_not_called()
    connection.commit.assert_not_called()


def test_injected_connection_does_not_import_netmiko(monkeypatch: pytest.MonkeyPatch) -> None:
    """Permite usar una factoria inyectada sin resolver Netmiko."""
    original_import = builtins.__import__

    def guarded_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("netmiko"):
            raise AssertionError("Netmiko debe resolverse solo con la factoria por defecto")
        return original_import(name, *args, **kwargs)

    adapter, factory, connection, node = _netmiko()
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    assert adapter.execute_show(node, "display vlan") == "operational\n"
    assert adapter.push_configuration(node, ("vlan 210",))[1] is True


def test_default_factory_resolves_connecthandler_only_when_connecting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resuelve ConnectHandler al consultar sin conectar durante la construccion."""
    netmiko = pytest.importorskip("netmiko")
    factory = MagicMock()
    factory.return_value.__enter__.return_value.send_command.return_value = "ok\n"
    monkeypatch.setattr(netmiko, "ConnectHandler", factory)
    adapter = NetmikoTransportAdapter(DeviceCredentials("lab-user", "lab-password"))
    factory.assert_not_called()
    assert adapter.execute_show(_node(), "display vlan") == "ok\n"
    factory.assert_called_once()


@pytest.mark.parametrize("method", ["show", "config", "commit"])
def test_netmiko_cli_rejection_preserves_transcript_and_prevents_success(method: str) -> None:
    """Propaga rechazos operativos, de configuracion y de commit con su evidencia."""
    adapter, factory, connection, node = _netmiko()
    target = {"show": connection.send_command, "config": connection.send_config_set, "commit": connection.commit}
    target[method].return_value = "Error: rejected\r\n"
    with pytest.raises(CliCommandRejectedError) as caught:
        if method == "show":
            adapter.execute_show(node, "display vlan")
        else:
            adapter.push_configuration(node, ("vlan 210",))
    assert caught.value.node_id == node.node_id
    assert "Error: rejected\n" in caught.value.raw_output
    assert "\r" not in caught.value.raw_output
    if method != "commit":
        connection.commit.assert_not_called()
    factory.return_value.__exit__.assert_called_once()


def test_commit_rejection_is_detected_without_a_configuration_trailing_newline() -> None:
    """Detecta rechazos de commit independientemente del terminador de la salida previa."""
    adapter, factory, connection, node = _netmiko()
    connection.send_config_set.return_value = "configured"
    connection.commit.return_value = "Error: rejected"
    with pytest.raises(CliCommandRejectedError) as caught:
        adapter.push_configuration(node, ("vlan 210",))
    assert caught.value.raw_output == "configuredError: rejected"


@pytest.mark.parametrize("method", ["connect", "show", "config", "commit", "exit"])
def test_netmiko_wraps_transport_failures_and_closes_open_sessions(method: str) -> None:
    """Traduce fallos de conexion y de interaccion conservando la causa."""
    adapter, factory, connection, node = _netmiko()
    target = {
        "connect": factory, "show": connection.send_command,
        "config": connection.send_config_set, "commit": connection.commit,
        "exit": connection.exit_config_mode,
    }
    failure = OSError("lab disconnected")
    target[method].side_effect = failure
    with pytest.raises(DeviceTransportError) as caught:
        if method in ("connect", "show"):
            adapter.execute_show(node, "display vlan")
        else:
            adapter.push_configuration(node, ("vlan 210",))
    assert caught.value.__cause__ is failure
    assert caught.value.node_id == node.node_id
    assert caught.value.command == ("display vlan" if method in ("connect", "show") else "vlan 210")
    if method != "connect":
        factory.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("exception_name", ["NetmikoAuthenticationException", "NetmikoTimeoutException", "ReadTimeout"])
def test_netmiko_wraps_native_ssh_failures(exception_name: str) -> None:
    """Traduce las excepciones especificas de autenticacion y timeout de Netmiko."""
    exceptions = pytest.importorskip("netmiko.exceptions")
    adapter, factory, connection, node = _netmiko()
    failure = getattr(exceptions, exception_name)("lab failure")
    factory.side_effect = failure
    with pytest.raises(DeviceTransportError) as caught:
        adapter.execute_show(node, "display vlan")
    assert caught.value.__cause__ is failure


def test_simulated_outputs_fallback_updates_and_history_are_deterministic() -> None:
    """Prioriza nodo y comando, permite actualizar salidas y conserva instantaneas."""
    node = _node()
    outputs = {(node.node_id, " display vlan "): "node\r\n"}
    adapter = SimulatedTransportAdapter(outputs, default_show_outputs={"display vlan": "default\r\n"})
    outputs.clear()
    assert adapter.execute_show(node, "display vlan") == "node\n"
    snapshot = adapter.history
    adapter.set_show_output(node.node_id, " display vlan ", "updated\r\n")
    assert adapter.execute_show(node, " display vlan ") == "updated\n"
    assert adapter.execute_show(_node("S1-9306-TEST"), "display vlan") == "default\n"
    assert adapter.execute_show(node, "display bgp peer") == ""
    assert adapter.push_configuration(node, ("vlan 210",)) == ("vlan 210\n", True)
    assert len(snapshot) == 1
    assert [record.mode for record in adapter.history] == ["show", "show", "show", "show", "config"]
    assert all(not record.committed for record in adapter.history[:-1])


@pytest.mark.parametrize("method", ["show", "config"])
@pytest.mark.parametrize("native_error", [False, True])
def test_simulated_failures_are_explicit_and_do_not_record_success(method: str, native_error: bool) -> None:
    """Relanza errores del dominio o traduce fallos inyectados sin registrar exito."""
    node = _node()
    failure = DeviceTransportError("lab failure", node_id=node.node_id) if native_error else OSError("lab failure")
    adapter = SimulatedTransportAdapter(failing_nodes={node.node_id: failure})
    with pytest.raises(DeviceTransportError) as caught:
        if method == "show":
            adapter.execute_show(node, "display vlan")
        else:
            adapter.push_configuration(node, ("vlan 210",))
    assert adapter.history == ()
    assert caught.value is failure if native_error else caught.value.__cause__ is failure


def test_simulated_command_failure_takes_precedence_over_node_failure() -> None:
    """Permite fallos por comando con prioridad sobre el fallo del nodo."""
    node = _node()
    adapter = SimulatedTransportAdapter(failing_nodes={
        node.node_id: OSError("node failure"), (node.node_id, "display vlan"): OSError("command failure"),
    })
    with pytest.raises(DeviceTransportError, match="command failure"):
        adapter.execute_show(node, " display vlan ")


@pytest.mark.parametrize("method", ["show", "config"])
@pytest.mark.parametrize("node_id,output", [("PE1-TEST", "% Invalid input"), ("PE2-TEST", "Error: rejected")])
def test_simulated_cli_rejections_are_not_successful(method: str, node_id: str, output: str) -> None:
    """Detecta rechazos de ambos vendors sin agregar registros de exito."""
    node = _node(node_id)
    adapter = SimulatedTransportAdapter(
        default_show_outputs={"show vrf": output}, config_outputs={node_id: output},
    )
    with pytest.raises(CliCommandRejectedError) as caught:
        if method == "show":
            adapter.execute_show(node, "show vrf")
        else:
            adapter.push_configuration(node, ("vlan 210",))
    assert caught.value.raw_output == output
    assert adapter.history == ()


def test_empty_configuration_fails_before_connecting() -> None:
    """Rechaza bloques vacios en ambos adaptadores sin abrir sesion."""
    adapter, factory, connection, node = _netmiko()
    for transport in (adapter, SimulatedTransportAdapter()):
        with pytest.raises(DeviceTransportError, match="commands"):
            transport.push_configuration(node, ())
    factory.assert_not_called()


def test_credentials_are_loaded_from_mapping_or_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Carga campos requeridos, opcionales y prefijos desde el borde del sistema."""
    monkeypatch.setenv("INTENTFABRIC_SSH_USERNAME", "lab-user")
    monkeypatch.setenv("INTENTFABRIC_SSH_PASSWORD", "lab-password")
    assert load_credentials_from_env().username == "lab-user"
    defaults = load_credentials_from_env({"LAB_USERNAME": "lab-user", "LAB_PASSWORD": "lab-password"}, prefix="LAB_")
    assert (defaults.port, defaults.timeout_seconds, defaults.secret) == (22, 30, None)
    explicit = load_credentials_from_env({
        "LAB_USERNAME": "lab-user", "LAB_PASSWORD": "lab-password", "LAB_SECRET": "lab-secret",
        "LAB_PORT": "2222", "LAB_TIMEOUT": "40",
    }, prefix="LAB_")
    assert (explicit.port, explicit.timeout_seconds, explicit.secret) == (2222, 40, "lab-secret")


@pytest.mark.parametrize("overrides", [
    {"USERNAME": ""}, {"PASSWORD": " "}, {"PORT": "bad"}, {"PORT": "0"},
    {"TIMEOUT": "bad"}, {"TIMEOUT": "601"}, {"SECRET": ""},
])
def test_invalid_environment_credentials_fail_explicitly(overrides: dict[str, str]) -> None:
    """Rechaza ausencia y limites invalidos sin intentar conexiones."""
    environment = {"USERNAME": "lab-user", "PASSWORD": "lab-password", **overrides}
    with pytest.raises(DeviceTransportError) as caught:
        load_credentials_from_env(environment, prefix="")
    assert caught.value.node_id == "env"
    with pytest.raises(DeviceTransportError, match="credenciales SSH ausentes"):
        load_credentials_from_env({})
