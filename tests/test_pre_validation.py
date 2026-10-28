"""Garantiza reportes inmutables y acumulativos de validacion previa."""

from dataclasses import FrozenInstanceError, replace
from ipaddress import IPv4Address, IPv4Network
from itertools import permutations
import json

import pytest

from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.bootstrap import build_plugin_catalog
from intentfabric.domain import (
    IntentFabricError, PreValidationFailedError, ValidationIssue,
    ValidationReport, ValidationSeverity, ValidationStage,
)
from intentfabric.domain.errors import (
    IntentParseError, PluginConsistencyError, PluginRegistrationError,
    TemplateNotFoundError, UnsupportedCombinationError,
)
from intentfabric.domain.intent import AccessHop, DiaIntent, ProviderEdgeHop, TransitHop
from intentfabric.services.dia import validate_dia_intent_semantics
from intentfabric.services.dia.intent_parser import DiaIntentParser


def _issue(**overrides: object) -> ValidationIssue:
    fields = {
        "code": "UNSUPPORTED_VENDOR",
        "message": "Registre un vendor soportado para el salto.",
        "stage": ValidationStage.STATIC_OFFLINE,
    }
    return ValidationIssue(**(fields | overrides))


def _dia_intent() -> DiaIntent:
    return DiaIntent(
        description="LAB-DIA-001", vlan_id=3001, vrf_name="LAB-INTERNET",
        wan_network=IPv4Network("198.51.100.0/30"),
        lan_network=IPv4Network("203.0.113.0/29"), bandwidth_mbps=50,
        qos_policy_name="LAB_50MB_PARENT",
        access=AccessHop("huawei", IPv4Address("192.0.2.11"), "port", "uplink"),
        transits=(TransitHop("cisco", IPv4Address("192.0.2.12"), "down", "up"),),
        provider_edge=ProviderEdgeHop("huawei", IPv4Address("192.0.2.21"), "parent"),
    )


@pytest.mark.parametrize("code", [None, 3, "", " \n\t", "lower_case", "BAD-CODE", " BAD", "1_BAD"])
def test_issue_rejects_invalid_codes(code: object) -> None:
    """Rechaza codigos vacios o ajenos al formato UPPER_SNAKE_CASE."""
    with pytest.raises(ValueError, match="code:"):
        _issue(code=code)


@pytest.mark.parametrize("message", [None, 3, "", " \n\t"])
def test_issue_rejects_empty_or_non_text_messages(message: object) -> None:
    """Exige un mensaje textual no vacio para cada hallazgo."""
    with pytest.raises(ValueError, match="message:"):
        _issue(message=message)


def test_issue_preserves_taxonomy_and_default_severity() -> None:
    """Conserva los campos de entrada y asigna ERROR por defecto."""
    issue = _issue(code="VLAN_802_1Q", field_path="vlan_id", node_id="LAB-PE")
    assert issue.severity is ValidationSeverity.ERROR
    assert issue.sort_key() == ("static_offline", "error", "VLAN_802_1Q", "LAB-PE", "vlan_id")
    assert _issue().sort_key() == ("static_offline", "error", "UNSUPPORTED_VENDOR", "", "")
    assert ValidationStage.PREFLIGHT_ONLINE.value == "preflight_online"
    assert ValidationSeverity.WARNING.value == "warning"


@pytest.mark.parametrize("model", [_issue(), ValidationReport("LAB-001", "DIA", ())])
def test_validation_models_are_frozen_and_slotted(
    model: ValidationIssue | ValidationReport,
) -> None:
    """Impide mutar campos y agregar atributos a los modelos de validacion."""
    field = "code" if isinstance(model, ValidationIssue) else "service_id"
    with pytest.raises(FrozenInstanceError):
        setattr(model, field, "CHANGED")
    assert not hasattr(model, "__dict__")


def test_report_canonically_orders_every_sort_dimension() -> None:
    """Ordena por subfase, severidad, codigo, nodo y campo sin depender de la insercion."""
    expected = (
        _issue(stage=ValidationStage.PREFLIGHT_ONLINE),
        _issue(code="DUPLICATE_NODE_HOP"),
        _issue(node_id="LAB-A", field_path="hops[0]"),
        _issue(node_id="LAB-A", field_path="hops[1]"),
        _issue(node_id="LAB-B"),
        _issue(severity=ValidationSeverity.WARNING),
    )
    serialized = json.dumps(ValidationReport("LAB-001", "DIA", expected).to_dict())
    for issue_order in permutations(expected):
        report = ValidationReport("LAB-001", "DIA", issue_order)
        assert report.issues == expected
        assert json.dumps(report.to_dict()) == serialized


def test_report_filters_errors_and_warnings_in_canonical_order() -> None:
    """Clasifica todos los hallazgos y solo considera invalidantes los errores."""
    error = _issue()
    warning = _issue(code="CHECK_POLICY", severity=ValidationSeverity.WARNING)
    report = ValidationReport("LAB-001", "DIA", (warning, error))
    assert report.errors == (error,)
    assert report.warnings == (warning,)
    assert not report.is_valid
    assert not report.preflight_executed
    assert ValidationReport("LAB-001", "DIA", (warning,)).is_valid
    assert ValidationReport("LAB-001", "DIA", ()).is_valid


def test_report_orders_messages_when_taxonomy_and_location_match() -> None:
    """Resuelve empates de la clave canonica sin depender del orden de llegada."""
    first = _issue(message="Declare la plantilla provision.")
    second = _issue(message="Declare la plantilla teardown.")
    assert first.sort_key() == second.sort_key()
    for issue_order in [(first, second), (second, first)]:
        assert ValidationReport("LAB-001", "DIA", issue_order).issues == (first, second)


@pytest.mark.parametrize("error_type", [
    IntentParseError, PluginConsistencyError, PluginRegistrationError,
    TemplateNotFoundError, UnsupportedCombinationError,
])
def test_existing_errors_inherit_the_framework_base(error_type: type[Exception]) -> None:
    """Conserva compatibilidad con Exception y permite capturar errores del framework."""
    assert issubclass(error_type, IntentFabricError)
    assert issubclass(error_type, Exception)


def test_pre_validation_error_preserves_the_report_and_error_codes() -> None:
    """Expone el reporte original y detalla servicio y errores en el mensaje."""
    warning = _issue(code="CHECK_POLICY", severity=ValidationSeverity.WARNING)
    report = ValidationReport("LAB-001", "DIA", (_issue(), warning))
    error = PreValidationFailedError(report)
    assert isinstance(error, IntentFabricError)
    assert error.report is report
    assert "LAB-001" in str(error)
    assert "['UNSUPPORTED_VENDOR']" in str(error)
    assert "CHECK_POLICY" not in str(error)


def test_report_serializes_explicit_values_and_fixed_field_order() -> None:
    """Expone conteos, subfase ejecutada y campos completos en orden fijo."""
    issue = _issue(field_path="hops[0].vendor", node_id="LAB-A")
    report = ValidationReport("LAB-001", "DIA", (issue,), preflight_executed=True)
    serialized = report.to_dict()
    assert list(serialized) == [
        "service_id", "service_type", "is_valid", "preflight_executed",
        "error_count", "warning_count", "issues",
    ]
    assert serialized == {
        "service_id": "LAB-001", "service_type": "DIA", "is_valid": False,
        "preflight_executed": True, "error_count": 1, "warning_count": 0,
        "issues": [{
            "code": "UNSUPPORTED_VENDOR", "message": issue.message,
            "stage": "static_offline", "severity": "error",
            "field_path": "hops[0].vendor", "node_id": "LAB-A",
        }],
    }
    assert list(serialized["issues"][0]) == [
        "code", "message", "stage", "severity", "field_path", "node_id",
    ]
    serialized["issues"].clear()
    assert report.issues == (issue,)


@pytest.mark.parametrize("vlan_id", [-1, 0, 4095])
def test_dia_rejects_vlans_outside_the_service_range(vlan_id: int) -> None:
    """Rechaza VLAN fuera de 1..4094 aunque la intencion se construya en memoria."""
    issues = validate_dia_intent_semantics(replace(_dia_intent(), vlan_id=vlan_id))
    assert len(issues) == 1
    assert issues[0].code == "INVALID_VLAN_RANGE"
    assert issues[0].field_path == "vlan_id"


@pytest.mark.parametrize("vlan_id", [1, 1002, 1003, 1004, 1005])
def test_dia_reports_each_cisco_hop_using_a_reserved_vlan(vlan_id: int) -> None:
    """Informa cada salto Cisco afectado por una VLAN reservada."""
    intent = _dia_intent()
    intent = replace(intent, vlan_id=vlan_id, access=replace(intent.access, vendor="cisco"))
    issues = validate_dia_intent_semantics(intent)
    assert [(issue.code, issue.field_path, issue.node_id) for issue in issues] == [
        ("RESERVED_CISCO_VLAN", "vlan_id", "192.0.2.11"),
        ("RESERVED_CISCO_VLAN", "vlan_id", "192.0.2.12"),
    ]


@pytest.mark.parametrize("vlan_id", [1, 1002, 1003, 1004, 1005, 4094])
def test_huawei_path_accepts_vlans_reserved_only_for_cisco(vlan_id: int) -> None:
    """No aplica la reserva Cisco cuando todos los saltos son Huawei."""
    intent = _dia_intent()
    intent = replace(intent, vlan_id=vlan_id, transits=tuple(
        replace(hop, vendor="huawei") for hop in intent.transits
    ))
    assert validate_dia_intent_semantics(intent) == ()


@pytest.mark.parametrize("address", [
    "198.51.100.0", "198.51.100.1", "198.51.100.2", "198.51.100.3",
    "203.0.113.0", "203.0.113.1", "203.0.113.7",
])
def test_dia_reports_management_overlap_in_wan_and_lan(address: str) -> None:
    """Detecta gestion contenida en WAN o LAN, incluidas sus direcciones de borde."""
    intent = _dia_intent()
    intent = replace(intent, provider_edge=replace(
        intent.provider_edge, management_ip=IPv4Address(address),
    ))
    issues = validate_dia_intent_semantics(intent)
    assert len(issues) == 1
    assert issues[0].code == "MANAGEMENT_IP_OVERLAPS_SERVICE_NETWORK"
    assert issues[0].field_path == "hops[2].management_ip"
    assert issues[0].node_id == address


@pytest.mark.parametrize("bandwidth_mbps, expected_count", [(1000, 0), (1001, 1)])
def test_dia_enforces_the_laboratory_port_capacity(
    bandwidth_mbps: int, expected_count: int,
) -> None:
    """Acepta 1000 Mbps y rechaza el primer valor superior a la capacidad."""
    issues = validate_dia_intent_semantics(replace(_dia_intent(), bandwidth_mbps=bandwidth_mbps))
    assert len(issues) == expected_count
    if issues:
        assert issues[0].code == "BANDWIDTH_EXCEEDS_PORT_CAPACITY"
        assert issues[0].field_path == "bandwidth_mbps"


def test_dia_accumulates_semantic_defects_at_every_hop() -> None:
    """Acumula reservas, superposiciones y exceso de capacidad sin abortar."""
    intent = _dia_intent()
    intent = replace(
        intent, vlan_id=1, bandwidth_mbps=1001,
        access=replace(intent.access, management_ip=IPv4Address("198.51.100.1")),
        transits=(replace(intent.transits[0], management_ip=IPv4Address("203.0.113.1")),),
        provider_edge=replace(intent.provider_edge, management_ip=IPv4Address("198.51.100.2")),
    )
    issues = validate_dia_intent_semantics(intent)
    assert [issue.code for issue in issues].count("MANAGEMENT_IP_OVERLAPS_SERVICE_NETWORK") == 3
    assert {issue.code for issue in issues} == {
        "RESERVED_CISCO_VLAN", "MANAGEMENT_IP_OVERLAPS_SERVICE_NETWORK",
        "BANDWIDTH_EXCEEDS_PORT_CAPACITY",
    }
    assert all(issue.stage is ValidationStage.STATIC_OFFLINE for issue in issues)
    assert all(issue.severity is ValidationSeverity.ERROR for issue in issues)


def test_catalog_keeps_semantic_validation_optional_and_isolated() -> None:
    """Conserva servicios sin validador y aisla los registros entre catalogos."""
    catalog = PluginCatalog()
    catalog.register_service(DiaIntentParser(frozenset()))
    intent = _dia_intent()
    assert catalog.validate_semantics(intent) == ()
    calls: list[DiaIntent] = []

    def validate(candidate: DiaIntent) -> list[ValidationIssue]:
        calls.append(candidate)
        return [_issue()]

    catalog.register_service_validator("DIA", validate)
    assert catalog.validate_semantics(intent) == (_issue(),)
    assert calls == [intent]
    assert PluginCatalog().validate_semantics(intent) == ()
    with pytest.raises(PluginRegistrationError, match="validador duplicado"):
        catalog.register_service_validator("DIA", validate)


def test_catalog_requires_a_registered_service_for_its_validator() -> None:
    """Rechaza un validador huerfano de servicio en el catalogo."""
    with pytest.raises(PluginRegistrationError, match="servicio no registrado"):
        PluginCatalog().register_service_validator("DIA", validate_dia_intent_semantics)


def test_bootstrap_registers_the_dia_semantic_rules() -> None:
    """Activa las reglas DIA mediante la raiz de composicion existente."""
    intent = replace(_dia_intent(), vlan_id=0)
    assert build_plugin_catalog().validate_semantics(intent) == validate_dia_intent_semantics(intent)
