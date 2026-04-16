# Scraping real (GYG + Viator): instala dependencias completas si hace falta, actualiza fuentes en BD y ejecuta un ciclo.
# Ejecutar desde la carpeta scraping-otas con:  Set-ExecutionPolicy -Scope Process Bypass; .\run-real-scrape.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# DATABASE_URL para Supabase (misma cadena que en Render). Opcional si solo usas Postgres local en .env
$supabaseLocal = Join-Path $PSScriptRoot ".env.supabase.local"
if (Test-Path $supabaseLocal) {
    Get-Content $supabaseLocal | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq "" -or $line.StartsWith("#")) { return }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) { return }
        $key = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim().Trim('"')
        if ($key -eq "DATABASE_URL") { $env:DATABASE_URL = $val }
    }
}

function Read-JsonEnv($relativePath) {
    $p = Join-Path $PSScriptRoot $relativePath
    if (-not (Test-Path $p)) { throw "No existe $p" }
    return ([IO.File]::ReadAllText($p, [Text.Encoding]::UTF8).Trim())
}

Write-Host "Comprobando entorno Python (necesitas requirements.txt completo + Playwright)..." -ForegroundColor Cyan
if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Host "Crea primero el venv: python -m venv .venv" -ForegroundColor Red
    exit 1
}

$py = ".\.venv\Scripts\python.exe"
& $py -c "import playwright" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando dependencias completas (puede tardar)..." -ForegroundColor Yellow
    & $py -m pip install -r requirements.txt
    & $py -m playwright install chromium
}

$env:GYG_MONITORED_TOURS_JSON = Read-JsonEnv "config\gyg_monitored.json"
$env:VIATOR_MONITORED_TOURS_JSON = Read-JsonEnv "config\viator_monitored.json"
$env:MONITORED_TOURS_JSON = Read-JsonEnv "config\monitored_tours_seed.json"
# Cobertura ~un mes de fechas por producto GYG (mas lento). Bajar a 7-14 si priorizas velocidad.
$env:GYG_DAILY_HORIZON_DAYS = "31"

Write-Host "Actualizando tours y fuentes OTA en la base..." -ForegroundColor Cyan
& $py -m scripts.seed_monitored_tours

Write-Host "Scraping GetYourGuide (sin ventana; puede tardar varios minutos)..." -ForegroundColor Cyan
& $py -c "import asyncio; from scheduler.jobs.getyourguide_job import run_getyourguide_cycle; asyncio.run(run_getyourguide_cycle())"

Write-Host "Scraping Viator (se abrira Chromium; Cloudflare puede pedir interaccion)..." -ForegroundColor Yellow
& $py -c "import asyncio; from scheduler.jobs.viator_job import run_viator_cycle; asyncio.run(run_viator_cycle())"

Write-Host "Actualizando snapshot JSON del listado Viator para el frontend..." -ForegroundColor Cyan
& $py -m scraping.viator.listing_scraper --no-headless --out data/viator_tours.json --url "https://www.viator.com/Barcelona-attractions/Sagrada-Familia/d562-a845"

Write-Host "Listo. Reinicia o recarga la API y el dashboard. Documentacion: REAL_SCRAPING.md" -ForegroundColor Green
