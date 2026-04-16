# Crea el rol ota_user y la base ota_intel (conexion como postgres en localhost:5432).
# Busca psql en rutas habituales (PostgreSQL oficial o bundle HikCentral).
$ErrorActionPreference = "Stop"
$candidates = @(
    "${env:ProgramFiles(x86)}\HikCentral\VSM Servers\PostgreSQL\bin\psql.exe"
    "${env:ProgramFiles}\PostgreSQL\16\bin\psql.exe"
    "${env:ProgramFiles}\PostgreSQL\17\bin\psql.exe"
)
$psql = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $psql) {
    $found = Get-ChildItem "${env:ProgramFiles}\PostgreSQL" -Recurse -Filter "psql.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
    if ($found) { $psql = $found }
}
if (-not $psql) {
    Write-Host "No se encontro psql.exe. Instala PostgreSQL o usa pgAdmin y ejecuta scripts/init-local-db.sql" -ForegroundColor Red
    exit 1
}
Write-Host "Usando: $psql" -ForegroundColor Gray
$sqlRole = @'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ota_user') THEN
    CREATE ROLE ota_user WITH LOGIN PASSWORD 'ota_password';
  END IF;
END $$;
'@
& $psql -U postgres -h 127.0.0.1 -p 5432 -d postgres -v ON_ERROR_STOP=1 -c $sqlRole
$exists = & $psql -U postgres -h 127.0.0.1 -p 5432 -d postgres -tAc "SELECT EXISTS (SELECT FROM pg_database WHERE datname = 'ota_intel')"
if ($exists -ne 't') {
    & $psql -U postgres -h 127.0.0.1 -p 5432 -d postgres -v ON_ERROR_STOP=1 -c "CREATE DATABASE ota_intel OWNER ota_user;"
}
Write-Host "Listo: usuario ota_user y base ota_intel." -ForegroundColor Green
