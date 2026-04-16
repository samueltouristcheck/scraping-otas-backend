-- Ejecutar UNA VEZ como superusuario de PostgreSQL, por ejemplo:
--   "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -f scripts/init-local-db.sql
-- Si el usuario o la base ya existen, ignora el error o adapta los nombres.

CREATE USER ota_user WITH PASSWORD 'ota_password';
CREATE DATABASE ota_intel OWNER ota_user;
