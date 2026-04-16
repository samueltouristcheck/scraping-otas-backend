# Scraping real (GetYourGuide + Viator)

## Qué hace falta

1. **Espacio en disco** (varios cientos de MB libres en el volumen del usuario). Si `playwright install chromium` falla con **ENOSPC / no space left on device**, libera espacio (archivos temporales, papelera, Docker imágenes viejas) y vuelve a ejecutar el comando.

2. **Python** con el entorno completo del proyecto (no solo `requirements-api-local.txt`):

   ```powershell
   cd c:\Users\touri\Desktop\Otas_TFT\scraping-otas
   .\.venv\Scripts\pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m playwright install chromium
   ```

3. **PostgreSQL** y **`.env`** con `DATABASE_URL` correcto (como en la guía principal del repo padre).

4. **Red estable**. Viator suele abrir **Chromium visible** (`headless=False`) por Cloudflare; puede pedir pasar un desafío o esperar unos segundos.

## Configuración de productos a vigilar

En la carpeta `config/` hay JSON de ejemplo (URLs públicas de Barcelona / Sagrada):

| Archivo | Uso |
|---------|-----|
| `gyg_monitored.json` | Lista para **GYG_MONITORED_TOURS_JSON** (job GetYourGuide). |
| `viator_monitored.json` | Lista para **VIATOR_MONITORED_TOURS_JSON** (job Viator, página de listado). |
| `monitored_tours_seed.json` | Lista para **MONITORED_TOURS_JSON** (seed de tours + fuentes en BD). |

Puedes **editar esos JSON** y cambiar URLs por otros productos/listados (mantén el formato). Los campos deben cumplir el modelo `MonitoredTourSource` (ver `models/dto/monitoring.py`).

Para **dejar fijo** en `.env` (sin script), copia el contenido de cada JSON **en una sola línea** en:

- `GYG_MONITORED_TOURS_JSON=...`
- `VIATOR_MONITORED_TOURS_JSON=...`
- `MONITORED_TOURS_JSON=...`

## Ejecución automática (recomendado)

Desde `scraping-otas`:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\run-real-scrape.ps1
```

El script:

1. Instala `requirements.txt` y Chromium si faltan.
2. Carga los tres JSON en variables de entorno.
3. Ejecuta `seed_monitored_tours` para crear/actualizar tours y fuentes OTA.
4. Lanza **un ciclo** de scraping GetYourGuide (headless).
5. Lanza **un ciclo** de scraping Viator (navegador visible).
6. Actualiza `data/viator_tours.json` con el listado (para el panel “Viator listing” en el frontend).

**Duración:** GetYourGuide recorre varios “horizontes” de días. `run-real-scrape.ps1` usa por defecto **`GYG_DAILY_HORIZON_DAYS=31`** (~un mes de fechas por producto; más lento). En `.env` puedes bajar a `7`–`14` si priorizas velocidad, o subir a `180` (muy lenta).

## Scheduler continuo (opcional)

Para ejecutar según cron (cada 2 h por defecto):

```powershell
$env:GYG_MONITORED_TOURS_JSON = [IO.File]::ReadAllText("$PWD\config\gyg_monitored.json").Trim()
$env:VIATOR_MONITORED_TOURS_JSON = [IO.File]::ReadAllText("$PWD\config\viator_monitored.json").Trim()
.\.venv\Scripts\python.exe -m scheduler.runner
```

Ajusta `SCHEDULER_CRON`, `VIATOR_SCHEDULER_CRON` y `SCHEDULER_RUN_ON_STARTUP` en `.env`.

## Después de scrapear

1. Arranca la API (`uvicorn` o Docker).
2. Recarga el frontend (`npm run dev`) y elige el tour correspondiente (p. ej. **Sagrada Familia – Regular / Large groups**).

## Legal y uso responsable

Respeta los términos de cada OTA, robots.txt y límites de uso. Este proyecto es para análisis competitivo autorizado.
