# Instala solo el entorno Python (sin Docker). Ejecutar desde scraping-otas.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Creado .env desde .env.example. Revisa DATABASE_URL si tu Postgres usa otro usuario/clave." -ForegroundColor Yellow
}

Write-Host "Creando .venv e instalando dependencias (API + Alembic, sin Playwright)..." -ForegroundColor Cyan
python -m venv .venv
& ".\.venv\Scripts\pip.exe" install --upgrade pip
& ".\.venv\Scripts\pip.exe" install -r requirements-api-local.txt

Write-Host "Listo. Siguiente: crea la base con scripts\init-local-db.sql (o equivalente) y ejecuta .\run-api-local.ps1" -ForegroundColor Green
