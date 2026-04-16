# Crea .env.supabase.local desde la plantilla y abre el bloc de notas para que edites la URL.
# Ejecutar desde la carpeta scraping-otas: .\prepare-supabase-env.ps1

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
Set-Location $here

$example = Join-Path $here "supabase-env.example"
$target = Join-Path $here ".env.supabase.local"

if (-not (Test-Path $example)) {
    Write-Host "No encuentro supabase-env.example en $here" -ForegroundColor Red
    exit 1
}

if (Test-Path $target) {
    Write-Host "Ya existe .env.supabase.local — lo abro para editar." -ForegroundColor Cyan
} else {
    Copy-Item $example $target
    Write-Host "Creado .env.supabase.local — rellena TU_CONTRASEÑA y TU_PROJECT_REF, guarda y cierra." -ForegroundColor Cyan
}

notepad $target
