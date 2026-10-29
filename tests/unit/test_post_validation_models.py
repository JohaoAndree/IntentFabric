"""Garantiza derivaciones, inmutabilidad e invariantes del estado posdespliegue."""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import json

import pytest

from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.bootstrap import build_plugin_catalog
from intentfabric.domain import (
    DiaIntent, L2VpnIntent, L3VpnIntent,
    EphemeralProbeCleanupError, IntentFabricError, ObservedState, PostValidationFailedError,
    PostValidationReport, ServiceOperationalStatus, TriageStepName, TriageStepResult,
    build_ephemeral_svi_provision_commands, build_ephemeral_svi_teardown_commands,
    build_expected_state,
)


_ROOT = Path(__file__).resolve().parents[2]


def _intent(service: str = "dia") -> DiaIntent | L3VpnIntent | L2VpnIntent:
    return build_plugin_catalog().parse_intent(
        load_intent_mapping(_ROOT / f"examples/intents/{service}_valid.json"),
    )


def _report() -> PostValidationReport:
    expected = build_expected_state(_intent())
    observed = ObservedState(True, expected.expected_lldp_ports, expected.l2_node_ids,
                             expected.l2_node_ids, True, True, True)
    step = TriageStepResult(TriageStepName.PE_INTERFACE_STATE, True, expected.pe_node_id,
                            "Subinterfaz activa", ("display interface brief",))
    return PostValidationReport(expected.service_id, expected.service_type, "default",
                                ServiceOperationalStatus.OPERATIONAL, 1, expected, observed, (step,))


@pytest.mark.parametrize("service", ["dia", "l3vpn", "l2vpn"])
def test_expected_state_derives_route_order_and_service_fields(service: str) -> None:
    """Deriva interfaces canonicas, ruta y sonda segun el tipo de servicio."""
    intent = _intent(service)
    expected = build_expected_state(intent, variant="default")
    assert expected == build_expected_state(intent)
    assert expected.service_id == intent.description
    assert expected.service_type == intent.service_type
    assert expected.pe_subinterface == f"{intent.provider_edge.parent_interface}.{intent.vlan_id}"
    ports = [(intent.access.node_id, intent.access.uplink_interface)]
    for transit in intent.transits:
        ports.extend(((transit.node_id, transit.downstream_interface),
                      (transit.node_id, transit.upstream_interface)))
    ports.append((intent.provider_edge.node_id, intent.provider_edge.parent_interface))
    assert expected.expected_lldp_ports == tuple(ports)
    assert expected.l2_node_ids == (intent.access.node_id, *(hop.node_id for hop in intent.transits))
    if service == "l2vpn":
        assert not expected.requires_svi_probe
        assert expected.pw_id == intent.pw_id and expected.evi_id == intent.evi_id
        assert all(getattr(expected, name) is None for name in (
            "svi_interface", "svi_ip_address", "svi_netmask", "ping_target_ip",
            "vrf_name", "expected_route_prefix", "bgp_neighbor_ip",
        ))
    else:
        assert expected.requires_svi_probe
        assert expected.svi_interface == f"Vlan{intent.vlan_id}"
        assert expected.svi_ip_address == str(intent.wan_network.network_address + 2)
        assert expected.ping_target_ip == str(intent.wan_network.network_address + 1)
        assert expected.svi_netmask == "255.255.255.252"
        assert expected.vrf_name == intent.vrf_name
        assert expected.expected_route_prefix == str(intent.lan_network if service == "dia" else intent.wan_network)
        assert expected.bgp_neighbor_ip == (expected.svi_ip_address if service == "l3vpn" else None)


def test_huawei_access_derives_vlanif_and_variant_is_preserved() -> None:
    """Deriva Vlanif para acceso Huawei y conserva la variante solicitada."""
    intent = _intent()
    expected = build_expected_state(replace(intent, access=replace(intent.access, vendor="huawei")), variant="lab")
    assert expected.svi_interface == f"Vlanif{intent.vlan_id}"
    assert expected.variant == "lab"


@pytest.mark.parametrize("vendor,interface,shutdown,remove", [
    ("cisco", "Vlan210", " no shutdown", "no interface Vlan210"),
    ("huawei", "Vlanif210", " undo shutdown", "undo interface Vlanif210"),
])
def test_svi_commands_preserve_prescribed_syntax(vendor: str, interface: str, shutdown: str, remove: str) -> None:
    """Conserva sintaxis y orden exactos de creacion y eliminacion SVI."""
    assert build_ephemeral_svi_provision_commands(vendor, 210, "192.0.2.2", "255.255.255.252") == (
        f"interface {interface}", " ip address 192.0.2.2 255.255.255.252", shutdown,
    )
    assert build_ephemeral_svi_teardown_commands(vendor, 210) == (remove,)


@pytest.mark.parametrize("field,value", [
    ("step", "pe_interface_state"), ("passed", 1), ("node_id", " "),
    ("details", ""), ("commands_executed", ()), ("commands_executed", ["show vlan brief"]),
])
def test_triage_step_rejects_invalid_contract_fields(field: str, value: object) -> None:
    """Rechaza eslabones sin identidad, resultado booleano o comandos."""
    with pytest.raises(ValueError, match=field):
        replace(_report().steps[0], **{field: value})


@pytest.mark.parametrize("status", list(ServiceOperationalStatus))
def test_report_enforces_sdc_and_root_cause(status: ServiceOperationalStatus) -> None:
    """Exige SDC y causa raiz coherentes para los tres estados operativos."""
    failed = status == ServiceOperationalStatus.FAILED
    changes = dict(status=status, sdc=int(not failed),
                   root_cause_step=TriageStepName.PE_INTERFACE_STATE if failed else None,
                   root_cause_node_id="PE-LAB" if failed else None)
    report = replace(_report(), **changes)
    assert report.is_compliant is not failed
    with pytest.raises(ValueError, match="sdc"):
        replace(report, sdc=int(failed))
    if failed:
        for name in ("root_cause_step", "root_cause_node_id"):
            with pytest.raises(ValueError, match="root_cause"):
                replace(report, **{name: None})
    else:
        with pytest.raises(ValueError, match="root_cause"):
            replace(report, root_cause_node_id="PE-LAB")


@pytest.mark.parametrize("changes", [{"status": "OPERATIONAL"}, {"sdc": True}, {"steps": ()}])
def test_report_rejects_invalid_types_or_empty_steps(changes: dict[str, object]) -> None:
    """Rechaza estados sin enumerado, SDC booleano y reportes vacios."""
    with pytest.raises(ValueError):
        replace(_report(), **changes)


def test_models_are_frozen_slotted_and_serialize_in_fixed_order() -> None:
    """Impide mutaciones y produce JSON reproducible sin tuplas residuales."""
    report = _report()
    for model in (report, report.expected_state, report.observed_state, report.steps[0]):
        assert not hasattr(model, "__dict__")
        field = next(iter(model.__dataclass_fields__))
        with pytest.raises(FrozenInstanceError):
            setattr(model, field, None)
    serialized = report.to_dict()
    assert list(serialized) == [
        "service_id", "service_type", "variant", "status", "sdc", "is_compliant",
        "root_cause_step", "root_cause_node_id", "expected_state", "observed_state", "steps",
    ]
    assert json.loads(json.dumps(serialized)) == serialized
    assert json.dumps(serialized) == json.dumps(_report().to_dict())


def test_exceptions_preserve_context_and_report() -> None:
    """Expone contexto de limpieza y reporte fallido en errores del framework."""
    cleanup = EphemeralProbeCleanupError("fallo", node_id="SW-LAB", vlan_id=210)
    assert isinstance(cleanup, IntentFabricError)
    assert (cleanup.node_id, cleanup.vlan_id) == ("SW-LAB", 210)
    report = replace(_report(), status=ServiceOperationalStatus.FAILED, sdc=0,
                     root_cause_step=TriageStepName.PE_INTERFACE_STATE, root_cause_node_id="PE-LAB")
    failure = PostValidationFailedError(report)
    assert isinstance(failure, IntentFabricError) and failure.report is report
    for value in (report.service_id, "FAILED", "pe_interface_state", "PE-LAB"):
        assert value in str(failure)
