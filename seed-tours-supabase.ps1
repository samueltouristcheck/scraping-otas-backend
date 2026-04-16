# Inserta los tours por defecto (Sagrada, Park Güell, etc.) en la base configurada en .env.supabase.local
# Ejecutar desde scraping-otas con el venv activado: .\seed-tours-supabase.ps1

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
        if ($key -eq "DATABASE_URL") { $env:DATABASE_URL = $val }
    }
}

if (-not $env:DATABASE_URL) {
    Write-Host "Falta DATABASE_URL en .env.supabase.local" -ForegroundColor Red
    exit 1
}

Write-Host "Sembrando tours en la base remota..." -ForegroundColor Cyan
python -m scripts.seed_monitored_tours
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "Listo. Recarga el dashboard en Vercel." -ForegroundColor Green
