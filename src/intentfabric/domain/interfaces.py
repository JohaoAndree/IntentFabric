"""Normaliza y abrevia interfaces de forma pura y determinista."""

import re

from intentfabric.domain.errors import InvalidInterfaceNameError


_PREFIX_RULES = (
    (("gi", "ge", "gigabitethernet"), "GigabitEthernet", "Gi", "GE"),
    (("te", "10ge", "tengigabitethernet"), "TenGigabitEthernet", "Te", "10GE"),
    (("xge", "xgigabitethernet"), "XGigabitEthernet", "Te", "XGE"),
    (("fa", "fastethernet"), "FastEthernet", "Fa", "Fa"),
    (("eth", "ethernet"), "Ethernet", "Eth", "Eth"),
    (("lo", "loopback"), "Loopback", "Lo", "LoopBack"),
    (("vl", "vlan"), "Vlan", "Vl", "Vlanif"),
    (("vlanif",), "Vlanif", "Vl", "Vlanif"),
)


def normalize_interface_name(name: str, *, vendor: str | None = None) -> str:
    """Expande prefijos conocidos y valida indices y subinterfaces VLAN."""
    match = re.fullmatch(r"(10ge|[a-z]+)([0-9]+(?:/[0-9]+)*(?:\.[0-9]+)?)", name, re.I) if isinstance(name, str) else None
    if match is None:
        raise InvalidInterfaceNameError(f"interface: nombre invalido {name!r}")
    prefix, indices = match.groups()
    for aliases, canonical, _, _ in _PREFIX_RULES:
        if prefix.lower() in aliases:
            break
    else:
        raise InvalidInterfaceNameError(f"interface: prefijo desconocido en {name!r}")
    if canonical in ("Loopback", "Vlan", "Vlanif"):
        if not indices.isdecimal():
            raise InvalidInterfaceNameError(f"interface: se requiere un entero en {name!r}")
    elif "." in indices and not 1 <= int(indices.rsplit(".", 1)[1]) <= 4094:
        raise InvalidInterfaceNameError(f"interface: subinterfaz VLAN fuera de 1..4094 en {name!r}")
    if canonical in ("Vlan", "Vlanif") and vendor in ("cisco", "huawei"):
        canonical = "Vlan" if vendor == "cisco" else "Vlanif"
    return canonical + indices


def abbreviate_interface_name(name: str, vendor: str) -> str:
    """Devuelve la abreviatura nativa del fabricante conservando los indices."""
    if vendor not in ("cisco", "huawei"):
        raise InvalidInterfaceNameError(f"vendor: fabricante no soportado {vendor!r}")
    normalized = normalize_interface_name(name, vendor=vendor)
    for _, canonical, cisco_prefix, huawei_prefix in _PREFIX_RULES:
        if normalized.startswith(canonical) and normalized[len(canonical):len(canonical) + 1].isdigit():
            prefix = cisco_prefix if vendor == "cisco" else huawei_prefix
            return prefix + normalized[len(canonical):]
    raise InvalidInterfaceNameError(f"interface: nombre invalido {name!r}")


def split_subinterface(name: str, *, vendor: str | None = None) -> tuple[str, int | None]:
    """Separa la interfaz madre canonica y el identificador VLAN opcional."""
    normalized = normalize_interface_name(name, vendor=vendor)
    parent, separator, vlan = normalized.partition(".")
    return parent, int(vlan) if separator else None


def are_equivalent_interfaces(first: str, second: str, *, vendor: str | None = None) -> bool:
    """Compara identificadores tras aplicar las mismas reglas canonicas."""
    return normalize_interface_name(first, vendor=vendor) == normalize_interface_name(second, vendor=vendor)
