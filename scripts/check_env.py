"""Informa las versiones del entorno y la advertencia SSH de Paramiko."""

import importlib.metadata
import platform
from collections.abc import Callable


def main(
    lookup: Callable[[str], str] = importlib.metadata.version,
    python_version: Callable[[], str] = platform.python_version,
) -> int:
    print(f"python: {python_version()}")
    paramiko_version = None
    for name in ("PyYAML", "Jinja2", "netmiko", "paramiko"):
        try:
            version = lookup(name)
        except importlib.metadata.PackageNotFoundError:
            print(f"{name}: no instalado")
        else:
            print(f"{name}: {version}")
            if name == "paramiko":
                paramiko_version = version

    if paramiko_version is not None:
        try:
            major = int(paramiko_version.split(".")[0])
        except ValueError:
            pass
        else:
            if major >= 5:
                print(
                    "ADVERTENCIA: Paramiko >=5 retiró SHA-1 (firmas RSA e "
                    "intercambio de claves); verificar compatibilidad SSH con "
                    "los equipos del laboratorio."
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
