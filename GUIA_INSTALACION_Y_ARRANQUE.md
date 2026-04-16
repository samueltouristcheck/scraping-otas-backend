# Guia de instalacion y arranque - OTA Competitive Intelligence Platform

Esta guia explica, de principio a fin, como instalar dependencias, configurar variables de entorno y levantar el proyecto.

## 1. Requisitos previos

- Windows 10/11 (PowerShell)
- Python 3.12+
- Docker Desktop
- Git

Opcional pero recomendado:

- Entorno virtual (`.venv`)

## 2. Clonar e ingresar al proyecto

```powershell
git clone <URL_DEL_REPO>
cd scraping-otas
```

Si ya tienes el repo, solo entra al directorio:

```powershell
cd C:\Users\PC\Desktop\scraping-otas
```

## 3. Crear y activar entorno virtual

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Si PowerShell bloquea scripts, puedes permitirlos en la sesion actual:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 4. Instalar dependencias Python

```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

## 5. Instalar navegadores de Playwright

El proyecto usa Playwright para scraping.

```powershell
playwright install chromium
```

## 6. Configurar variables de entorno

Copia el archivo base y luego ajusta valores:

```powershell
copy .env.example .env
```

Variables clave de `.env`:

- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`
- `DATABASE_URL`
- `API_HOST`, `API_PORT`
- `FRONTEND_ORIGINS`
- `MONITORED_TOURS_JSON`
- `GYG_MONITORED_TOURS_JSON`
- `SCHEDULER_TZ`, `SCHEDULER_CRON`

Ejemplo local (ya viene en `.env.example`):

```env
POSTGRES_DB=ota_intel
POSTGRES_USER=ota_user
POSTGRES_PASSWORD=ota_password
POSTGRES_PORT=5432
DATABASE_URL=postgresql+asyncpg://ota_user:ota_password@localhost:5432/ota_intel
API_PORT=8000
```

## 7. Levantar base de datos (PostgreSQL) con Docker

```powershell
docker compose up -d postgres
```

Verifica que este healthy:

```powershell
docker compose ps
```

## 8. Ejecutar migraciones

```powershell
alembic upgrade head
```

## 9. Seed inicial de tours monitoreados

```powershell
python -m scripts.seed_monitored_tours
```

## 10. Formas de iniciar el proyecto

### Opcion A (recomendada): stack completo con Docker

Levanta API + scheduler + postgres:

```powershell
docker compose up --build
```

En segundo plano:

```powershell
docker compose up -d --build
```

### Opcion B: solo DB + API en Docker

Util para frontend local en `localhost:5173`:

```powershell
docker compose up -d postgres api
```

Health checks:

- `http://127.0.0.1:8001/api/v1/health`
- `http://127.0.0.1:8001/api/v1/health/db`
- `http://127.0.0.1:8001/api/v1/tours`

Nota: con esta opcion, el mapeo de puertos depende de `API_PORT` en tu `.env`.

### Opcion C: API local (sin contenedor API)

Con `.venv` activa y postgres arriba:

```powershell
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

API local:

- `http://127.0.0.1:8000/api/v1/health`

### Opcion D: Scheduler local

```powershell
python -m scheduler.runner
```

## 11. Ejecutar tests

```powershell
pytest
```

Puedes correr por carpeta:

```powershell
pytest tests/unit
pytest tests/integration
pytest tests/e2e
```

## 12. Comandos utiles de mantenimiento

Apagar servicios:

```powershell
docker compose down
```

Apagar y borrar volumen de datos:

```powershell
docker compose down -v
```

Reconstruir imagenes:

```powershell
docker compose build --no-cache
```

Ver logs de API:

```powershell
docker compose logs -f api
```

Ver logs de scheduler:

```powershell
docker compose logs -f scheduler
```

## 13. Troubleshooting rapido

### Error Docker Engine no disponible

Si aparece un error tipo:

`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`

Haz lo siguiente:

1. Abre Docker Desktop.
2. Espera a que termine de iniciar.
3. Verifica con `docker info`.
4. Reintenta `docker compose up -d postgres api`.

### Fallo por variables de entorno

- Verifica que exista `.env`.
- Revisa que `DATABASE_URL` apunte al host correcto (`localhost` para ejecucion local, `postgres` dentro de Docker Compose).

### Fallo de scraping por Playwright

- Reinstala navegador:

```powershell
playwright install chromium
```

## 14. Orden recomendado para primer arranque

1. Crear `.env` desde `.env.example`.
2. `docker compose up -d postgres`.
3. `alembic upgrade head`.
4. `python -m scripts.seed_monitored_tours`.
5. `docker compose up --build`.
6. Probar health endpoint.

---

Si quieres, se puede extender esta guia con una seccion especifica de desarrollo frontend + backend (Vite en `5173` y API en `8000/8001`) segun como lo estes corriendo en tu maquina.
