# Guía de Instalación — TibiaPilotNG

## Requisitos previos

### Software

| Herramienta | Versión | Notas |
|---|---|---|
| Windows | 10/11 | Obligatorio |
| Python | 3.11.7 exacta | Gestionado por `.python-version` |
| Poetry | 1.7.1+ | Gestor de dependencias |
| Tesseract OCR | cualquiera | Debe instalarse en la ruta por defecto |
| Arduino IDE | cualquiera | Para flashear el firmware |

### Hardware

- **Arduino Leonardo** (obligatorio) — conectado a **COM33** a **115200 baud**
- Resolución de pantalla: **1280×720** o **1920×1080** (autodetectado)

---

## Paso 1 — Instalar Tesseract OCR

1. Ir a https://github.com/UB-Mannheim/tesseract/wiki (mantenedor oficial de binarios para Windows)
2. Bajar el instalador más reciente de 64-bit, por ejemplo: `tesseract-ocr-w64-setup-5.x.x.exe`
3. Ejecutar el instalador — **dejar la ruta por defecto**:

```
C:\Program Files\Tesseract-OCR\
```

4. En "Additional language data" alcanza con dejar solo **English**
5. Verificar que funciona:

```bash
"C:\Program Files\Tesseract-OCR\tesseract.exe" --version
```

> La ruta está hardcodeada en `src/repositories/actionBar/core.py`. Si instalás en otro lugar, debés editar ese archivo.

---

## Paso 2 — Instalar Python 3.11.7

El proyecto requiere exactamente Python 3.11.7. Si tenés otra versión activa, Poetry fallará con un error de compatibilidad.

### Opción A — pyenv-win (recomendada)

```bash
pip install pyenv-win --target "$HOME/.pyenv"
```

Agregar al PATH en PowerShell como administrador:

```powershell
[System.Environment]::SetEnvironmentVariable("PYENV", "$env:USERPROFILE\.pyenv\pyenv-win", "User")
[System.Environment]::SetEnvironmentVariable("Path", "$env:USERPROFILE\.pyenv\pyenv-win\bin;$env:USERPROFILE\.pyenv\pyenv-win\shims;" + $env:Path, "User")
```

Reiniciar la terminal y luego:

```bash
pyenv install 3.11.7
pyenv local 3.11.7
```

### Opción B — Instalador oficial

1. Bajar `python-3.11.7-amd64.exe` desde https://www.python.org/downloads/release/python-3117/
2. Instalar (no es necesario marcar "Add to PATH" si no querés pisar tu versión actual)
3. Apuntar Poetry al ejecutable:

```bash
poetry env use "C:\Users\TU_USUARIO\AppData\Local\Programs\Python\Python311\python.exe"
```

### Verificar

```bash
python --version
# Python 3.11.7
```

---

## Paso 3 — Instalar Poetry

```bash
pip install poetry==1.7.1
```

Verificar:

```bash
poetry --version
```

---

## Paso 4 — Instalar dependencias del proyecto

Desde la raíz del proyecto:

```bash
poetry install
```

Esto instala todas las dependencias listadas en `pyproject.toml` en un virtualenv aislado.

---

## Solución de problemas — OpenCV (`ImportError: DLL load failed while importing cv2`)

Si al ejecutar `import cv2` ves `No se puede encontrar el módulo especificado`, en Windows suele faltar `MFPlat.DLL` (componente multimedia del sistema).

### 1) Ejecutar PowerShell como Administrador

`Get-WindowsCapability` y `Add-WindowsCapability` requieren elevación. Si no abrís la consola como admin, vas a ver:

`La operación solicitada requiere elevación.`

### 2) Verificar e instalar Media Feature Pack

En **PowerShell (Administrador)**:

```powershell
Get-WindowsCapability -Online | Where-Object Name -like "*Media*" | Select-Object Name,State
Add-WindowsCapability -Online -Name Media.MediaFeaturePack~~~~0.0.1.0
```

Si el paquete no aparece por nombre, instalalo desde:
- `Configuración` -> `Aplicaciones` -> `Características opcionales` -> `Agregar una característica` -> **Media Feature Pack**

### 3) Reiniciar Windows

El reinicio es necesario para que el DLL quede disponible globalmente.

### 4) Validar OpenCV en el virtualenv

```powershell
.\.venv311\Scripts\python.exe -c "import cv2; print(cv2.__version__)"
```

Si sigue fallando, verificá manualmente la existencia de:
- `C:\Windows\System32\mfplat.dll`

---

## Paso 5 — Flashear el Arduino Leonardo

### Bibliotecas de Arduino (obligatorio antes de compilar)

El sketch `arduino/arduino.ino` **no** trae las dependencias en el repo: hay que instalarlas con el **Gestor de bibliotecas** del Arduino IDE (**Sketch → Incluir biblioteca → Administrar bibliotecas…**, o el icono de bibliotecas en la barra lateral del IDE 2).

| Biblioteca | En el gestor | Notas |
|---|---|---|
| **ArduinoJson** | *ArduinoJson* — autor **Benoit Blanchon** | Si falla `ArduinoJson.h`, no está instalada. El código usa `DynamicJsonDocument` (API v6): instalá **versión 6.x** (p. ej. 6.21.5) desde el desplegable de versiones, o bien la última 7.x y cambiá en el `.ino` `DynamicJsonDocument doc(200)` por `JsonDocument doc`. |
| **USB Host Shield** | *USB Host Shield Library 2.0* (p. ej. Circuits@Home) | Aporta `hiduniversal.h` y el stack USB host. |
| **AbsMouse (ratón absoluto)** | *no hace falta el gestor* | Una copia mínima incluida en el repo (`arduino/TibiaPilotAbsMouse.h` / `.cpp`) sustituye la biblioteca [absmouse](https://github.com/jonathanedgecombe/absmouse) de Jonathan Edgecombe y evita conflictos con otros `HID.h`. Si instalaste *absmouse* por separado, podés desinstalarla para no duplicar lógica. |

Sin **ArduinoJson** la compilación termina con: `fatal error: ArduinoJson.h: No such file or directory`.

### Cargar el firmware

1. Abrir Arduino IDE
2. Abrir `arduino/arduino.ino`
3. Seleccionar placa: **Arduino Leonardo**
4. Seleccionar puerto: **COM33**
5. **Verificar** y luego **Subir** el sketch

> El bot manda comandos JSON al Arduino para simular mouse y teclado. Si el Arduino no está conectado o en COM33, las acciones de input no funcionarán.
>
> Si tu Arduino está en otro puerto, editá `src/utils/ino.py` y cambiá `COM33` por tu puerto.

---

## Paso 6 — (Opcional) Configurar pantalla virtual

Para correr el bot en segundo plano sin monitor físico:

1. Descomprimir el driver USB-MMID v2
2. En CMD como administrador:

```cmd
deviceinstaller64 install usbmmidd.inf usbmmidd
deviceinstaller64 enableidd 1
```

---

## Paso 7 — Configurar Tibia

El bot está hardcodeado para una configuración específica del cliente de Tibia:

- Resolución: **1280×720** o **1920×1080** (autodetectado por el bot)
- Hotkeys: F1–F12 para spells (ver screenshots en `README.md`)
- Action bar y HUD configurados según las capturas de pantalla del README
- Gráficos y efectos en la configuración correcta

---

## Paso 8 — Ejecutar el bot

```bash
poetry run python main.py
```

Se abre una ventana GUI con las páginas:
- **Configuration** — Backpacks, hotkeys
- **Cavebot** — Waypoints, opciones de criaturas
- **Healing** — Pociones, spells, items
- **ComboSpells** — Secuencias de spells
- **Inventory** — Vista de items actuales

La configuración se guarda automáticamente en `file.json`.

---

## Comandos útiles

```bash
# Ejecutar tests
poetry run pytest .

# Type checking
poetry run mypy

# Build ejecutable standalone
poetry run pyinstaller main.py
```

---

## Valores hardcodeados a verificar

| Valor | Archivo | Default |
|---|---|---|
| Puerto Arduino | `src/utils/ino.py` | `COM33` |
| Ruta Tesseract | `src/repositories/actionBar/core.py` | `C:\Program Files\Tesseract-OCR\tesseract.exe` |
| Resolución | varios archivos | `720p/1080p` (autodetectado) |
