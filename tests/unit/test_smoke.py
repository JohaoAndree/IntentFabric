"""Pruebas de importación; no comprueban conexiones de red."""

import pytest


def test_base_imports() -> None:
    import intentfabric
    import jinja2
    import yaml

    assert intentfabric is not None
    assert jinja2 is not None
    assert yaml is not None


def test_netmiko_import() -> None:
    netmiko = pytest.importorskip("netmiko")
    assert netmiko is not None
