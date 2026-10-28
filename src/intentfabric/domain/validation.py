"""Modelos inmutables para acumular hallazgos de validacion por subfase."""

from dataclasses import dataclass
from enum import StrEnum


class ValidationSeverity(StrEnum):
    """Clasifica los hallazgos que bloquean o advierten sobre una intencion."""

    ERROR = "error"
    WARNING = "warning"


class ValidationStage(StrEnum):
    """Identifica la subfase que produjo un hallazgo de validacion."""

    STATIC_OFFLINE = "static_offline"
    PREFLIGHT_ONLINE = "preflight_online"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Describe un hallazgo accionable con ubicacion y codigo taxonomico."""

    code: str
    message: str
    stage: ValidationStage
    severity: ValidationSeverity = ValidationSeverity.ERROR
    field_path: str | None = None
    node_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("code: se requiere texto no vacio en UPPER_SNAKE_CASE")
        if self.code[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
            for character in self.code
        ):
            raise ValueError("code: se requiere el formato UPPER_SNAKE_CASE")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message: se requiere texto no vacio y accionable")

    def sort_key(self) -> tuple[str, str, str, str, str]:
        """Ordena por subfase, severidad, codigo, nodo y campo afectado."""
        return (
            self.stage.value, self.severity.value, self.code,
            self.node_id or "", self.field_path or "",
        )


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Agrupa los hallazgos ordenados y el estado de ejecucion de Pre-Flight."""

    service_id: str
    service_type: str
    issues: tuple[ValidationIssue, ...]
    preflight_executed: bool = False

    def __post_init__(self) -> None:
        ordered = sorted(self.issues, key=lambda issue: (issue.sort_key(), issue.message))
        object.__setattr__(self, "issues", tuple(ordered))

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        """Devuelve los hallazgos que impiden continuar con el servicio."""
        return tuple(issue for issue in self.issues if issue.severity == ValidationSeverity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        """Devuelve las advertencias conservando el orden canonico."""
        return tuple(issue for issue in self.issues if issue.severity == ValidationSeverity.WARNING)

    @property
    def is_valid(self) -> bool:
        """Indica si el reporte permite continuar sin errores."""
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, object]:
        """Serializa el reporte con campos e issues en orden fijo."""
        return {
            "service_id": self.service_id,
            "service_type": self.service_type,
            "is_valid": self.is_valid,
            "preflight_executed": self.preflight_executed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [
                {
                    "code": issue.code,
                    "message": issue.message,
                    "stage": issue.stage.value,
                    "severity": issue.severity.value,
                    "field_path": issue.field_path,
                    "node_id": issue.node_id,
                }
                for issue in self.issues
            ],
        }
