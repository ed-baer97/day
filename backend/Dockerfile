FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic.ini .
COPY alembic ./alembic

EXPOSE 8000
# ВАЖНО: держать --workers 1, пока в памяти процесса хранятся:
# - auth.py (_revoked_tokens, _failed_logins)
# - account_helpers.py (_SEEN_GPS)
# - board_cache.py и routers/map.py (локальные кэши)
# - edge_fleet.py (кольца релизов и heartbeat-ы станций)
# - shelly_link.py и фоновый shelly_poller (при >1 воркере нужен pg_try_advisory_lock или отдельный процесс)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
