"""Aplica planes secuenciales con corte inmediato y evidencia de saltos previos."""

from intentfabric.application.transport import DeviceTransportPort
from intentfabric.domain.deployment import NodeDeploymentResult, ServiceDeploymentReport
from intentfabric.domain.errors import DeploymentError, DeviceTransportError
from intentfabric.domain.generation import ServiceGenerationPlan
from intentfabric.domain.topology import TopologyCatalog


class DeploymentService:
    """Despliega los artefactos en el orden canonico recibido del generador."""

    def __init__(self, topology: TopologyCatalog, transport: DeviceTransportPort) -> None:
        self._topology = topology
        self._transport = transport

    def deploy(self, plan: ServiceGenerationPlan) -> ServiceDeploymentReport:
        """Aplica el plan o lanza DeploymentError con los saltos completados antes del fallo."""
        completed: list[NodeDeploymentResult] = []
        for artifact in plan.artifacts:
            node = self._topology.get_node(artifact.node_id)
            try:
                raw_output, committed = self._transport.push_configuration(node, artifact.commands)
            except DeviceTransportError as error:
                raise DeploymentError(
                    f"{artifact.node_id}: fallo de despliegue en salto {artifact.hop_index}; {error}",
                    node_id=artifact.node_id, hop_index=artifact.hop_index,
                    partial_results=tuple(completed),
                ) from error
            completed.append(NodeDeploymentResult(
                hop_index=artifact.hop_index, node_id=artifact.node_id,
                management_ip=artifact.management_ip, vendor=artifact.vendor, os_family=node.os_family,
                role=artifact.role, operation=artifact.operation, commands=artifact.commands,
                raw_output=raw_output, committed=committed, sha256=artifact.sha256,
            ))
        return ServiceDeploymentReport(
            service_id=plan.service_id, service_type=plan.service_type, operation=plan.operation,
            variant=plan.variant, plan_sha256=plan.plan_sha256, results=tuple(completed),
        )
