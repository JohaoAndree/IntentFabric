# IntentFabric

Framework determinista en Python para aprovisionamiento y validación automática de ciclo cerrado de servicios corporativos DIA, L3VPN y L2VPN (`evpn_vpws` / `martini_ldp`) sobre redes MPLS/L2 Cisco IOS-XE y Huawei VRP. Convierte intención declarativa JSON/YAML en configuración y contrasta el estado observado con el esperado, según el ciclo de vida de RFC 9315 adoptado en [ADR-012](docs/adr/ADR-012.md).

**Estado:** E1–E4 completadas hasta ADR-012. La implementación y las pruebas simuladas están cerradas; las mejoras operativas de la tesis requieren mediciones de laboratorio.

## Arquitectura hexagonal

| Capa en `src/intentfabric/` | Responsabilidad |
|---|---|
| `domain/` | Modelos inmutables, derivaciones matemáticas en base 1000 y normalización de interfaces. |
| `application/` | Puertos, catálogo, servicios de las cuatro fases y `PipelineOrchestrator`. |
| `services/` | Parsers, validadores semánticos y contextos de `dia`, `l3vpn` y `l2vpn`. |
| `vendors/` | Definiciones `cisco`/`huawei`, escalado bps/kbps y plantillas Jinja2 `provision` / `teardown`. |
| `adapters/` | E/S JSON/YAML, Jinja2, Netmiko SSH, transporte simulado y `FileExecutionLogger` JSON/CSV. |
| `bootstrap.py`, `cli.py` | Composición de dependencias y entrada `argparse`. |

El núcleo (`domain/`, `application/`, `services/`, `vendors/`) usa solo `stdlib`. Las dependencias externas quedan en `adapters/`; [test_architecture.py](tests/unit/test_architecture.py) verifica las fronteras mediante AST.

## Pipeline determinista de cuatro fases

1. **Validación previa híbrida — `PreValidationService`.** La subfase 1A valida estructura, semántica y coherencia con `inventory/topology.yaml` offline. La subfase 1B ejecuta el Pre-Flight online de solo lectura. Un rechazo impide generar y desplegar (*Fail-Fast*).
2. **Generación determinista — `DeterministicGeneratorService`.** `TopologyPathResolver` resuelve la ruta L2 → PE al parsear la intención. Se derivan direccionamiento y QoS en base 1000 y se renderizan plantillas Jinja2 con `StrictUndefined`. Configuraciones normalizadas y plan incluyen hashes SHA-256; la misma entrada, topología y variante producen la misma configuración.
3. **Despliegue automatizado — `DeploymentService`.** Aplica `provision` o `teardown` secuencialmente mediante `NetmikoTransportAdapter` (CLI-over-SSH, `commit` para `huawei_vrpv8`) o `SimulatedTransportAdapter`. Un fallo detiene el despliegue y conserva resultados parciales.
4. **Validación posdespliegue — `PostValidationTriageService`.** El triage prioriza interfaz PE, continuidad LLDP, VLAN/MAC y control del servicio: rutas VRF/VPNv4 y eBGP, o circuito EVPN/VPWS-LDP. DIA y L3VPN usan una sonda SVI efímera con limpieza en `finally`; L2VPN valida el circuito sin SVI. `OPERATIONAL` y `READY_FOR_SERVICE` cumplen SDC=1; `FAILED` cumple SDC=0. L3VPN admite `READY_FOR_SERVICE` con eBGP `Active`/`Idle` si las demás comprobaciones cumplen.

`PipelineOrchestrator.run()` coordina las cuatro fases y omite la fase 4 si falla el despliegue. `ExecutionRecord` reúne reportes, tiempos por fase/total, hash, SDC y causa raíz. Los tiempos medidos y las salidas de red dependen de la ejecución.

## Requisitos e instalación

Python >= 3.13; entorno base: **Python 3.14.2** en Windows. El selector `py -3.14` no fija el parche. Desde la raíz, en PowerShell:

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python --version
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -m pip install --no-deps -e .
```

[requirements.lock](requirements.lock) fija el entorno de desarrollo y SSH; [pyproject.toml](pyproject.toml) declara el paquete y el entrypoint `intentfabric`.

## Guía de uso de la CLI

```text
intentfabric {validate,generate,deploy,verify,run,teardown}
             --intent ARCHIVO [--topology ARCHIVO] [--variant VARIANTE]
             [--transport {none,simulated,ssh}]
             [--json-out ARCHIVO] [--csv-out ARCHIVO]
intentfabric generate --intent ARCHIVO [opciones comunes]
                      [--operation {provision,teardown}]
```

| Subcomando | Ejecución | Transporte predeterminado |
|---|---|---|
| `validate` | Fase 1; incluye Pre-Flight si hay transporte. | `none` |
| `generate` | Validación estática y generación; `--operation` predetermina `provision`. | `none` |
| `deploy` | Validación, generación y despliegue de `provision`. | `simulated` |
| `verify` | Solo auditoría posdespliegue; puede crear la sonda SVI temporal. | `simulated` |
| `run` | Las cuatro fases. | `simulated` |
| `teardown` | Validación estática, generación y despliegue de retiro, sin Pre-Flight online ni fase 4. | `simulated` |

Opciones comunes a todos los subcomandos:

| Opción | Contrato |
|---|---|
| `--intent`, `-i` | Archivo JSON/YAML requerido. |
| `--topology`, `-t` | Predeterminado: `inventory/topology.yaml`. |
| `--variant`, `-v` | Predeterminado: `default`; L2VPN admite `evpn_vpws` y `martini_ldp`. |
| `--transport` | `none`, `simulated` o `ssh`; despliegue y auditoría requieren transporte. |
| `--json-out` | Reemplaza el archivo con el registro completo. |
| `--csv-out` | Anexa métricas; crea encabezado si falta o está vacío. |
| `--help`, `-h` | Ayuda del comando. |

La CLI imprime el registro JSON en stdout. Retorna `0` si cumple, `1` ante resultado fallido y `2` ante argumentos inválidos o errores de carga, credenciales o ejecución. SDC es `null` si no se ejecuta la fase 4.

Ejemplos offline y simulados, sin hardware ni credenciales:

```powershell
.venv\Scripts\intentfabric validate -i examples/intents/dia_valid.yaml -t inventory/topology.yaml --transport none
.venv\Scripts\intentfabric generate -i examples/intents/l3vpn_valid.yaml -t inventory/topology.yaml --transport none
.venv\Scripts\intentfabric generate -i examples/intents/l2vpn_valid.yaml -v martini_ldp --operation teardown
.venv\Scripts\intentfabric run -i examples/intents/dia_valid.yaml -t inventory/topology.yaml --transport simulated --json-out runs/dia.json --csv-out runs/metrics.csv
.venv\Scripts\intentfabric run -i examples/intents/l3vpn_valid.yaml --transport simulated --json-out runs/l3vpn.json --csv-out runs/metrics.csv
.venv\Scripts\intentfabric run -i examples/intents/l2vpn_valid.yaml -v evpn_vpws --transport simulated --json-out runs/l2vpn.json --csv-out runs/metrics.csv
.venv\Scripts\intentfabric teardown -i examples/intents/l2vpn_valid.yaml -v evpn_vpws --transport simulated
```

Para SSH, selecciona `--transport ssh` y define `INTENTFABRIC_SSH_USERNAME` y `INTENTFABRIC_SSH_PASSWORD` en el entorno. Opcionales: `INTENTFABRIC_SSH_SECRET`, `INTENTFABRIC_SSH_PORT` (22) e `INTENTFABRIC_SSH_TIMEOUT` (30 segundos). El destino procede del inventario.

## Verificación y pruebas

```powershell
.venv\Scripts\python scripts/check_env.py
.venv\Scripts\python -m pytest
.venv\Scripts\python -m pytest tests/unit/test_architecture.py tests/contract
.venv\Scripts\python -m pytest tests/unit/test_dia_golden.py tests/unit/test_l3vpn_golden.py tests/unit/test_l2vpn_golden.py
```

`check_env.py` informa versiones y ausencias; su código 0 no garantiza dependencias instaladas. Advierte sobre compatibilidad SSH con Paramiko >= 5. Si el entorno restringe el directorio temporal del sistema, configura `$env:PYTEST_DEBUG_TEMPROOT = "$PWD/runs"` antes de pytest.

## Estructura del repositorio y hoja de ruta

```text
src/intentfabric/
  domain/           Modelos y derivaciones puras
  application/      Puertos y pipeline
  services/         dia/, l3vpn/, l2vpn/
  vendors/          cisco/, huawei/ y plantillas
  adapters/         E/S y transportes
  bootstrap.py      Composición
  cli.py            CLI intentfabric
inventory/          Topología estática
examples/intents/   Intenciones JSON/YAML de laboratorio
tests/              unit/, contract/, fixtures/, golden/
scripts/            Diagnóstico del entorno
docs/               adr/, specs/, walkthroughs/
```

| ADR | Etapa | Alcance completado | Estado |
|---|---|---|---|
| [ADR-001](docs/adr/ADR-001.md) | E1 | Arquitectura hexagonal y AST. | Accepted |
| [ADR-002](docs/adr/ADR-002.md) | E1 | Runtime, empaquetado y dependencias bloqueadas. | Accepted |
| [ADR-003](docs/adr/ADR-003.md) | E1 | Intención DIA y derivaciones. | Partially Superseded por ADR-007 |
| [ADR-004](docs/adr/ADR-004.md) | E1 | Contratos de extensión y catálogo. | Accepted |
| [ADR-005](docs/adr/ADR-005.md) | E1 | Validación semántica y contrato Pre-Flight. | Accepted |
| [ADR-006](docs/adr/ADR-006.md) | E1 | Generación DIA, QoS decimal y golden files. | Accepted |
| [ADR-007](docs/adr/ADR-007.md) | E2 | Topología, ruta L2 → PE e interfaces. | Accepted |
| [ADR-008](docs/adr/ADR-008.md) | E2 | L3VPN, BGP y golden files. | Accepted |
| [ADR-009](docs/adr/ADR-009.md) | E2 | L2VPN EVPN/VPWS y Martini LDP. | Accepted |
| [ADR-010](docs/adr/ADR-010.md) | E3 | Transportes, Pre-Flight y despliegue. | Accepted |
| [ADR-011](docs/adr/ADR-011.md) | E4 | Triage, sonda SVI y SDC. | Accepted |
| [ADR-012](docs/adr/ADR-012.md) | E4 | Orquestador, registro JSON/CSV y CLI. | Accepted |

Fuera del MVP: rollback transaccional, aprovisionamiento del underlay/core día 0, configuración CE, Web UI, concurrencia multiusuario y YANG/NETCONF/gNMI. Las reglas de diseño se conservan en [context-master.md](docs/specs/context-master.md).
