# Terraf

Terraf es una herramienta de exploración minera desde escritorio. Permite el procesamiento espectral, manejo de base de datos de exploración, y cuenta con una interfaz gráfica (GUI) y de línea de comandos (CLI).

## Requisitos
- Python >= 3.10

## Instalación

Puedes instalar Terraf y sus dependencias de manera local:

```bash
# Instalación básica
pip install -e .

# Instalación con soporte para la interfaz gráfica (GUI)
pip install -e .[gui]

# Instalación con todas las dependencias (GUI y Machine Learning)
pip install -e .[all]
```

Para una instalación rápida en Windows, también puedes ejecutar el script de PowerShell proporcionado:
```powershell
.\install.ps1
```

## Uso

Terraf ofrece dos modos de uso principales:

### 1. Interfaz de Línea de Comandos (CLI)
Una vez instalado, puedes usar el comando `terraf` desde tu terminal:
```bash
terraf --help
```

### 2. Interfaz Gráfica (GUI)
Para abrir la interfaz gráfica, puedes usar el comando:
```bash
terraf-gui
```
O simplemente ejecutar el script:
```cmd
run_gui.bat
```

## Estructura del Proyecto
- `src/terraf`: Código fuente principal de la aplicación.
- `spectraf`: Librería de procesamiento espectral.
- `terraf.toml`: Archivo de configuración principal.
- `pyproject.toml`: Configuración de dependencias y construcción del proyecto Python.

## Notas
Los archivos de configuración locales, bases de datos (`*.db`), y los resultados de procesamiento no se incluyen en el control de versiones por defecto.
