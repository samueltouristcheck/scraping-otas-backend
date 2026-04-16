# Scraping REAL contra la base de Supabase (la misma que usa la API en Render).
# Requisitos: .venv, requirements.txt + playwright install chromium, config/*.json.
# Uso: .\run-real-scrape-supabase.ps1
#
# Nota: el paso final genera data/viator_tours.json EN TU PC. En Render ese archivo no existe
# salvo que lo subas o montes volumen; el resto del dashboard (precios/disponibilidad) sí viene de la BD.

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
Set-Location $here

$localEnv = Join-Path $here ".env.supabase.local"
if (-not (Test-Path $localEnv)) {
    Write-Host "Crea .env.supabase.local con DATABASE_URL (ver supabase-env.example)." -ForegroundColor Red
    exit 1
}

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

if (-not $env:DATABASE_URL) {
    Write-Host "DATABASE_URL no encontrado en .env.supabase.local" -ForegroundColor Red
    exit 1
}

Write-Host "DATABASE_URL apunta a Supabase. Lanzando run-real-scrape.ps1 ..." -ForegroundColor Cyan
& (Join-Path $here "run-real-scrape.ps1")
