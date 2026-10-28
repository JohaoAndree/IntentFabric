"""Orquestacion determinista de la generacion posterior a validacion previa."""

from typing import Any

from intentfabric.application.plugin_catalog import PluginCatalog
from intentfabric.application.pre_validation import PreValidationService
from intentfabric.application.template_renderer import TemplateRendererPort
from intentfabric.domain.generation import (
    NodeConfigurationArtifact, ServiceGenerationPlan, compute_sha256,
)
from intentfabric.domain.template_key import Operation, TemplateKey


class DeterministicGeneratorService:
    """Genera artefactos por salto en orden canonico sin efectuar cambios de red."""

    def __init__(
        self, catalog: PluginCatalog, renderer: TemplateRendererPort,
        pre_validator: PreValidationService | None = None,
    ) -> None:
        self._catalog = catalog
        self._renderer = renderer
        self._pre_validator = pre_validator

    def generate(
        self, intent: Any, *, operation: Operation | str = Operation.PROVISION,
        variant: str = "default",
    ) -> ServiceGenerationPlan:
        """Valida si corresponde y renderiza la ruta con huellas de texto UTF-8."""
        operation = Operation(operation)
        if self._pre_validator is not None:
            self._pre_validator.validate_and_require(intent, operations=(operation.value,), variant=variant)
        artifacts: list[NodeConfigurationArtifact] = []
        for hop_index, hop in enumerate(intent.hops):
            key = TemplateKey(intent.service_type, operation, hop.role, variant)
            context = self._catalog.build_hop_context(intent, hop_index, operation)
            rendered_text = self._renderer.render(hop.vendor, key, context)
            commands = tuple(
                line for line in rendered_text.splitlines()
                if line.strip() and not line.lstrip().startswith(("!", "#"))
            )
            artifacts.append(NodeConfigurationArtifact(
                hop_index=hop_index,
                node_id=(getattr(hop, "node_id", None) or getattr(hop, "hostname", None)
                         or str(hop.management_ip)),
                management_ip=hop.management_ip, vendor=hop.vendor, role=hop.role,
                operation=operation, template_key=key, rendered_text=rendered_text,
                commands=commands, sha256=compute_sha256(rendered_text),
            ))
        plan_sha256 = compute_sha256("|".join(
            f"{artifact.hop_index}:{artifact.node_id}:{artifact.sha256}"
            for artifact in artifacts
        ))
        return ServiceGenerationPlan(
            service_id=getattr(intent, "service_id", None) or intent.description,
            service_type=intent.service_type, operation=operation, variant=variant,
            artifacts=tuple(artifacts), plan_sha256=plan_sha256,
        )
