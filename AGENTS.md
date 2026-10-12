# AGENTS.md

## Proyecto
IntentFabric: framework determinista de aprovisionamiento y validación de servicios de red multivendor (DIA, L3VPN, L2VPN) sobre MPLS. Tesis de pregrado: la claridad y la trazabilidad pesan más que funcionalidad extra.

## Roles
- Implementación: ejecuta la Parte B del ADR indicado.
- Revisión (cuando el prompt lo indique): verifica la implementación contra los criterios de aceptación del ADR y reporta hallazgos. Puede agregar pruebas en tests/. No modifica src/ ni los ADR. Informa por criterio: cumple / no cumple / no comprobable, con la evidencia (comando o archivo).

## Cómo trabajar
- Implementa SOLO la Parte B del ADR indicado (docs/adr/). La Parte A es contexto y restricciones: no la reabras ni propongas alternativas durante la implementación.
- Problema no bloqueante en la decisión: repórtalo al final del resumen, sin cambiarla.
- Contradicción que impide implementar la Parte B o cumplir sus criterios: detén la parte afectada y reporta el bloqueo. No cambies la decisión por tu cuenta.
- Falta información que afecte contratos públicos, formatos de salida, arquitectura, seguridad o criterios de aceptación: detén la parte afectada y pregunta.
- Detalles internos (nombres privados, orden de funciones auxiliares): sigue las convenciones existentes, sin improvisar diseño. Anota los relevantes como "Asumido:".
- Edita solo lo que el ADR indica. En docs/adr/ edita únicamente la sección 10 del ADR en curso; nunca su Parte A ni su Estado. No crees docs/walkthroughs/: los redacta Johao.
- No agregues dependencias ni features fuera del ADR (sin LLMs, API, UI ni Docker).

## Comandos de red y configuraciones de referencia
- NUNCA inventes comandos CLI de Cisco IOS-XE ni Huawei VRP. Usa solo las configuraciones de referencia de tests/golden/.
- Puedes parametrizar los valores previstos por el ADR conservando la sintaxis de la referencia. No introduzcas comandos, opciones ni variantes sin respaldo. Si falta una referencia necesaria, pregunta.
- No modifiques un golden para hacer pasar una implementación. Crear o actualizar uno requiere autorización explícita del ADR o de Johao.

## Datos y secretos
- Sin datos reales de producción en código, pruebas, golden, ejemplos ni commits: nombres de nodos, identificadores de cliente, IPs reales. Usa valores de laboratorio o de documentación (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24, ASN privados 64512–65534).
- Sin credenciales, claves ni tokens en el repositorio. Las credenciales llegan solo por variables de entorno (ADR-010).

## Arquitectura (ADR-001)
- Paquete: src/intentfabric/. domain/ no importa ningún otro paquete del proyecto ni librerías de red.
- application/ define con Protocol los contratos de los adaptadores y no depende de sus implementaciones. Las dependencias entre paquetes siguen la tabla de ADR-001.
- Validación, generación y comparación son funciones puras: sin red, archivos ni otros efectos. El acceso a archivos, variables de entorno y equipos ocurre fuera del dominio.
- Sin estado global mutable. Type hints y dataclasses frozen en los modelos. CLI con argparse (biblioteca estándar).
- La versión mínima de Python vive en pyproject.toml y debe coincidir con ADR-002. Si AGENTS.md, pyproject.toml y los ADR son incompatibles, reporta la contradicción antes de modificar la configuración.

## Pruebas y determinismo
- Todo cambio de comportamiento incluye pruebas. Para documentación o configuración sin comportamiento ejecutable, aplica la verificación que indique el paso, sin pruebas artificiales.
- Si aún no existen pruebas, pytest termina con código 5 (ninguna recogida). No es un fallo ni "pruebas en verde": aplica la verificación del paso e indícalo en el resumen.
- La misma entrada produce exactamente la misma salida. Usa orden explícito donde el orden de los datos pueda variar. Sin fechas actuales, valores aleatorios ni datos del entorno en la salida determinista.
- Archivos de texto: lee y escribe con encoding="utf-8" y saltos de línea "\n" explícitos.
- Comprueba el determinismo con pruebas y usa tests/golden/ para las salidas de referencia.
- No debilites, elimines ni alteres pruebas para ocultar un fallo.
- Una prueba de importación no sustituye una prueba funcional ni una conexión real a un equipo.

## Comandos
Desde la raíz del repositorio. Los de instalación y pruebas aplican una vez que ADR-002 haya creado pyproject.toml.
- Crear entorno (Python 3.14, según ADR-002): `py -3.14 -m venv .venv`
- Activar en PowerShell: `.\.venv\Scripts\Activate.ps1`
- Verificar la versión activa: `python --version`
- Instalar con extras de desarrollo: `python -m pip install -e ".[dev]"`
- Pruebas: `python -m pytest -q`

`py -3.14` no garantiza un parche concreto: comprueba que la versión activa coincide con ADR-002. No cambies de versión de Python ni instales extras fuera del ADR indicado; usa solo las alternativas que ADR-002 autoriza y documenta su uso. Si las pruebas no pueden ejecutarse por un requisito pendiente del entorno, reporta el bloqueo; no lo presentes como pruebas en verde.

## Git
Antes de editar: `git branch --show-current` y `git status`. Si estás en main, DETENTE y avisa. Comprueba que la rama corresponde al ADR indicado. No sobrescribas, descartes ni incluyas cambios previos ajenos a la tarea; si impiden continuar o no puedes determinar su alcance, detén la parte afectada y avisa.

### Ramas
- main: estable y con pruebas en verde. Nunca trabajes directo en main.
- docs/adr-NNN-<slug>: redacción de un ADR. adr-NNN/<slug>: implementación (Johao la crea antes de ti). fix/<slug>, chore/<slug>.
- <slug>: ASCII, minúsculas, guiones, sin tildes. Ejemplo: adr-002/politica-dependencias.

### Commits (puntos de control)
- Formato: `tipo(adr-NNN): descripción`, en imperativo y minúsculas (conserva la grafía exacta de los identificadores técnicos). Asunto de máximo 72 caracteres. Tipos: feat, test, fix, docs, refactor, chore. Ejemplo: `feat(adr-003): agregar modelo DiaIntent`. Fuera de un ADR: `tipo: descripción`.
- Cada paso de la Parte B es un punto de control y puede abarcar varios commits coherentes, atómicos y reversibles. Un commit no mezcla ADR.
- Los commits de pasos completados cumplen sus pruebas o la verificación del paso (ver Pruebas). Nunca crees commits ordinarios con pruebas en rojo.
- Elección interna relevante no especificada: anótala en el cuerpo con `Asumido: …`. No lo uses para justificar decisiones que requerían consulta previa.
- Antes de cada commit revisa lo preparado (`git diff --staged`) e incluye solo lo de la tarea.
- WIP: `wip(adr-NNN): descripción`, solo para conservar trabajo incompleto ante un bloqueo o interrupción. El cuerpo indica qué falta y qué pruebas están pendientes o fallan; avísalo en el resumen. Un WIP no cumple la definición de hecho.
- Prohibido para ti: push, merge, tag, rebase, reset --hard, push --force, clean, branch -D. Las realiza solo Johao.

## Definición de hecho
La tarea está completa solo si: los criterios de aceptación del ADR están cumplidos; las pruebas y verificaciones de determinismo pasan; los cambios propios están en commits ordinarios; el árbol está limpio (salvo cambios ajenos previos, que se conservan y se informan); no quedan bloqueos ni WIP de la tarea.

Resumen final: pasos de la Parte B completados; archivos tocados; verificaciones y resultados; commits creados (hash y asunto del último); supuestos ("Asumido"); desviaciones, problemas y bloqueos. Si algo no se cumple, declara la tarea incompleta y qué falta.