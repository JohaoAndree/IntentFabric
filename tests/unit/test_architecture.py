"""Comprueba las dependencias estáticas de las capas según ADR-001."""

import ast
import sys
from importlib.util import resolve_name
from pathlib import Path

import pytest


def _classify(module: str, package: str) -> tuple[str, str | None]:
    parts = module.removeprefix(package).lstrip(".").split(".")
    layer = parts[0] if parts[0] != "__init__" else ""
    plugin = parts[1] if layer in ("services", "vendors") and len(parts) > 1 else None
    return layer, plugin


def _import_targets(node: ast.Import | ast.ImportFrom, context: str) -> tuple[str, ...]:
    if isinstance(node, ast.Import):
        return tuple(alias.name for alias in node.names)
    base = node.module or ""
    if node.level:
        base = resolve_name("." * node.level + base, context)
    # Evaluar X.a evita ocultar una capa mediante from intentfabric import adapters.
    return (base,) + tuple(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")


def _dependency_rule(
    source: tuple[str, str | None], target: str, package: str
) -> str | None:
    source_layer, source_plugin = source
    if target != package and not target.startswith(package + "."):
        root = target.split(".")[0]
        if root not in sys.stdlib_module_names and source_layer != "adapters":
            return f"{source_layer or package}: terceros solo permitidos en adapters ({root})"
        return None
    if target == package:
        return None
    target_layer, target_plugin = _classify(target, package)
    allowed = {
        "": ("",),
        "domain": ("domain",),
        "application": ("application", "domain"),
        "services": ("services", "domain", "application"),
        "vendors": ("vendors", "domain", "application"),
        "adapters": ("adapters", "domain", "application"),
        "bootstrap": (
            "", "domain", "application", "services", "vendors", "adapters", "bootstrap", "cli"
        ),
        "cli": ("cli", "domain", "application", "bootstrap"),
    }
    if target_layer not in allowed:
        return "módulo no clasificado en ADR-001"
    if source_layer in ("services", "vendors") and source_plugin is not None:
        if target_layer in ("services", "vendors") and target_layer != source_layer:
            return "un plugin no puede importar del otro tipo de plugin"
        if target_layer == source_layer and target_plugin not in (None, source_plugin):
            return "un plugin no puede importar de otro plugin"
    if target_layer not in allowed[source_layer]:
        return f"{source_layer or package} no puede importar {target_layer or package}"
    return None


def collect_violations(src_root: Path, package: str = "intentfabric") -> list[str]:
    """Analiza el paquete bajo src_root y devuelve reglas incumplidas sin ejecutar código.

    Los mensajes usan rutas relativas a src_root y números de línea; se ordenan
    lexicográficamente y se deduplica cada regla incumplida en una misma línea.
    """
    violations: list[str] = []
    package_root = src_root.joinpath(*package.split("."))
    layers = (
        "", "domain", "application", "services", "vendors", "adapters", "bootstrap", "cli"
    )
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(src_root)
        if path.parent == package_root and path.stem not in ("__init__", "bootstrap", "cli"):
            violations.append(f"{relative.as_posix()}: módulo no clasificado en ADR-001")
            continue
        parts = relative.with_suffix("").parts
        is_package = parts[-1] == "__init__"
        module = ".".join(parts[:-1] if is_package else parts)
        source = _classify(module, package)
        if source[0] not in layers:
            violations.append(f"{relative.as_posix()}: módulo no clasificado en ADR-001")
            continue
        context = module if is_package else module.rpartition(".")[0]
        with path.open(encoding="utf-8", newline="\n") as stream:
            tree = ast.parse(stream.read(), filename=relative.as_posix())
        # Las dependencias bajo TYPE_CHECKING también restringen la arquitectura.
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for target in _import_targets(node, context):
                    rule = _dependency_rule(source, target, package)
                    if rule is not None:
                        violations.append(f"{relative.as_posix()}:{node.lineno}: {rule}")
    return sorted(set(violations))


def _write_module(src_root: Path, module_path: str, source: str) -> None:
    path = src_root / module_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8", newline="\n")


def test_real_tree_has_no_violations() -> None:
    """Comprueba que el código del proyecto respeta las capas del ADR."""
    src_root = Path(__file__).resolve().parents[2] / "src"
    assert collect_violations(src_root) == []


@pytest.mark.parametrize("module_name", ("interfaces.py", "topology.py"))
def test_topology_domain_modules_preserve_stdlib_boundary(tmp_path: Path, module_name: str) -> None:
    """Incluye los nuevos modulos en la verificacion AST sin excepciones de capa."""
    _write_module(tmp_path, f"intentfabric/domain/{module_name}", "import yaml\n")
    assert any("terceros solo permitidos en adapters (yaml)" in issue
               for issue in collect_violations(tmp_path))


@pytest.mark.parametrize(
    "module_name", ["domain", "application", "services", "vendors", "adapters", "utils"]
)
def test_unclassified_root_modules_report_violation(
    tmp_path: Path, module_name: str
) -> None:
    """Rechaza módulos raíz no reservados incluso si tienen el nombre de una capa."""
    module_path = f"intentfabric/{module_name}.py"
    _write_module(tmp_path, module_path, '"""Módulo sintético en la raíz."""\n')
    assert collect_violations(tmp_path) == [
        f"{module_path}: módulo no clasificado en ADR-001"
    ]


@pytest.mark.parametrize(
    ("module_path", "source", "rule"),
    [
        ("domain/check.py", "import intentfabric.adapters\n", "domain no puede importar adapters"),
        ("domain/check.py", "import yaml\n", "terceros solo permitidos en adapters (yaml)"),
        ("domain/check.py", "from ..adapters import x\n", "domain no puede importar adapters"),
        ("application/check.py", "import jinja2\n", "terceros solo permitidos en adapters (jinja2)"),
        ("services/dia/check.py", "import yaml\n", "terceros solo permitidos en adapters (yaml)"),
        ("services/dia/check.py", "import intentfabric.services.l3vpn\n", "otro plugin"),
        ("vendors/cisco/check.py", "import textfsm\n", "terceros solo permitidos en adapters (textfsm)"),
        ("vendors/cisco/check.py", "import intentfabric.adapters\n", "vendors no puede importar adapters"),
        ("adapters/check.py", "import intentfabric.vendors.cisco\n", "adapters no puede importar vendors"),
        ("domain/check.py", "from intentfabric import adapters\n", "domain no puede importar adapters"),
        ("domain/check.py", "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import intentfabric.adapters\n", "domain no puede importar adapters"),
        ("domain/__init__.py", "from .. import adapters\n", "domain no puede importar adapters"),
        ("domain/check.py", "from intentfabric import domain, adapters\n", "domain no puede importar adapters"),
        ("vendors/cisco/check.py", "from ..huawei import parser\n", "otro plugin"),
        ("services/dia/check.py", "import intentfabric.vendors.cisco\n", "otro tipo de plugin"),
        ("vendors/cisco/check.py", "import intentfabric.services.dia\n", "otro tipo de plugin"),
        ("helpers.py", "", "módulo no clasificado en ADR-001"),
        ("bootstrap.py", "import yaml\n", "terceros solo permitidos en adapters (yaml)"),
        ("cli.py", "import yaml\n", "terceros solo permitidos en adapters (yaml)"),
    ],
)
def test_forbidden_imports_report_file_and_rule(
    tmp_path: Path, module_path: str, source: str, rule: str
) -> None:
    """Detecta las violaciones sintéticas con el archivo y la regla afectada."""
    _write_module(tmp_path, f"intentfabric/{module_path}", source)
    violations = collect_violations(tmp_path)
    assert violations
    assert any(
        f"intentfabric/{module_path}" in message and rule in message
        for message in violations
    )


@pytest.mark.parametrize(
    ("module_path", "source"),
    [
        ("adapters/check.py", "import yaml, textfsm, intentfabric.domain\n"),
        ("services/dia/check.py", "import intentfabric.domain\nimport intentfabric.services.dia.rules\n"),
        ("bootstrap.py", "import intentfabric.adapters\n"),
        ("domain/check.py", "import intentfabric\nimport ast, sys\nfrom pathlib import Path\n"),
        ("services/dia/check.py", "from . import rules\nfrom ...domain import result\n"),
        ("vendors/cisco/__init__.py", "from .parser import parse\nfrom ...application import ports\n"),
        ("domain/check.py", "from . import *\n"),
        ("__init__.py", '"""Paquete de laboratorio."""\n'),
    ],
)
def test_allowed_imports_have_no_violations(
    tmp_path: Path, module_path: str, source: str
) -> None:
    """Acepta dependencias permitidas, biblioteca estándar e imports propios."""
    _write_module(tmp_path, f"intentfabric/{module_path}", source)
    assert collect_violations(tmp_path) == []


@pytest.mark.parametrize("source_layer", ["domain", "application", "services", "vendors", "adapters", "bootstrap", "cli"])
@pytest.mark.parametrize("target_layer", ["domain", "application", "services", "vendors", "adapters", "bootstrap", "cli"])
def test_project_dependencies_follow_layer_table(
    tmp_path: Path, source_layer: str, target_layer: str
) -> None:
    """Contrasta todas las combinaciones de capas con la tabla de dependencias."""
    permitted = {
        "domain": {"domain"},
        "application": {"domain", "application"},
        "services": {"domain", "application", "services"},
        "vendors": {"domain", "application", "vendors"},
        "adapters": {"domain", "application", "adapters"},
        "bootstrap": {"domain", "application", "services", "vendors", "adapters", "bootstrap", "cli"},
        "cli": {"domain", "application", "bootstrap", "cli"},
    }
    module_path = (
        f"{source_layer}.py"
        if source_layer in ("bootstrap", "cli")
        else f"{source_layer}/check.py"
    )
    _write_module(
        tmp_path, f"intentfabric/{module_path}", f"import intentfabric.{target_layer}\n"
    )
    assert bool(collect_violations(tmp_path)) == (target_layer not in permitted[source_layer])


def test_analysis_does_not_execute_project_code(tmp_path: Path) -> None:
    """Detecta imports sin ejecutar las instrucciones del módulo inspeccionado."""
    _write_module(
        tmp_path,
        "intentfabric/domain/check.py",
        "raise RuntimeError('No ejecutar')\nimport yaml\n",
    )
    assert collect_violations(tmp_path)


def test_diagnostics_are_independent_of_file_creation_order(tmp_path: Path) -> None:
    """Produce los mismos mensajes ante árboles equivalentes creados en otro orden."""
    modules = (
        ("intentfabric/domain/b.py", "import yaml\n"),
        ("intentfabric/application/a.py", "import jinja2\n"),
    )
    first = tmp_path / "first"
    second = tmp_path / "second"
    for module_path, source in modules:
        _write_module(first, module_path, source)
    for module_path, source in reversed(modules):
        _write_module(second, module_path, source)
    violations = collect_violations(first)
    assert violations == collect_violations(first) == collect_violations(second)
    assert violations == sorted(violations)


def test_package_parameter_changes_project_root(tmp_path: Path) -> None:
    """Resuelve imports propios y relativos para el nombre de paquete recibido."""
    _write_module(tmp_path, "labfabric/domain/check.py", "from ..adapters import x\n")
    assert any(
        "domain no puede importar adapters" in message
        for message in collect_violations(tmp_path, "labfabric")
    )
