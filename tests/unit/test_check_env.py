"""Contrato de salida de check_env con versiones simuladas."""

import importlib.metadata
import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture
def check_env() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "check_env.py"
    spec = importlib.util.spec_from_file_location("check_env", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_lookup(versions: dict[str, str]) -> Callable[[str], str]:
    def lookup(name: str) -> str:
        try:
            return versions[name]
        except KeyError:
            raise importlib.metadata.PackageNotFoundError(name) from None

    return lookup


@pytest.fixture
def versions() -> dict[str, str]:
    return {"PyYAML": "6.0.2", "Jinja2": "3.1.6", "netmiko": "4.8.0", "paramiko": "4.0.0"}


def test_all_installed(
    check_env: ModuleType, versions: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    result = check_env.main(make_lookup(versions), lambda: "3.14.2")
    assert result == 0
    assert capsys.readouterr().out == (
        "python: 3.14.2\n"
        "PyYAML: 6.0.2\n"
        "Jinja2: 3.1.6\n"
        "netmiko: 4.8.0\n"
        "paramiko: 4.0.0\n"
    )


def test_netmiko_missing(
    check_env: ModuleType, versions: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    del versions["netmiko"]
    assert check_env.main(make_lookup(versions), lambda: "3.14.2") == 0
    assert "netmiko: no instalado\n" in capsys.readouterr().out


@pytest.mark.parametrize("version", ["5.0.0", "6.0.0"])
def test_paramiko_warning(
    check_env: ModuleType,
    versions: dict[str, str],
    capsys: pytest.CaptureFixture[str],
    version: str,
) -> None:
    versions["paramiko"] = version
    assert check_env.main(make_lookup(versions), lambda: "3.14.2") == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 6
    assert lines[-1] == (
        "ADVERTENCIA: Paramiko >=5 retiró SHA-1 (firmas RSA e intercambio de "
        "claves); verificar compatibilidad SSH con los equipos del laboratorio."
    )


@pytest.mark.parametrize("version", ["4.0.0", "desconocida", ""])
def test_no_paramiko_warning(
    check_env: ModuleType,
    versions: dict[str, str],
    capsys: pytest.CaptureFixture[str],
    version: str,
) -> None:
    versions["paramiko"] = version
    assert check_env.main(make_lookup(versions), lambda: "3.14.2") == 0
    output = capsys.readouterr().out
    assert len(output.splitlines()) == 5
    assert "ADVERTENCIA" not in output


def test_all_libraries_missing_python_first(
    check_env: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    assert check_env.main(make_lookup({}), lambda: "3.13.0") == 0
    assert capsys.readouterr().out.splitlines() == [
        "python: 3.13.0",
        "PyYAML: no instalado",
        "Jinja2: no instalado",
        "netmiko: no instalado",
        "paramiko: no instalado",
    ]


def test_same_input_same_output(
    check_env: ModuleType, versions: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    lookup = make_lookup(versions)
    assert check_env.main(lookup, lambda: "3.14.2") == 0
    first = capsys.readouterr().out
    assert check_env.main(lookup, lambda: "3.14.2") == 0
    assert capsys.readouterr().out == first
