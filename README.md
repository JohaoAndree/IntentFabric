# IntentFabric

Framework determinista de aprovisionamiento y validación de servicios de red
multivendor (DIA, L3VPN y L2VPN) sobre MPLS. En esta etapa se configura el paquete
y se verifica el entorno; todavía no hay lógica de negocio ni conexión SSH real.

## Requisitos

- Entorno de referencia: Windows 11 y Python 3.14.2, según ADR-002.
- Git y PowerShell para los comandos de esta guía, ejecutados desde la raíz.
- Mínimo declarado del paquete: Python 3.13. Usar 3.13 como contingencia requiere
  diagnóstico y autorización de Johao; Python 3.15 no se utiliza en este ADR.

Las dependencias iniciales se resuelven con los rangos de `pyproject.toml`:
`PyYAML>=6.0`, `Jinja2>=3.1`, extra `dev` con `pytest>=8` y extra opcional `ssh`
con `netmiko>=4.8,<5`. No se impone un tope adicional a Paramiko.

## Instalación inicial

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
python -m pip install -e ".[dev]"
```

Comprueba que la versión activa sea **3.14.2**: `py -3.14` no fija el parche.
Si la activación falla, usa `.\.venv\Scripts\python.exe` en lugar de `python`
en los comandos siguientes. No cambies de intérprete sin aplicar la contingencia
del ADR y consultar a Johao.

Para verificar también la instalación e importación SSH en el mismo entorno:

```powershell
python -m pip install -e ".[ssh]"
```

## Instalación reproducible

En un entorno limpio con el mismo intérprete del registro de ADR-002, instala
usando el lock como archivo de restricciones:

```powershell
python -m pip install -c requirements.lock -e ".[dev]"
```

Si el alcance registrado del lock incluye SSH (`dev+ssh`):

```powershell
python -m pip install -c requirements.lock -e ".[dev,ssh]"
```

`requirements.lock` captura un entorno Windows con un intérprete concreto;
no garantiza reproducibilidad en otras plataformas o versiones de Python. Su
alcance y las versiones verificadas figuran en la sección 10 de
[ADR-002](docs/adr/ADR-002.md). Si el alcance es `dev, SSH pendiente`, el lock
solo cubre el entorno base y no permite afirmar que SSH sea reproducible.

## Verificación

```powershell
python scripts/check_env.py
python -m pytest -q
```

El script muestra Python, PyYAML, Jinja2, Netmiko y Paramiko en ese orden;
una librería ausente aparece como `no instalado` y el código de salida es 0.
Con Paramiko 5 o superior agrega una advertencia de compatibilidad SSH.
El test de Netmiko se omite si no está instalado: significa **no comprobado**.
Importar Netmiko no prueba una conexión real ni la compatibilidad con un equipo.

## Actualización deliberada del lock

Actualizar `requirements.lock` requiere autorización previa de Johao. No lo
regeneres durante una instalación reproducible. Tras la autorización, resuelve
los rangos en un entorno limpio con el intérprete de referencia, instala los
extras del alcance aprobado y repite el script y las pruebas. Si pasan, captura
`python -m pip freeze --exclude-editable` con UTF-8 y saltos LF:

```powershell
python -c "import pathlib, subprocess, sys; result = subprocess.run([sys.executable, '-m', 'pip', 'freeze', '--exclude-editable'], check=True, capture_output=True, text=True, encoding='utf-8'); pathlib.Path('requirements.lock').write_text(result.stdout, encoding='utf-8', newline='\n')"
```

Repite la instalación con `-c requirements.lock` en `.venv-verify`, ejecuta el
script y las pruebas, compara las versiones de las cuatro librerías con el lock
y elimina ese entorno temporal. Registra en la sección 10 de ADR-002 la fecha,
el intérprete, las versiones, el alcance, los resultados y el motivo del cambio.
