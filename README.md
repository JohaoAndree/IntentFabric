# IntentFabric

Framework determinista para la automatización de servicios de red multivendor
sobre infraestructura MPLS. Su alcance previsto comprende la generación,
pre-validación, despliegue y post-validación de configuraciones para Cisco
IOS-XE y Huawei VRP, con soporte para servicios DIA, L3VPN y L2VPN.

El proyecto se desarrolla como trabajo de grado de Ingeniería de Sistemas en la
Universidad de Lima, con enfoque en ingeniería de software aplicada a la
automatización de redes. La fase actual corresponde a la infraestructura del
paquete y sus dependencias, completada en ADR-002.

## Descripción general

IntentFabric busca transformar una intención operativa estructurada en
configuraciones específicas por plataforma y tipo de servicio. El flujo previsto
comprende cuatro fases: generación mediante reglas y plantillas, pre-validación
sintáctica y lógica, despliegue por SSH y post-validación del estado observado.

El diseño prioriza determinismo, trazabilidad y reproducibilidad: una misma
entrada deberá producir la misma configuración normalizada. La evaluación
experimental prevista utiliza una ruta mixta Cisco–Huawei en un laboratorio
físico. Las mejoras respecto del aprovisionamiento manual se mantienen como
hipótesis hasta disponer de mediciones.

Los servicios contemplados son acceso a Internet dedicado (DIA), VPN de capa 3
(L3VPN) y enlaces de capa 2 punto a punto (L2VPN). Su implementación funcional y
la verificación de compatibilidad con los equipos se realizarán en etapas
posteriores.

## Requisitos del sistema

| Componente | Requisito y alcance verificado |
|---|---|
| Sistema operativo | Windows 11 como entorno de referencia verificado. La ejecución en Linux está pendiente de validación. |
| Python | 3.14.2 como intérprete de referencia; mínimo declarado del paquete: 3.13. |
| Git | Control de versiones y acceso al repositorio. |
| PowerShell | Consola utilizada en los comandos de esta guía para Windows. |

El mínimo declarado no implica que todas las versiones posteriores estén
verificadas. El uso de Python 3.13 como contingencia requiere un diagnóstico
documentado; Python 3.15 queda fuera del entorno adoptado en ADR-002.

Las dependencias se declaran en [pyproject.toml](pyproject.toml):

| Grupo | Dependencias |
|---|---|
| Base | `PyYAML>=6.0`, `Jinja2>=3.1` |
| Desarrollo (`dev`) | `pytest>=8` |
| SSH opcional (`ssh`) | `netmiko>=4.8,<5` |

Paramiko se instala como dependencia transitiva de Netmiko, sin una restricción
adicional de versión en el proyecto.

## Instalación

Desde la raíz del repositorio, la instalación de desarrollo utiliza un entorno
virtual y el paquete en modo editable:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install -e ".[dev]"
```

La versión activa debe ser **3.14.2**; el selector `py -3.14` no fija el parche.
Si la activación falla, los comandos pueden ejecutarse con
`.\.venv\Scripts\python.exe` en lugar de `python`.

El soporte SSH se instala de forma opcional en el mismo entorno:

```powershell
python -m pip install -e ".[ssh]"
```

Esta instalación resuelve las dependencias según los rangos declarados. Para
reproducir el entorno registrado se utiliza el archivo de restricciones.

## Instalación reproducible

[requirements.lock](requirements.lock) contiene las versiones exactas capturadas
del entorno verificado con Python 3.14.2 en Windows. Se utiliza con `-c` como
archivo de restricciones: limita las versiones de las dependencias solicitadas
por el paquete y sus extras, sin instalar por sí solo todos los paquetes listados.

En un entorno virtual limpio con el intérprete de referencia:

```powershell
python -m pip install -c requirements.lock -e ".[dev]"
```

Para reproducir también el soporte SSH:

```powershell
python -m pip install -c requirements.lock -e ".[dev,ssh]"
```

El alcance actual del lock es **dev+ssh**. La captura no garantiza
reproducibilidad en Linux ni con otros intérpretes. Las versiones y los resultados
de instalación se registran en la sección 10 de [ADR-002](docs/adr/ADR-002.md).

## Verificación

La comprobación del entorno y la ejecución de las pruebas unitarias se realizan
con los siguientes comandos:

```powershell
python scripts/check_env.py
python -m pytest -q
```

El script informa las versiones de Python, PyYAML, Jinja2, Netmiko y Paramiko,
en ese orden. Una librería ausente se muestra como `no instalado`; el código de
salida es 0 incluso si faltan librerías. Con Paramiko 5 o superior se emite una
advertencia sobre mecanismos SSH retirados y compatibilidad con el laboratorio.

Las pruebas cubren las importaciones, el contrato de salida del script, las
ausencias de dependencias, la advertencia de Paramiko y el determinismo. El test
de Netmiko se omite cuando la librería no está instalada: ese resultado significa
**no comprobado**. La importación correcta no demuestra una conexión SSH real.

## Estado del proyecto y arquitectura

**ADR-002 completado:** paquete `intentfabric` 0.1.0, metadatos, dependencias,
verificación del entorno y lock reproducido en un entorno limpio. La verificación
registrada con los extras `dev+ssh` obtuvo **11 pruebas aprobadas**, sin omisiones.

| Ruta | Contenido actual |
|---|---|
| `src/intentfabric/` | Paquete base del framework. |
| `src/intentfabric/domain/` | Capa reservada para modelos puros e inmutables. |
| `src/intentfabric/application/` | Capa reservada para el pipeline, las fases y los puertos. |
| `src/intentfabric/services/` | Paquetes plugin por servicio, sin implementaciones concretas todavía. |
| `src/intentfabric/vendors/` | Paquetes plugin por vendor, sin implementaciones concretas todavía. |
| `src/intentfabric/adapters/` | Capa reservada para implementaciones de los puertos. |
| `src/intentfabric/bootstrap.py` | Raíz de composición reservada, únicamente con un docstring. |
| `docs/` | Decisiones de arquitectura (ADR) y registros de implementación. |
| `tests/` | Pruebas unitarias del entorno y directorio reservado para referencias golden. |
| `scripts/` | Script de diagnóstico de versiones `check_env.py`. |

La estructura hexagonal de [ADR-001](docs/adr/ADR-001.md) mantiene el dominio
independiente de las demás capas y de terceros. La aplicación depende del dominio;
los servicios, vendors y adaptadores dependen del núcleo. Los plugins permanecen
aislados entre sí, las librerías externas se limitan a los adaptadores y la
composición se concentra en `bootstrap.py`. La prueba `test_architecture.py`
comprueba estos límites mediante análisis estático de imports.

La generación de configuraciones, las validaciones de servicios y el despliegue
pertenecen al alcance previsto y aún no están implementados. La conexión SSH real
y la evaluación experimental siguen pendientes de verificación en laboratorio.

La decisión técnica y su evidencia se encuentran en [ADR-002](docs/adr/ADR-002.md)
y en su [walkthrough de implementación](docs/walkthroughs/ADR-002.md).

## Extensión: agregar un vendor o un servicio

El contrato de [ADR-004](docs/adr/ADR-004.md) separa las declaraciones de cada
plugin de la lectura de sus recursos. El registro se realiza en `bootstrap.py`;
los plugins nuevos utilizan los contratos existentes del núcleo.

Para incorporar un vendor:

1. Crea `src/intentfabric/vendors/<id>/__init__.py` y expón una
   `VENDOR_DEFINITION` construida con `VendorDefinition`. Usa un identificador
   de 2 a 32 caracteres que empiece por una letra minúscula y continúe con letras
   minúsculas, dígitos o guiones bajos.
2. Declara las combinaciones que soportará mediante claves `TemplateKey` y rutas
   relativas al paquete del vendor. Añade los archivos correspondientes bajo
   `templates/<servicio en minúsculas>/<operación>/<rol>.j2`. Las operaciones son
   `provision` y `teardown`; los roles, `access`, `transit` y `pe`. Se utiliza la
   variante `default`; la selección de otras variantes queda pendiente del
   laboratorio y de su ADR.
3. Importa el paquete en `bootstrap.py` e incorpóralo a `VENDOR_PACKAGES`.
   El catálogo registra su definición y proporciona sus identificadores al parser
   DIA; no hace falta mantener otra lista de vendors conocidos.
4. Ejecuta las pruebas de contrato y después la suite completa desde la raíz:

   ```powershell
   python -m pytest -q tests/contract
   python -m pytest -q
   ```

Para incorporar un servicio, crea `src/intentfabric/services/<service>/` con un
parser que cumpla `ServiceIntentParser`: declara su `service_type` y convierte la
entrada estructurada en una intención de dominio. Regístralo mediante
`catalog.register_service(...)` en `build_plugin_catalog()`, después de registrar
los vendors. Añade las declaraciones y plantillas del servicio en cada vendor que
deba soportarlo y ejecuta las mismas verificaciones.

`build_verified_catalog()` comprueba los servicios declarados y la lectura de las
plantillas antes de devolver el catálogo. Los registros duplicados se rechazan;
las combinaciones sin plantilla fallan con `UnsupportedCombinationError` al
resolverlas. Las pruebas de contrato también detectan rutas fuera de la convención
y archivos `.j2` que no figuran en la definición.

Actualmente Cisco y Huawei están registrados con mapas de plantillas vacíos.
Su contenido de red y las referencias golden se incorporarán en ADR-006;
ADR-004 no implementa renderizado ni conexión con equipos.

## Gestión de lockfile

La actualización de `requirements.lock` constituye un cambio controlado de
dependencias. El procedimiento requiere resolver los rangos de `pyproject.toml`
en un entorno limpio con el intérprete de referencia y los extras del alcance,
ejecutar las verificaciones y capturar las versiones con:

```powershell
python -m pip freeze --exclude-editable
```

La salida se guarda en `requirements.lock` con codificación UTF-8 y saltos de
línea LF. Antes de incorporar el cambio, la instalación con `-c` se repite en
`.venv-verify`; se ejecutan el script y las pruebas, se comparan las versiones
con el lock y se elimina el entorno temporal. El registro técnico debe incluir
el motivo, el intérprete, las versiones, el alcance y los resultados.
