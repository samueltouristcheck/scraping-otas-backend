# Arranca la API en http://localhost:8001 sin Docker (PostgreSQL local en el puerto 5432).
# Requisitos: PostgreSQL instalado, base ota_intel y usuario en .env, y haber ejecutado setup-local.ps1 antes.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "No hay .venv. Ejecuta primero: .\setup-local.ps1" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Creado .env; revisa DATABASE_URL." -ForegroundColor Yellow
}

# Alembic lee DATABASE_URL del entorno; la app usa pydantic (.env) al arrancar uvicorn.
Get-Content ".env" -Encoding UTF8 | ForEach-Object {
    if ($_ -match '^\s*DATABASE_URL=(.+)\s*$') {
        $env:DATABASE_URL = $matches[1].Trim()
    }
}
if (-not $env:DATABASE_URL) {
    Write-Host "No hay DATABASE_URL en .env" -ForegroundColor Red
    exit 1
}

$py = ".\.venv\Scripts\python.exe"
$alembic = ".\.venv\Scripts\alembic.exe"
$uvicorn = ".\.venv\Scripts\uvicorn.exe"

Write-Host "Migraciones..." -ForegroundColor Cyan
& $alembic upgrade head

Write-Host "Seed de tours..." -ForegroundColor Cyan
& $py -m scripts.seed_monitored_tours

Write-Host "API en http://127.0.0.1:8001 (Ctrl+C para parar)" -ForegroundColor Green
& $uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload
