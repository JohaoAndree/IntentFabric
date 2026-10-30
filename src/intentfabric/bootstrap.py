"""Raíz de composición: único módulo que nombra implementaciones concretas."""

from collections.abc import Callable, Sequence
from importlib.resources import files
from pathlib import Path
import time
from types import ModuleType
from typing import Any

from intentfabric.adapters.execution_logger import FileExecutionLogger
from intentfabric.adapters.intent_file_loader import load_intent_mapping
from intentfabric.adapters.netmiko_transport import NetmikoTransportAdapter, load_credentials_from_env
from intentfabric.adapters.simulated_transport import SimulatedTransportAdapter
from intentfabric.adapters.packaged_template_source import PackagedTemplateSource
from intentfabric.adapters.jinja_renderer import JinjaTemplateRenderer
from intentfabric.adapters.yaml_topology_repository import YamlTopologyRepository
from intentfabric.application.generation import DeterministicGeneratorService
from intentfabric.application.orchestrator import ExecutionLoggerPort, NoOpExecutionLogger, PipelineOrchestrator
from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.application.pre_validation import PreFlightCheckerPort, PreValidationService
from intentfabric.application.preflight_online import OnlinePreFlightChecker
from intentfabric.application.deployment import DeploymentService
from intentfabric.application.transport import DeviceTransportPort
from intentfabric.application.post_validation import PostValidationTriageService
from intentfabric.application.template_source import TemplateSource
from intentfabric.domain.errors import IntentFabricError
from intentfabric.domain.intent import DiaIntent, L2VpnIntent, L3VpnIntent
from intentfabric.domain.post_validation import ExpectedState, build_expected_state
from intentfabric.domain.topology import TopologyCatalog, TopologyNode
from intentfabric.services.dia.context_builder import build_dia_hop_context
from intentfabric.services.dia.intent_parser import DiaIntentParser
from intentfabric.services.dia.validator import validate_dia_intent_semantics
from intentfabric.services.l2vpn import (
    L2VpnIntentParser, build_l2vpn_hop_context, validate_l2vpn_semantics,
)
from intentfabric.services.l3vpn import (
    L3VpnIntentParser, build_l3vpn_hop_context, validate_l3vpn_semantics,
)
from intentfabric.vendors import cisco, huawei


VENDOR_PACKAGES: tuple[ModuleType, ...] = (cisco, huawei)


def build_template_source() -> PackagedTemplateSource:
    """Construye las raíces de recursos a partir de los paquetes de vendor registrados."""
    return PackagedTemplateSource({
        package.VENDOR_DEFINITION.vendor_id: files(package)
        for package in VENDOR_PACKAGES
    })


def load_default_topology(path: Path | str | None = None) -> TopologyCatalog:
    """Carga el inventario por defecto o la ruta indicada por el consumidor."""
    return YamlTopologyRepository(path if path is not None else Path("inventory/topology.yaml")).load_catalog()


def build_plugin_catalog(topology: TopologyCatalog | None = None) -> PluginCatalog:
    """Registra los vendors y deriva de ellos los vendors conocidos del parser DIA."""
    catalog = PluginCatalog()
    for package in VENDOR_PACKAGES:
        catalog.register_vendor(package.VENDOR_DEFINITION)
    topology = topology if topology is not None else load_default_topology()
    catalog.register_service(DiaIntentParser(known_vendors=catalog.vendor_ids(), topology=topology))
    catalog.register_service_validator(DiaIntentParser.service_type, validate_dia_intent_semantics)
    catalog.register_context_builder(DiaIntentParser.service_type, build_dia_hop_context)
    catalog.register_service(L3VpnIntentParser(known_vendors=catalog.vendor_ids(), topology=topology))
    catalog.register_service_validator(L3VpnIntentParser.service_type, validate_l3vpn_semantics)
    catalog.register_context_builder(L3VpnIntentParser.service_type, build_l3vpn_hop_context)
    catalog.register_service(L2VpnIntentParser(known_vendors=catalog.vendor_ids(), topology=topology))
    catalog.register_service_validator(L2VpnIntentParser.service_type, validate_l2vpn_semantics)
    catalog.register_context_builder(L2VpnIntentParser.service_type, build_l2vpn_hop_context)
    if "cisco" in catalog.vendor_ids():
        catalog.register_vendor_qos_builder("cisco", cisco.build_cisco_qos_context)
    if "huawei" in catalog.vendor_ids():
        catalog.register_vendor_qos_builder("huawei", huawei.build_huawei_qos_context)
    return catalog


def build_verified_catalog() -> PluginCatalog:
    """Construye el catálogo y exige consistencia con los recursos empaquetados."""
    catalog = build_plugin_catalog()
    catalog.assert_consistent(build_template_source())
    return catalog


def build_generator(
    catalog: PluginCatalog | None = None, template_source: TemplateSource | None = None,
    pre_validator: PreValidationService | None = None,
    topology: TopologyCatalog | None = None,
) -> DeterministicGeneratorService:
    """Compone el generador con recursos empaquetados y validacion previa por defecto."""
    if topology is None and (catalog is None or pre_validator is None):
        topology = load_default_topology()
    if catalog is None:
        catalog = build_plugin_catalog(topology)
    if template_source is None:
        template_source = build_template_source()
    if pre_validator is None:
        pre_validator = PreValidationService(catalog, topology=topology)
    return DeterministicGeneratorService(
        catalog, JinjaTemplateRenderer(catalog, template_source), pre_validator,
    )


def build_online_preflight_checker(
    topology: TopologyCatalog | None = None, *, transport: DeviceTransportPort,
) -> OnlinePreFlightChecker:
    """Compone el verificador online con el inventario indicado o por defecto."""
    return OnlinePreFlightChecker(topology if topology is not None else load_default_topology(), transport)


def build_pre_validator(
    catalog: PluginCatalog | None = None, *, topology: TopologyCatalog | None = None,
    preflight_checker: PreFlightCheckerPort | None = None,
) -> PreValidationService:
    """Compone validacion estatica y el verificador online opcional."""
    topology = topology if topology is not None else load_default_topology()
    catalog = catalog if catalog is not None else build_plugin_catalog(topology)
    return PreValidationService(catalog, topology=topology, preflight_checker=preflight_checker)


def build_deployment_service(
    topology: TopologyCatalog | None = None, *, transport: DeviceTransportPort,
) -> DeploymentService:
    """Compone despliegue secuencial con inventario y transporte inyectable."""
    return DeploymentService(topology if topology is not None else load_default_topology(), transport)


def build_post_validator(
    topology: TopologyCatalog | None = None, *, transport: DeviceTransportPort,
) -> PostValidationTriageService:
    """Compone el triage posdespliegue con inventario y transporte inyectable."""
    return PostValidationTriageService(topology if topology is not None else load_default_topology(), transport)


def load_intent_file(path: Path | str) -> dict[str, Any]:
    """Carga una intencion JSON o YAML sin exponer el adaptador al consumidor."""
    return load_intent_mapping(Path(path))


def build_execution_logger(
    *, json_path: Path | str | None = None, csv_path: Path | str | None = None,
) -> ExecutionLoggerPort:
    """Compone persistencia JSON/CSV solo cuando se solicita algun destino."""
    if json_path is not None or csv_path is not None:
        return FileExecutionLogger(json_path=json_path, csv_path=csv_path)
    return NoOpExecutionLogger()


def build_ssh_transport() -> NetmikoTransportAdapter:
    """Compone SSH con credenciales obtenidas exclusivamente del entorno."""
    return NetmikoTransportAdapter(load_credentials_from_env())


def build_orchestrator(
    *, topology: TopologyCatalog | None = None, catalog: PluginCatalog | None = None,
    transport: DeviceTransportPort | None = None, enable_online_preflight: bool = True,
    logger: ExecutionLoggerPort | None = None, clock: Callable[[], float] = time.perf_counter,
) -> PipelineOrchestrator:
    """Conecta las fases al mismo inventario, catalogo y transporte opcional."""
    topology = topology if topology is not None else load_default_topology()
    catalog = catalog if catalog is not None else build_plugin_catalog(topology)
    checker = (build_online_preflight_checker(topology, transport=transport)
               if transport is not None and enable_online_preflight else None)
    pre_validator = build_pre_validator(catalog, topology=topology, preflight_checker=checker)
    return PipelineOrchestrator(
        catalog, pre_validator, build_generator(catalog, topology=topology),
        deployment_service=build_deployment_service(topology, transport=transport) if transport is not None else None,
        post_validator=build_post_validator(topology, transport=transport) if transport is not None else None,
        logger=logger, clock=clock,
    )


class _IntentSimulatedTransport(SimulatedTransportAdapter):
    """Alterna respuestas de laboratorio limpias y operativas segun el ciclo."""

    def __init__(
        self, clean_outputs: dict[tuple[str, str], str],
        operational_outputs: dict[tuple[str, str], str], pe_query: tuple[str, str],
    ) -> None:
        super().__init__(clean_outputs)
        self._operational_outputs = operational_outputs
        self._pe_query = pe_query

    def execute_show(self, node: TopologyNode, command: str) -> str:
        """Inicia una auditoria directa con estado operativo si no hubo Pre-Flight."""
        if not self.history and (node.node_id, command.strip()) == self._pe_query:
            self._activate_operational_outputs()
        return super().execute_show(node, command)

    def push_configuration(self, node: TopologyNode, commands: Sequence[str]) -> tuple[str, bool]:
        """Activa evidencia operativa tras aplicar una configuracion simulada."""
        result = super().push_configuration(node, commands)
        self._activate_operational_outputs()
        return result

    def _activate_operational_outputs(self) -> None:
        for (node_id, command), output in self._operational_outputs.items():
            self.set_show_output(node_id, command, output)


def build_simulated_transport_for_intent(
    intent: DiaIntent | L3VpnIntent | L2VpnIntent, *, topology: TopologyCatalog | None = None,
    variant: str = "default",
) -> SimulatedTransportAdapter:
    """Compone respuestas parametrizadas de laboratorio para todas las fases.

    Sintaxis de VLAN, interfaces, LLDP, MAC, ping, rutas y circuitos tomada de
    tests/fixtures/preflight/ y tests/fixtures/post_validation/. No requiere
    leer fixtures durante la ejecucion ni utilizar equipos externos.
    Las derivaciones operativas invalidas se omiten para que Fase 1A emita
    el rechazo taxonomico antes de ejecutar cualquier consulta de transporte.
    """
    topology = topology if topology is not None else load_default_topology()
    clean_outputs = _simulated_clean_outputs(intent, topology)
    try:
        expected = build_expected_state(intent, variant=variant)
    except (IntentFabricError, ValueError):
        expected = None
    operational_outputs = (
        _simulated_operational_outputs(intent, topology, expected)
        if expected is not None and all(topology.find_node(hop.node_id) is not None for hop in intent.hops)
        else {}
    )
    pe = intent.provider_edge
    interface_command = "show ip interface brief" if pe.vendor == "cisco" else "display interface brief"
    return _IntentSimulatedTransport(clean_outputs, operational_outputs, (pe.node_id, interface_command))


def _simulated_clean_outputs(
    intent: DiaIntent | L3VpnIntent | L2VpnIntent, topology: TopologyCatalog,
) -> dict[tuple[str, str], str]:
    clean_outputs: dict[tuple[str, str], str] = {}
    l2_node_ids = (intent.access.node_id, *(hop.node_id for hop in intent.transits))
    for hop in intent.hops:
        node = topology.find_node(hop.node_id)
        if node is None:
            continue
        cisco = node.vendor == "cisco"
        if node.node_id in l2_node_ids:
            vlan_command = "show vlan brief" if cisco else "display vlan"
            clean_outputs[node.node_id, vlan_command] = (
                "1 default active Gi1/0/1\n" if cisco else "1 common UT:GE0/0/1(U)\n"
            )
        if node.node_id == intent.access.node_id:
            access = intent.access
            if cisco:
                clean_outputs[node.node_id, f"show interfaces {access.customer_port} switchport"] = (
                    f"Name: {access.customer_port}\nSwitchport: Enabled\nAdministrative Mode: static access\n"
                    "Operational Mode: static access\nAccess Mode VLAN: 1 (default)\n"
                )
            else:
                clean_outputs[node.node_id, f"display port vlan {access.customer_port}"] = (
                    f"{access.customer_port} access 1 -\n"
                )
        if node.node_id == intent.provider_edge.node_id:
            pe = intent.provider_edge
            interface_command = "show ip interface brief" if cisco else "display interface brief"
            clean_outputs[node.node_id, interface_command] = (
                f"{pe.parent_interface} unassigned YES NVRAM administratively down down\n" if cisco
                else f"{pe.parent_interface} down down 0% 0% 0 0\n"
            )
            if isinstance(intent, DiaIntent):
                vrf_command = "show vrf" if cisco else "display ip vpn-instance"
                clean_outputs[node.node_id, vrf_command] = f"{intent.vrf_name} 65000:1 ipv4\n"
            elif isinstance(intent, L3VpnIntent):
                bgp_command = "show bgp all summary" if cisco else "display bgp peer"
                clean_outputs[node.node_id, bgp_command] = (
                    f"BGP router identifier 192.0.2.1, local AS number {intent.pe_asn}\n" if cisco
                    else f"BGP local router ID : 192.0.2.2\nLocal AS number : {intent.pe_asn}\n"
                )
    return clean_outputs


def _simulated_operational_outputs(
    intent: DiaIntent | L3VpnIntent | L2VpnIntent, topology: TopologyCatalog, expected: ExpectedState,
) -> dict[tuple[str, str], str]:
    operational_outputs: dict[tuple[str, str], str] = {}
    for hop in intent.hops:
        node = topology.get_node(hop.node_id)
        cisco = node.vendor == "cisco"
        ports = [port for node_id, port in expected.expected_lldp_ports if node_id == node.node_id]
        lldp_command = "show lldp neighbors" if cisco else "display lldp neighbor brief"
        operational_outputs[node.node_id, lldp_command] = "".join(
            f"SW-LAB {port} 150 R Gi1/0/24\n" if cisco else f"{port} SW-LAB GE1/0/10 111\n"
            for port in ports
        )
        if node.node_id in expected.l2_node_ids:
            vlan_command = "show vlan brief" if cisco else "display vlan"
            vlan_row = "{vlan} default active Gi1/0/1\n" if cisco else "{vlan} common UT:GE0/0/1(U)\n"
            operational_outputs[node.node_id, vlan_command] = vlan_row.format(vlan=intent.vlan_id)
            mac_command = (f"show mac address-table vlan {intent.vlan_id}" if cisco
                           else f"display mac-address vlan {intent.vlan_id}")
            operational_outputs[node.node_id, mac_command] = (
                f"{intent.vlan_id} 0200.0000.0001 DYNAMIC {ports[0]}\n" if cisco
                else f"0200-0000-0001 {intent.vlan_id}/- {ports[0]} dynamic\n"
            )
    access = intent.access
    pe = intent.provider_edge
    cisco = pe.vendor == "cisco"
    interface_command = "show ip interface brief" if cisco else "display interface brief"
    operational_outputs[pe.node_id, interface_command] = (
        f"{expected.pe_subinterface} {expected.ping_target_ip or '192.0.2.1'} YES manual up up\n" if cisco
        else f"{expected.pe_subinterface} up up(s) 0% 0% 0 0\n"
    )
    if isinstance(intent, L2VpnIntent):
        operational_outputs.update(_simulated_circuit_outputs(intent, expected.variant))
    else:
        operational_outputs[access.node_id, f"ping {expected.ping_target_ip}"] = (
            "!!!!!\nSuccess rate is 100 percent (5/5), round-trip min/avg/max = 1/2/4 ms\n"
            if access.vendor == "cisco" else
            "5 packet(s) transmitted\n5 packet(s) received\n0.00% packet loss\n"
        )
        if isinstance(intent, DiaIntent):
            route_command = (f"show ip route vrf {intent.vrf_name}" if cisco
                             else f"display ip routing-table vpn-instance {intent.vrf_name}")
            route_output = (f"S {intent.lan_network} [1/0] via {expected.svi_ip_address}\n" if cisco
                            else f"{intent.lan_network} Static 60 0 RD {expected.svi_ip_address} {expected.pe_subinterface}\n")
        else:
            route_command = (f"show bgp vpnv4 unicast vrf {intent.vrf_name}" if cisco
                             else f"display bgp vpnv4 vpn-instance {intent.vrf_name} routing-table")
            route_output = (f"*> {intent.wan_network} 0.0.0.0 0 32768 ?\n" if cisco
                            else f"*> {intent.wan_network} 0.0.0.0 0 0 ?\n")
            peer_command = (f"show bgp vpnv4 unicast vrf {intent.vrf_name} summary" if cisco
                            else f"display bgp vpnv4 vpn-instance {intent.vrf_name} peer")
            operational_outputs[pe.node_id, peer_command] = _simulated_peer_output(
                intent, expected.bgp_neighbor_ip,
            )
        operational_outputs[pe.node_id, route_command] = route_output
    return operational_outputs


def _simulated_circuit_outputs(intent: L2VpnIntent, variant: str) -> dict[tuple[str, str], str]:
    pe = intent.provider_edge
    if variant == "martini_ldp":
        command = (f"show mpls l2transport vc {intent.pw_id}" if pe.vendor == "cisco"
                   else f"display mpls l2vc {intent.pw_id}")
        output = (
            f"{pe.parent_interface}.{intent.vlan_id} Eth VLAN {intent.vlan_id} {intent.remote_pe_ip} {intent.pw_id} UP\n"
            if pe.vendor == "cisco" else
            f"*client interface : {pe.parent_interface}.{intent.vlan_id}\nsession state : up\nVC state : up\nVC ID : {intent.pw_id}\n"
        )
    else:
        command = ("show l2vpn evpn vpws" if pe.vendor == "cisco"
                   else f"display bgp evpn evpl instance-id {intent.evi_id}")
        output = (
            f"EVPN instance: {intent.evi_id} (point-to-point)\nTotal VCs: 1\n"
            "1 up, 0 down, 0 admin-down, 0 hot-standby, 0 other\n"
            if pe.vendor == "cisco" else
            f"EVPL instance ID : {intent.evi_id}\nVPN-Instance : {intent.instance_name}\n"
            f"Interface name : {pe.parent_interface}.{intent.vlan_id}\nEvpl State : up\n"
            f"Local service ID : {intent.local_ac_id}\nRemote service ID : {intent.remote_ac_id}\n"
        )
    return {(pe.node_id, command): output}


def _simulated_peer_output(intent: L3VpnIntent, neighbor_ip: str | None) -> str:
    """Parametriza filas de resumen BGP documentadas por ambos fabricantes.

    Cisco IOS XE 17.x:
    https://www.cisco.com/c/en/us/td/docs/routers/ios/config/17-x/mpls/b-mpls/m_mp-carrier-bgp.html
    Huawei:
    https://info.support.huawei.com/network/ptmngsys/Web/tsrev_ne/en/content/ne/24_edesk_ne_bgp_routing_oscillation_failure/edesk_ne_bgp_routing_oscillation_failure_edesk003.html
    """
    if intent.provider_edge.vendor == "cisco":
        return f"{neighbor_ip} 4 {intent.ce_asn} 0 0 1 0 0 00:20:09 0\n"
    return f"{neighbor_ip} 4 {intent.ce_asn} 104931 104925 0 0242h14m Established 62\n"


create_default_catalog = build_plugin_catalog
create_default_generator = build_generator
