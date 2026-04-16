# Aplica migraciones Alembic contra la base Supabase.
# 1) Copia supabase-env.example → .env.supabase.local
# 2) Edita .env.supabase.local y pon DATABASE_URL con tu contraseña real
# 3) Ejecuta: .\apply-migrations-supabase.ps1
#
# O bien: $env:DATABASE_URL = "postgresql+asyncpg://..." ; .\apply-migrations-supabase.ps1

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
Set-Location $here

$localEnv = Join-Path $here ".env.supabase.local"
if (Test-Path $localEnv) {
    Get-Content $localEnv | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { return }
        $key = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim().Trim('"')
        if ($key -eq "DATABASE_URL") {
            $env:DATABASE_URL = $val
        }
    }
}

if (-not $env:DATABASE_URL) {
    Write-Host ""
    Write-Host "Falta DATABASE_URL." -ForegroundColor Yellow
    Write-Host "Opcion A: copia supabase-env.example a .env.supabase.local y edita la contraseña."
    Write-Host "Opcion B: `$env:DATABASE_URL = 'postgresql+asyncpg://...' ; .\apply-migrations-supabase.ps1"
    Write-Host ""
    exit 1
}

if ($env:DATABASE_URL -notmatch "postgresql\+asyncpg://") {
    Write-Host "DATABASE_URL debe usar el driver asyncpg: postgresql+asyncpg://..." -ForegroundColor Yellow
    exit 1
}

Write-Host "Ejecutando alembic upgrade head..." -ForegroundColor Cyan
alembic upgrade head
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Listo." -ForegroundColor Green
