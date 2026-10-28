# AGENTS.md

## Proyecto
IntentFabric: Framework modular determinista de aprovisionamiento y validación automática de servicios de red multivendor (DIA, L3VPN y L2VPN sobre MPLS/L2 en Cisco IOS-XE y Huawei VRP) mediante intención estructurada para operadores Carrier/NOC y evaluación experimental de tesis.
Prioridades: determinismo bit a bit, seguridad operativa (Fail-Fast pre/post-change), aislamiento arquitectonico hexagonal y trazabilidad experimental sobre funcionalidad extra.
Responsable: Johao Andreé. Aprueba las especificaciones y realiza las acciones prohibidas al agente.

## Especificación
Documento que define cada tarea; el prompt indica cuál. Ubicación: `docs/adr/ADR-00X.md`.
| Elemento | Dónde está |
| ------ | ------ |
| Identificador `<id>` | `ADR-00X` → `adr-00x` (ej. `ADR-005` → `adr-005`) |
| Aprobación | Metadato superior `Estado: Accepted` |
| Contexto (solo lectura) | Parte A, secciones 1-6 |
| Implementación (lo que se ejecuta) | Parte B, secciones 7-8 |
| Criterios de aceptación | Parte B, sección 9 |
| Registro de la tarea | Parte B, sección 10 |

* **Paso:** cada elemento de la lista ordenada de Implementación.
* Implementar o revisar requiere especificación aprobada. Si no lo está, detente y avisa.
* Si el prompt limita el alcance (p. ej. pasos 2-4), trabaja solo sobre eso.
* Si la especificación no sigue esta estructura: ejecuta solo lo redactado como instrucción de implementación y trata el resto como contexto. Si no puedes distinguirlos, o faltan criterios de aceptación verificables, detente y pregunta.

## Fuentes de verdad
Precedencia al interpretar: Especificación > AGENTS.md > `pyproject.toml` y `tests/test_architecture.py` > convenciones del código existente. Una contradicción que impida cumplir la tarea es un bloqueo (ver «Cómo trabajar»).

## Roles
* **Implementación** (por defecto): ejecuta los pasos de Implementación de la especificación indicada.
* **Revisión** (solo si el prompt lo indica): verifica la rama contra los criterios de aceptación. No modifica `src/` ni la especificación; puede agregar pruebas en `tests/`. Confirma que la rama corresponde a la tarea, lista sus commits respecto a la rama principal y ejecuta las pruebas («Comandos»). Informa:
    1. Por criterio: cumple / no cumple / no comprobable, con evidencia (comando o archivo).
    2. Aparte: incumplimientos de «Código y comentarios».
    3. Aparte: hallazgos fuera de la especificación.

## Cómo trabajar
* Implementa solo lo que Implementación indica. El Contexto y las decisiones previas no se reabren ni se sustituyen por alternativas propias.
* Edita solo los archivos que Implementación indica. De la especificación modifica únicamente el Registro, nunca el Contexto ni la aprobación. Única excepción: el walkthrough.
* Si la especificación tiene Registro, agrega una fila por punto de control en el mismo commit, siguiendo su formato (fecha del commit).
* No agregues dependencias ni features fuera de la especificación. Prohibido: nuevas librerías en `pyproject.toml` o `requirements.lock`, llamadas a LLMs/APIs externas, Web UI, soporte CE o rollback transaccional no especificado.
* Problema no bloqueante en la especificación: repórtalo en el resumen, sin cambiarla.
* Bloqueo (contradicción entre fuentes, o algo que impide implementar o cumplir los criterios): detén la parte afectada y reporta.
* Falta información que afecte contratos públicos, formatos de salida, arquitectura, seguridad o criterios de aceptación: detén la parte afectada y pregunta.
* Detalles internos (nombres privados, orden de auxiliares): sigue las convenciones existentes sin improvisar diseño. Registra cada elección relevante como `Asumido: …` en el cuerpo del commit y en el resumen. No lo uses para decisiones que requerían consulta.

## Referencias externas obligatorias (opcional)
* Nunca inventes comandos CLI de Cisco IOS-XE o Huawei VRP, salidas operativas de `show`/`display`, ni fórmulas de cálculo de QoS con constantes arbitrarias (ej. base 1024 o factores de sobreventa no declarados). Usa solo la sintaxis definida en la especificación, documentación oficial Cisco IOS-XE 17.x / Huawei VRP V200-V600 y los fixtures/golden files en `tests/golden/` y `tests/fixtures/`.
* Puedes parametrizar los valores previstos conservando la sintaxis de la referencia. Si falta una referencia necesaria, pregunta.
* No modifiques una referencia (`tests/golden/` o `tests/fixtures/`) para hacer pasar una implementación. Crear o actualizar una requiere autorización explícita de la especificación o del Responsable.

## Datos y secretos
* Sin datos reales de producción ni plantillas propietarias de operadores comerciales en código, pruebas, fixtures, ejemplos ni commits. Usa valores ficticios de laboratorio o rangos reservados (RFC 1918, RFC 5737 `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, ASNs privados `64512–65534`).
* Sin credenciales, claves ni tokens en el repositorio. Llegan solo por variables de entorno en tiempo de ejecución.

## Arquitectura
* Estructura: paquete raíz `src/intentfabric/` dividido en `domain/` (modelos inmutables, excepciones, derivaciones matemáticas puras, normalizador de interfaces), `application/` (puertos abstractos, catálogo de plugins, servicios de las 4 fases del pipeline y orquestador), `services/<s>/` (parsers de intención, validadores semánticos y estado esperado por servicio: `dia`, `l3vpn`, `l2vpn`), `vendors/<v>/` (definición del fabricante, escalado de unidades bps/kbps y plantillas Jinja2 por fabricante: `cisco`, `huawei`), `adapters/` (implementaciones de E/S: carga JSON/YAML, repositorio `inventory/topology.yaml`, motor Jinja2, transporte Netmiko/Simulado, parsers CLI y logger JSON/CSV) y `cli/` (entrypoint `argparse`).
* Dependencias permitidas: `domain/`, `application/`, `services/` y `vendors/` dependen exclusivamente de la biblioteca estándar de Python (`stdlib`); las librerías de terceros (`jinja2`, `pyyaml`, `netmiko`, `paramiko`, `textfsm`) están estrictamente confinadas en `adapters/`, verificado mediante análisis estático de AST en `tests/test_architecture.py`. `domain/` no importa de ninguna otra capa.
* Lógica de negocio sin efectos secundarios (red, archivos, entorno): esos accesos ocurren en los bordes (`adapters/` y `cli/`).
* Sin estado global mutable. Modelos inmutables (`@dataclass(frozen=True)`) y tipados estrictamente.
* Versión mínima del lenguaje: `Python >= 3.13` (entorno base `Python 3.14.2`) definida en `pyproject.toml` y alineada con `ADR-002`.

## Pruebas
* Todo cambio de comportamiento incluye pruebas. Para documentación o configuración sin comportamiento ejecutable, aplica la verificación que indique el paso, sin pruebas artificiales.
* Si aún no existen pruebas, `pytest` devuelve código 5: no es «en verde». Aplica la verificación del paso e indícalo en el resumen.
* No debilites, elimines ni alteres pruebas para ocultar un fallo.
* Una prueba de importación o de humo no sustituye una prueba funcional.
* Determinismo: misma entrada, misma salida ($f(x, \text{topo}) = y$). Orden explícito donde los datos puedan variar. Sin fechas actuales, aleatoriedad ni datos del entorno en salidas deterministas o cálculo de hashes SHA-256.
* Archivos de texto: encoding `UTF-8` y saltos de línea `\n` explícitos (`newline="\n"`).

## Comandos
Desde la raíz del repositorio.
| Acción | Comando |
| ------ | ------ |
| Crear entorno | `py -3.14 -m venv .venv` |
| Instalar dependencias | `.venv\Scripts\python -m pip install -r requirements.lock && .venv\Scripts\python -m pip install --no-deps -e .` |
| Pruebas | `.venv\Scripts\python -m pytest` |
| Lint / formato | `.venv\Scripts\python scripts/check_env.py && .venv\Scripts\python -m pytest tests/test_architecture.py` |

Comprueba que la versión activa del runtime cumple la versión mínima de «Arquitectura». No cambies de versión ni instales extras que la especificación no autorice. Si algo no puede ejecutarse por un requisito del entorno, reporta el bloqueo; no lo presentes como éxito.

## Git
Antes de editar: `git branch --show-current` y `git status`. Si estás en la rama principal, DETENTE y avisa. La rama corresponde a la tarea si su nombre incluye el `<id>`; si no, detente y avisa. No sobrescribas, descartes ni incluyas cambios ajenos; si impiden continuar, detén la parte afectada y avisa.

### Ramas
* Rama principal: `main`. Estable, con pruebas en verde. Nunca trabajes directo en ella.
* `docs/<id>/<slug>`, `feat/<id>/<slug>`, `fix/<slug>`, `chore/<slug>`. Sin `<id>`, el prompt indica la rama.
* `<slug>`: ASCII, minúsculas, guiones, sin tildes.

### Commits (puntos de control)
* Formato: `tipo(<id>): descripción`, en imperativo, sin tildes y minúsculas. Asunto de máximo 72 caracteres. Tipos: `feat`, `test`, `fix`, `docs`, `refactor`, `chore`. Sin `<id>`: `tipo: descripción`.
* Cada paso es un punto de control y puede abarcar varios commits atómicos y reversibles. Un commit no mezcla tareas.
* Los commits de pasos completados cumplen sus pruebas o verificación. Nunca crees commits ordinarios con pruebas en rojo.
* Antes de cada commit revisa `git diff --staged` e incluye solo lo de la tarea.
* WIP: `wip(<id>): descripción`, solo para conservar trabajo incompleto ante un bloqueo. El cuerpo indica qué falta y qué pruebas fallan. Un WIP no cumple la «Definición de hecho».
* Prohibido para ti: `push`, `merge`, `tag`, `rebase`, `reset --hard`, `push --force`, `clean`, `branch -D`. Las realiza solo el Responsable.

## Código y comentarios
* **Idioma:** identificadores en `inglés`; docstrings y comentarios en `español, sin tildes`. Los términos técnicos estándar no se traducen.
* **Nombres:** revelan intención. Evita abreviaturas crípticas, nombres genéricos (`data`, `tmp`, `util`) y prefijos de tipo.
* **Funciones:** una responsabilidad, pocos parámetros, nivel de abstracción uniforme. Si necesitas un comentario para explicar un bloque, extráelo a una función con nombre claro.
* **Sin duplicación:** extrae lo repetido solo con al menos tres usos o si el cambio debe ser simultáneo.
* **Errores:** explícitos y específicos heredando de `IntentFabricError`. Sin `except` genérico ni errores silenciados. Falla temprano con mensajes accionables.
* **Docstrings:** obligatorios en todo módulo, clase y función pública, incluidos pruebas y fixtures sin prefijo `_`. Una línea que diga qué hace. Amplía solo si el contrato no es evidente (precondiciones, excepciones, orden, determinismo). No repitas tipos ni parafrasees el nombre. No requeridos en privadas (`_`) ni anidadas.
* **Comentarios:** solo el porqué que el código no puede expresar (restricción, decisión no obvia, referencia a la especificación o a una referencia externa). Si renombrar o extraer basta, hazlo.
* Sin comentarios que narren lo obvio, sin código comentado, sin historial de cambios (para eso está git), sin separadores decorativos.
* Cada comentario ocupa de una a tres líneas. Si requiere más, va en el docstring del módulo o se reporta para documentarlo en la especificación.
* Un comentario que afirme el comportamiento de un sistema externo cita su fuente. Sin respaldo, no se escribe.
* Pendientes solo con referencia: `# TODO(<id>): descripción`. Sin TODO anónimos.
* En pruebas, el docstring enuncia el comportamiento que se garantiza, no cómo se prepara. Comenta solo preparaciones no evidentes.

## Walkthrough (opcional)
Tras entregar el «Resumen final», ayuda al Responsable a redactar `docs/walkthroughs/<id>.md`.
* **Contenido:** breve. Qué se implementó, por qué (enlazando la decisión que lo originó) y cómo funciona. Debe permitirle defenderlo oralmente; no es un listado de cambios (eso está en el Registro y en git). Si algo no es claro para explicarlo, pregunta en vez de suponer.
* **Git:** guárdalo en un commit propio `docs(<id>): agregar walkthrough`, aparte de los commits de implementación.
* No forma parte de la «Definición de hecho».

## Definición de hecho
Completa solo si: los criterios de aceptación se cumplen; las pruebas y verificaciones pasan; los cambios propios están en commits ordinarios (no WIP); el árbol está limpio (salvo cambios ajenos previos, que se conservan y se informan); no quedan bloqueos pendientes.

## Resumen final
Una línea por campo, sin narrar el proceso ni explicar el código. «—» si no hay nada que informar.
* Estado: completa | incompleta (qué falta)
* Pasos: completados / total
* Criterios: cumplidos / total
* Archivos: lista
* Verificaciones: comando → resultado
* Commits: hash y asunto del último
* Asumido: …
* Problemas y bloqueos: …