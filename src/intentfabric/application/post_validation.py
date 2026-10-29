"""Evalua evidencias CLI y ejecuta el triage posdespliegue en orden fijo."""

import re
from ipaddress import IPv4Network

from intentfabric.application.preflight_online import parse_active_vlans
from intentfabric.application.transport import DeviceTransportPort
from intentfabric.domain.errors import (
    DeviceTransportError, EphemeralProbeCleanupError, InvalidInterfaceNameError,
    PostValidationFailedError,
)
from intentfabric.domain.intent import DiaIntent, L2VpnIntent, L3VpnIntent
from intentfabric.domain.interfaces import are_equivalent_interfaces, normalize_interface_name
from intentfabric.domain.post_validation import (
    ExpectedState, ObservedState, PostValidationReport, ServiceOperationalStatus,
    TriageStepName, TriageStepResult, build_expected_state,
    build_ephemeral_svi_provision_commands, build_ephemeral_svi_teardown_commands,
)
from intentfabric.domain.topology import TopologyCatalog, TopologyNode


def parse_interface_is_up(output: str, vendor: str, interface_name: str) -> bool:
    """Comprueba estado fisico y protocolo solo en la interfaz solicitada."""
    for line in output.splitlines():
        columns = line.split()
        if len(columns) < 3:
            continue
        try:
            matches = are_equivalent_interfaces(columns[0], interface_name, vendor=vendor)
        except InvalidInterfaceNameError:
            continue
        if matches:
            if vendor == "cisco":
                return columns[-2].lower() == "up" and columns[-1].lower() == "up"
            return columns[1].lower().startswith("up") and columns[2].lower().startswith("up")
    return False


def parse_lldp_local_ports(output: str, vendor: str) -> frozenset[str]:
    """Extrae puertos locales canonicos de filas de vecinos LLDP."""
    ports: set[str] = set()
    for line in output.splitlines():
        columns = line.split()
        if vendor == "cisco":
            if len(columns) < 5 or not columns[2].isdecimal():
                continue
            candidate = columns[1]
        else:
            if len(columns) < 4 or not (columns[1].isdecimal() or columns[-1].isdecimal()):
                continue
            candidate = columns[0]
        try:
            port = normalize_interface_name(candidate, vendor=vendor)
        except InvalidInterfaceNameError:
            continue
        ports.add(port)
    return frozenset(ports)


def parse_vlan_mac_count(output: str, vendor: str, vlan_id: int) -> int:
    """Cuenta entradas MAC de la VLAN exacta sin confundir IDs de puertos."""
    count = 0
    for line in output.splitlines():
        columns = line.split()
        if len(columns) < 2:
            continue
        if vendor == "cisco":
            matches = columns[0] == str(vlan_id) and re.fullmatch(
                r"[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}", columns[1], re.I,
            ) is not None
        else:
            matches = columns[1].split("/")[0] == str(vlan_id) and re.fullmatch(
                r"[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}", columns[0], re.I,
            ) is not None
        count += int(matches)
    return count


def parse_ping_success(output: str, vendor: str) -> bool:
    """Acepta al menos una respuesta ICMP segun el resumen del fabricante."""
    if vendor == "cisco":
        match = re.search(r"Success rate is (\d+) percent", output)
        if match is not None:
            return int(match.group(1)) > 0
        return any(re.fullmatch(r"[!.UQMI?&]+", line.strip()) and "!" in line
                   for line in output.splitlines())
    match = re.search(r"(\d+)\s+packet\(s\)\s+received", output)
    return match is not None and int(match.group(1)) > 0


def parse_vrf_route_present(output: str, vendor: str, prefix: str) -> bool:
    """Busca un prefijo exacto en filas de rutas, excluyendo ecos y agregados."""
    expected = IPv4Network(prefix, strict=False)
    for line in output.splitlines():
        match = re.match(
            r"^\s*(?:(?:[A-Z*+?>&%=-]+|[A-Z]{1,2}[12])\s*){0,3}"
            r"(\d+(?:\.\d+){3}/\d{1,2})\s+(.+)$",
            line, re.I,
        )
        if match is None or re.match(r"is (?:variably )?subnetted\b", match.group(2)):
            continue
        try:
            route = IPv4Network(match.group(1), strict=False)
        except ValueError:
            continue
        if route == expected:
            return True
    return False


def parse_bgp_neighbor_state(output: str, vendor: str, neighbor_ip: str) -> str | None:
    """Extrae el estado del peer exacto sin confundir direcciones parciales."""
    states = ("Established", "Active", "Idle", "Connect", "OpenSent", "OpenConfirm")
    for line in output.splitlines():
        columns = line.split()
        if neighbor_ip not in columns or len(columns) < 2:
            continue
        if vendor == "cisco":
            return "Established" if columns[-1].isdecimal() else columns[-1]
        for state in states:
            if state in columns:
                return state
    return None


def parse_l2vpn_circuit_up(
    output: str, vendor: str, variant: str, *, pw_id: int, evi_id: int,
) -> bool:
    """Comprueba el circuito solicitado sin heredar estados de otras instancias."""
    if variant in ("default", "evpn_vpws"):
        if vendor == "cisco":
            for line in output.splitlines():
                columns = line.split()
                if len(columns) >= 2 and columns[0] == str(evi_id) and columns[-1].lower() == "up":
                    return True
            blocks = re.split(r"(?=EVPN instance\s*:)", output, flags=re.I)
            return any(re.search(rf"^EVPN instance\s*:\s*{evi_id}\b", block, re.I)
                       and re.search(r"\b[1-9]\d* up,\s*0 down", block, re.I)
                       for block in blocks)
        return _parse_identified_up_block(
            output, r"(?:EVPL\s+(?:instance|ID)|instance)", evi_id, r"(?:Evpl\s+)?State",
        )
    if variant == "martini_ldp":
        if vendor == "cisco":
            return any(len(columns := line.split()) >= 3
                       and columns[-2] == str(pw_id) and columns[-1].lower() == "up"
                       for line in output.splitlines())
        return _parse_identified_up_block(
            output, r"VC ID", pw_id, r"(?:session state|VC state)",
        )
    return False


def _parse_identified_up_block(output: str, label: str, identifier: int, state_label: str) -> bool:
    sections = re.split(r"(?=^\s*\*?client interface\s*:)", output, flags=re.I | re.M)
    if len(sections) == 1:
        sections = re.split(rf"(?=^\s*{label}\s*:)", output, flags=re.I | re.M)
    for section in sections:
        if re.search(rf"^\s*{label}\s*:\s*{identifier}\b", section, re.I | re.M):
            states = re.findall(rf"^\s*{state_label}\s*:\s*(\S+)", section, re.I | re.M)
            return bool(states) and all(state.lower() == "up" for state in states)
    return False


class PostValidationTriageService:
    """Recorre los cuatro eslabones y atribuye el primer fallo del servicio."""

    def __init__(self, topology: TopologyCatalog, transport: DeviceTransportPort) -> None:
        self._topology = topology
        self._transport = transport

    def validate(
        self, intent: DiaIntent | L3VpnIntent | L2VpnIntent, *, variant: str = "default",
    ) -> PostValidationReport:
        """Valida el servicio y garantiza limpieza tras las consultas de la sonda."""
        expected = build_expected_state(intent, variant=variant)
        pe_node = self._topology.get_node(expected.pe_node_id)
        interface_command = "show ip interface brief" if pe_node.vendor == "cisco" else "display interface brief"
        pe_up = parse_interface_is_up(
            self._transport.execute_show(pe_node, interface_command),
            pe_node.vendor, expected.pe_subinterface,
        )
        interface_step = TriageStepResult(
            TriageStepName.PE_INTERFACE_STATE, pe_up, pe_node.node_id,
            f"{expected.pe_subinterface}: up/up={pe_up}", (interface_command,),
        )
        lldp_step, ports_up = self._check_lldp(expected)
        if expected.requires_svi_probe:
            access_node = self._topology.get_node(expected.access_node_id)
            assert expected.svi_ip_address is not None and expected.svi_netmask is not None
            provision = build_ephemeral_svi_provision_commands(
                access_node.vendor, intent.vlan_id, expected.svi_ip_address, expected.svi_netmask,
            )
            self._transport.push_configuration(access_node, provision)
            ping_command = f"ping {expected.ping_target_ip}"
            try:
                ping_success = parse_ping_success(
                    self._transport.execute_show(access_node, ping_command), access_node.vendor,
                )
                vlan_step, active_nodes, mac_nodes = self._check_layer2(expected)
            finally:
                try:
                    self._transport.push_configuration(
                        access_node,
                        build_ephemeral_svi_teardown_commands(access_node.vendor, intent.vlan_id),
                    )
                except DeviceTransportError as error:
                    raise EphemeralProbeCleanupError(
                        f"{access_node.node_id}: fallo al eliminar la SVI efimera de la VLAN {intent.vlan_id}; {error}",
                        node_id=access_node.node_id, vlan_id=intent.vlan_id,
                    ) from error
                cleaned_up = True
        else:
            ping_success = None
            cleaned_up = True
            vlan_step, active_nodes, mac_nodes = self._check_layer2(expected)
        control_step, control_up, ebgp_state = self._check_control_plane(intent, expected, ping_success)
        steps = (interface_step, lldp_step, vlan_step, control_step)
        first_failed = next((step for step in steps if not step.passed), None)
        if first_failed is not None:
            status = ServiceOperationalStatus.FAILED
        elif isinstance(intent, L3VpnIntent) and ebgp_state != "Established":
            status = ServiceOperationalStatus.READY_FOR_SERVICE
        else:
            status = ServiceOperationalStatus.OPERATIONAL
        return PostValidationReport(
            service_id=expected.service_id, service_type=expected.service_type, variant=variant,
            status=status, sdc=int(first_failed is None), expected_state=expected,
            observed_state=ObservedState(
                pe_up, ports_up, active_nodes, mac_nodes, ping_success, cleaned_up, control_up, ebgp_state,
            ),
            steps=steps, root_cause_step=first_failed.step if first_failed else None,
            root_cause_node_id=first_failed.node_id if first_failed else None,
        )

    def require_compliant(self, report: PostValidationReport) -> PostValidationReport:
        """Rechaza un reporte no conforme conservando toda su evidencia."""
        if not report.is_compliant:
            raise PostValidationFailedError(report)
        return report

    def validate_and_require(
        self, intent: DiaIntent | L3VpnIntent | L2VpnIntent, *, variant: str = "default",
    ) -> PostValidationReport:
        """Valida y exige conformidad en una misma operacion."""
        return self.require_compliant(self.validate(intent, variant=variant))

    def _check_lldp(self, expected: ExpectedState) -> tuple[TriageStepResult, tuple[tuple[str, str], ...]]:
        observed: list[tuple[str, str]] = []
        commands: list[str] = []
        first_missing_node: str | None = None
        for node_id in dict.fromkeys(node_id for node_id, _ in expected.expected_lldp_ports):
            node = self._topology.get_node(node_id)
            command = "show lldp neighbors" if node.vendor == "cisco" else "display lldp neighbor brief"
            ports = parse_lldp_local_ports(self._transport.execute_show(node, command), node.vendor)
            commands.append(command)
            for candidate_node, port in expected.expected_lldp_ports:
                if candidate_node != node_id:
                    continue
                if port in ports:
                    observed.append((node_id, port))
                elif first_missing_node is None:
                    first_missing_node = node_id
        return TriageStepResult(
            TriageStepName.LLDP_CONTINUITY, first_missing_node is None,
            first_missing_node or expected.access_node_id,
            f"Puertos LLDP activos: {tuple(observed)!r}; esperados: {expected.expected_lldp_ports!r}",
            tuple(commands),
        ), tuple(observed)

    def _check_layer2(
        self, expected: ExpectedState,
    ) -> tuple[TriageStepResult, tuple[str, ...], tuple[str, ...]]:
        active_nodes: list[str] = []
        mac_nodes: list[str] = []
        commands: list[str] = []
        first_failed_node: str | None = None
        for node_id in expected.l2_node_ids:
            node = self._topology.get_node(node_id)
            vlan_command = "show vlan brief" if node.vendor == "cisco" else "display vlan"
            mac_command = (f"show mac address-table vlan {expected.vlan_id}" if node.vendor == "cisco"
                           else f"display mac-address vlan {expected.vlan_id}")
            active = expected.vlan_id in parse_active_vlans(
                self._transport.execute_show(node, vlan_command), node.vendor,
            )
            learned = parse_vlan_mac_count(
                self._transport.execute_show(node, mac_command), node.vendor, expected.vlan_id,
            ) > 0
            commands.extend((vlan_command, mac_command))
            if active:
                active_nodes.append(node_id)
            if learned:
                mac_nodes.append(node_id)
            if first_failed_node is None and (not active or (
                expected.requires_svi_probe and node_id == expected.access_node_id and not learned
            )):
                first_failed_node = node_id
        return TriageStepResult(
            TriageStepName.L2_VLAN_AND_MAC, first_failed_node is None,
            first_failed_node or expected.access_node_id,
            f"VLAN {expected.vlan_id} activa en {tuple(active_nodes)!r}; MAC en {tuple(mac_nodes)!r}",
            tuple(commands),
        ), tuple(active_nodes), tuple(mac_nodes)

    def _check_control_plane(
        self, intent: DiaIntent | L3VpnIntent | L2VpnIntent, expected: ExpectedState,
        ping_success: bool | None,
    ) -> tuple[TriageStepResult, bool, str | None]:
        node = self._topology.get_node(expected.pe_node_id)
        ebgp_state = None
        if isinstance(intent, L2VpnIntent):
            command = self._l2vpn_command(node, intent, expected.variant)
            control_up = parse_l2vpn_circuit_up(
                self._transport.execute_show(node, command), node.vendor, expected.variant,
                pw_id=intent.pw_id, evi_id=intent.evi_id,
            )
            passed = control_up
            commands = (command,)
        else:
            if isinstance(intent, DiaIntent):
                command = (f"show ip route vrf {intent.vrf_name}" if node.vendor == "cisco"
                           else f"display ip routing-table vpn-instance {intent.vrf_name}")
            else:
                command = (f"show bgp vpnv4 unicast vrf {intent.vrf_name}" if node.vendor == "cisco"
                           else f"display bgp vpnv4 vpn-instance {intent.vrf_name} routing-table")
            assert expected.expected_route_prefix is not None
            control_up = parse_vrf_route_present(
                self._transport.execute_show(node, command), node.vendor, expected.expected_route_prefix,
            )
            commands = (f"ping {expected.ping_target_ip}", command)
            passed = bool(ping_success and control_up)
            if isinstance(intent, L3VpnIntent):
                peer_command = (f"show bgp vpnv4 unicast vrf {intent.vrf_name} summary" if node.vendor == "cisco"
                                else f"display bgp vpnv4 vpn-instance {intent.vrf_name} peer")
                assert expected.bgp_neighbor_ip is not None
                ebgp_state = parse_bgp_neighbor_state(
                    self._transport.execute_show(node, peer_command), node.vendor, expected.bgp_neighbor_ip,
                )
                commands += (peer_command,)
                passed = passed and ebgp_state is not None
        return TriageStepResult(
            TriageStepName.SERVICE_CONTROL_AND_DATA_PLANE, passed, node.node_id,
            f"Control={control_up}; ping={ping_success}; eBGP={ebgp_state}", commands,
        ), control_up, ebgp_state

    @staticmethod
    def _l2vpn_command(node: TopologyNode, intent: L2VpnIntent, variant: str) -> str:
        if variant == "martini_ldp":
            return (f"show mpls l2transport vc {intent.pw_id}" if node.vendor == "cisco"
                    else f"display mpls l2vc {intent.pw_id}")
        return ("show l2vpn evpn vpws" if node.vendor == "cisco"
                else f"display evpl instance {intent.evi_id}")
