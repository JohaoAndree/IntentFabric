"""Verifica colisiones y precondiciones Day-0 mediante consultas de solo lectura."""

import re
from typing import Any

from intentfabric.application.transport import DeviceTransportPort
from intentfabric.domain.derivations import derive_subinterface_name
from intentfabric.domain.errors import InvalidInterfaceNameError
from intentfabric.domain.interfaces import are_equivalent_interfaces, normalize_interface_name
from intentfabric.domain.intent import AccessHop, ProviderEdgeHop, TransitHop
from intentfabric.domain.topology import TopologyCatalog, TopologyNode
from intentfabric.domain.validation import ValidationIssue, ValidationStage


def parse_active_vlans(output: str, vendor: str) -> frozenset[int]:
    """Extrae IDs VLAN de filas de tabla o listados activos de Huawei."""
    vlans: set[int] = set()
    pattern = r"^(\d+)\s+\S+" if vendor == "cisco" else r"^(\d+)\s+(?:common|mux|super)\b"
    for raw_line in output.splitlines():
        line = raw_line.strip()
        match = re.match(pattern, line)
        if match is not None:
            vlan = int(match.group(1))
            if 1 <= vlan <= 4094:
                vlans.add(vlan)
        elif vendor == "huawei" and re.fullmatch(r"\d+(?:\s+\d+)*", line):
            vlans.update(int(token) for token in line.split() if 1 <= int(token) <= 4094)
    return frozenset(vlans)


def parse_access_port_vlan(output: str, vendor: str, interface_name: str) -> int | None:
    """Extrae la VLAN o el PVID solo si la interfaz solicitada esta en modo access."""
    if vendor == "cisco":
        names = re.findall(r"^[ \t]*Name:[ \t]*(.*)$", output, re.MULTILINE)
        try:
            if any(not are_equivalent_interfaces(name.strip(), interface_name, vendor=vendor)
                   for name in names):
                return None
        except InvalidInterfaceNameError:
            return None
        switchport_states = re.findall(r"^[ \t]*Switchport:[ \t]*(.*)$", output, re.MULTILINE)
        if any(state.strip().lower() != "enabled" for state in switchport_states):
            return None
        modes = re.findall(
            r"^[ \t]*(?:Administrative Mode|Operational Mode):[ \t]*(.*)$", output, re.MULTILINE,
        )
        if not modes or any(mode.strip().lower() not in ("static access", "access") for mode in modes):
            return None
        match = re.search(r"Access Mode VLAN:\s*(\d+)", output)
        return int(match.group(1)) if match is not None else None
    for line in output.splitlines():
        columns = line.split()
        if len(columns) < 3 or not columns[2].isdecimal():
            continue
        try:
            matches = are_equivalent_interfaces(columns[0], interface_name, vendor=vendor)
        except InvalidInterfaceNameError:
            continue
        if matches:
            return int(columns[2]) if columns[1].lower() == "access" else None
    return None


def parse_existing_interfaces(output: str, vendor: str) -> frozenset[str]:
    """Normaliza el primer token valido de cada fila de interfaces."""
    interfaces: set[str] = set()
    for line in output.splitlines():
        columns = line.split()
        if not columns:
            continue
        try:
            interface = normalize_interface_name(columns[0], vendor=vendor)
        except InvalidInterfaceNameError:
            continue
        interfaces.add(interface)
    return frozenset(interfaces)


def parse_existing_vrfs(output: str, vendor: str) -> frozenset[str]:
    """Extrae nombres de las filas VRF con RD o identificador de instancia."""
    names: set[str] = set()
    for line in output.splitlines():
        columns = line.split()
        if len(columns) < 2 or columns[0] in ("Name", "VPN-Instance", "Total"):
            continue
        if re.fullmatch(r"(?:\d+(?:\.\d+){0,3}:\d+(?:\(auto\))?|\d+|<not|--|-)", columns[1]):
            names.add(columns[0])
    return frozenset(names)


def parse_local_bgp_asn(output: str, vendor: str) -> int | None:
    """Extrae el ASN del proceso BGP local segun la sintaxis del fabricante."""
    pattern = r"local AS number\s+(\d+)" if vendor == "cisco" else r"Local AS number\s*:\s*(\d+)"
    match = re.search(pattern, output)
    return int(match.group(1)) if match is not None else None


def _issue(code: str, message: str, field_path: str, node_id: str) -> ValidationIssue:
    return ValidationIssue(
        code=code, message=message, stage=ValidationStage.PREFLIGHT_ONLINE,
        field_path=field_path, node_id=node_id,
    )


class OnlinePreFlightChecker:
    """Recorre la ruta y acumula colisiones y precondiciones por salto."""

    def __init__(self, topology: TopologyCatalog, transport: DeviceTransportPort) -> None:
        self._topology = topology
        self._transport = transport

    def check_preflight(self, intent: Any) -> tuple[ValidationIssue, ...]:
        """Devuelve hallazgos online en orden de saltos y verificaciones prescritas."""
        issues: list[ValidationIssue] = []
        for index, hop in enumerate(intent.hops):
            node = self._topology.get_node(hop.node_id)
            if isinstance(hop, (AccessHop, TransitHop)):
                issues.extend(self._check_layer2(intent, hop, node))
            if isinstance(hop, ProviderEdgeHop):
                issues.extend(self._check_provider_edge(intent, hop, node))
        return tuple(issues)

    def _check_layer2(
        self, intent: Any, hop: AccessHop | TransitHop, node: TopologyNode,
    ) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        command = "show vlan brief" if node.vendor == "cisco" else "display vlan"
        output = self._transport.execute_show(node, command)
        if intent.vlan_id in parse_active_vlans(output, node.vendor):
            issues.append(_issue(
                "VLAN_COLLISION", f"vlan_id: la VLAN {intent.vlan_id} ya existe en {node.node_id}.",
                "vlan_id", node.node_id,
            ))
        if isinstance(hop, AccessHop):
            command = (f"show interfaces {hop.customer_port} switchport" if node.vendor == "cisco"
                       else f"display port vlan {hop.customer_port}")
            output = self._transport.execute_show(node, command)
            pvid = parse_access_port_vlan(output, node.vendor, hop.customer_port)
            if pvid is None:
                issues.append(_issue(
                    "CLIENT_PORT_BUSY",
                    f"customer_port: el puerto {hop.customer_port} no se encuentra en modo access libre en {node.node_id}.",
                    "hops[0].customer_port", node.node_id,
                ))
            elif pvid != 1:
                issues.append(_issue(
                    "CLIENT_PORT_BUSY",
                    f"customer_port: el puerto {hop.customer_port} ya pertenece a la VLAN {pvid} en {node.node_id}.",
                    "hops[0].customer_port", node.node_id,
                ))
        return tuple(issues)

    def _check_provider_edge(
        self, intent: Any, hop: ProviderEdgeHop, node: TopologyNode,
    ) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        expected_subif = normalize_interface_name(
            derive_subinterface_name(hop.parent_interface, intent.vlan_id), vendor=node.vendor,
        )
        command = "show ip interface brief" if node.vendor == "cisco" else "display interface brief"
        output = self._transport.execute_show(node, command)
        if expected_subif in parse_existing_interfaces(output, node.vendor):
            issues.append(_issue(
                "SUBINTERFACE_ALREADY_EXISTS",
                f"vlan_id: la subinterfaz {expected_subif} ya existe en {node.node_id}.",
                "vlan_id", node.node_id,
            ))
        if intent.service_type == "DIA":
            command = "show vrf" if node.vendor == "cisco" else "display ip vpn-instance"
            output = self._transport.execute_show(node, command)
            if intent.vrf_name not in parse_existing_vrfs(output, node.vendor):
                issues.append(_issue(
                    "MISSING_BASE_VRF",
                    f"vrf_name: la VRF base {intent.vrf_name!r} no existe en {node.node_id}.",
                    "vrf_name", node.node_id,
                ))
        if intent.service_type == "L3VPN":
            command = "show bgp all summary" if node.vendor == "cisco" else "display bgp peer"
            output = self._transport.execute_show(node, command)
            if parse_local_bgp_asn(output, node.vendor) != intent.pe_asn:
                issues.append(_issue(
                    "BGP_PROCESS_NOT_RUNNING",
                    f"pe_asn: BGP con ASN {intent.pe_asn} no esta activo en {node.node_id}.",
                    "pe_asn", node.node_id,
                ))
        return tuple(issues)
