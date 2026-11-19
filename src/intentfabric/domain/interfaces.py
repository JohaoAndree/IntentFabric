"""Normaliza y abrevia interfaces de forma pura y determinista."""

import re

from intentfabric.domain.errors import InvalidInterfaceNameError


_PREFIX_RULES = (
    (("gi", "ge", "gigabitethernet"), "GigabitEthernet", "GE", "Gi", "GE"),
    (("te", "10ge", "tengigabitethernet"), "TenGigabitEthernet", "10GE", "Te", "10GE"),
    (("xge", "xgigabitethernet"), "XGigabitEthernet", "XGE", "Te", "XGE"),
    (("multige", "multigigabitethernet", "mge"), "MultiGigabitEthernet", "MultiGE", None, "MultiGE"),
    (("fa", "fastethernet"), "FastEthernet", "FastEthernet", "Fa", "Fa"),
    (("eth", "ethernet"), "Ethernet", "Ethernet", "Eth", "Eth"),
    (("lo", "loopback"), "Loopback", "Loopback", "Lo", "LoopBack"),
    (("vl", "vlan"), "Vlan", "Vlanif", "Vl", "Vlanif"),
    (("vlanif",), "Vlanif", "Vlanif", "Vl", "Vlanif"),
)


def _is_huawei(vendor: str | None) -> bool:
    return isinstance(vendor, str) and vendor.strip().lower() == "huawei"


def normalize_interface_name(name: str, *, vendor: str | None = None) -> str:
    """Expande prefijos conocidos y valida indices y subinterfaces VLAN."""
    match = re.fullmatch(r"(10ge|[a-z]+)( *)([0-9]+(?:/[0-9]+)*(?:\.[0-9]+)?)", name, re.I) if isinstance(name, str) else None
    if match is None:
        raise InvalidInterfaceNameError(f"interface: nombre invalido {name!r}")
    prefix, spacing, indices = match.groups()
    is_huawei = _is_huawei(vendor)
    for aliases, default_canonical, huawei_canonical, cisco_prefix, _ in _PREFIX_RULES:
        if prefix.lower() in aliases:
            break
    else:
        raise InvalidInterfaceNameError(f"interface: prefijo desconocido en {name!r}")
    if spacing and not (is_huawei and default_canonical in ("Vlan", "Vlanif")):
        raise InvalidInterfaceNameError(f"interface: nombre invalido {name!r}")
    if not is_huawei and cisco_prefix is None and vendor is not None:
        raise InvalidInterfaceNameError(f"interface: prefijo desconocido en {name!r}")
    if default_canonical in ("Loopback", "Vlan", "Vlanif"):
        if not indices.isdecimal():
            raise InvalidInterfaceNameError(f"interface: se requiere un entero en {name!r}")
    elif "." in indices and not 1 <= int(indices.rsplit(".", 1)[1]) <= 4094:
        raise InvalidInterfaceNameError(f"interface: subinterfaz VLAN fuera de 1..4094 en {name!r}")
    if is_huawei:
        canonical = huawei_canonical
    elif default_canonical == "Vlanif" and vendor == "cisco":
        canonical = "Vlan"
    else:
        canonical = default_canonical
    return canonical + indices


def abbreviate_interface_name(name: str, vendor: str) -> str:
    """Devuelve la abreviatura nativa del fabricante conservando los indices."""
    is_huawei = _is_huawei(vendor)
    if not is_huawei and vendor != "cisco":
        raise InvalidInterfaceNameError(f"vendor: fabricante no soportado {vendor!r}")
    normalized = normalize_interface_name(name, vendor=vendor)
    for _, default_canonical, huawei_canonical, cisco_prefix, huawei_prefix in _PREFIX_RULES:
        if not is_huawei and cisco_prefix is None:
            continue
        canonical = (
            huawei_canonical
            if is_huawei
            else ("Vlan" if default_canonical == "Vlanif" else default_canonical)
        )
        if normalized.startswith(canonical) and normalized[len(canonical):len(canonical) + 1].isdigit():
            prefix = huawei_prefix if is_huawei else cisco_prefix
            if prefix is None:
                raise InvalidInterfaceNameError(f"interface: prefijo desconocido en {name!r}")
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
