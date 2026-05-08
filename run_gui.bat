@echo off
REM Lanzador de TerraF GUI — sin necesidad de terraf.exe
REM Usa el Python de Anaconda directamente (no pasa por Scripts\)

cd /d "%~dp0"

REM Intentar con el python del PATH (Anaconda Prompt lo configura)
where python >nul 2>&1
if %ERRORLEVEL% == 0 (
    python -m terraf.gui.app
    goto :eof
)

REM Fallback: ruta fija de Anaconda
set CONDA_PYTHON=%USERPROFILE%\anaconda3\python.exe
if exist "%CONDA_PYTHON%" (
    "%CONDA_PYTHON%" -m terraf.gui.app
    goto :eof
)

REM Fallback: Miniconda
set CONDA_PYTHON=%USERPROFILE%\miniconda3\python.exe
if exist "%CONDA_PYTHON%" (
    "%CONDA_PYTHON%" -m terraf.gui.app
    goto :eof
)

echo ERROR: No se encontro Python. Abre Anaconda Prompt y ejecuta:
echo   python -m terraf.gui.app
pause
