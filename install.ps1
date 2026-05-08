# install.ps1 — Instala terraf y agrega al PATH del usuario
#
# Uso:
#   .\install.ps1

$ErrorActionPreference = "Stop"

# ── 1. Instalar el paquete ────────────────────────────────────────────────────
Write-Host "Instalando terraf..." -ForegroundColor Cyan
python -m pip install -e . -q

# ── 2. Encontrar el directorio Scripts de Python ──────────────────────────────
$scriptsDir = python -c "import sysconfig; print(sysconfig.get_path('scripts'))"

# ── 3. Verificar si ya está en PATH ──────────────────────────────────────────
$userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -split ";" -contains $scriptsDir) {
    Write-Host "El directorio ya está en PATH: $scriptsDir" -ForegroundColor Yellow
} else {
    $newPath = ($userPath.TrimEnd(";") + ";" + $scriptsDir)
    [System.Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Host "Agregado al PATH: $scriptsDir" -ForegroundColor Green
    Write-Host ""
    Write-Host "Reinicia tu terminal para que el cambio tome efecto." -ForegroundColor Yellow
}

# ── 4. Confirmar instalación ──────────────────────────────────────────────────
Write-Host ""
Write-Host "Listo. Ejecuta 'terraf --help' para comenzar." -ForegroundColor Green
