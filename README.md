# Цифровой след LPG

Сквозной контроль СУГ: завод → газовоз → АГЗС → резервуар → ТРК → продажа.  
Приоритет: сбор данных, цифровой след партии, физический баланс и детекция расхождений (не управление оборудованием).

## Структура

```
backend/            FastAPI, учёт, ingest, миграции Alembic
frontend/           React + MapLibre (визуальный язык LogHub)
desktop/            пульт колонок, PySide6, команда agzs-station --ui
docker-compose.yml  локальные PostgreSQL и API
deploy/             площадка: web (nginx), api, Postgres
```

## Быстрый старт (локально)

### База

```bash
docker compose up -d db
```

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

По умолчанию `ACCOUNT_STORE=memory`: заправки, резервуары, токены и шкала живут в памяти процесса.  
Тесты тоже идут в memory.

Health: `GET http://localhost:8000/health`  
OpenAPI: `http://localhost:8000/docs`  
API prefix: `/api/v1`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

UI: `http://localhost:5173` (прокси `/api` → `:8000`).  
Витрина раз в 15 секунд читает `GET /api/v1/public/levels`.  
Тема — по [LogHub](https://github.com/ed-baer97/LogHub) (Caspian/forest).

### Пульт колонок

Окно кассира — PySide6. Оно не встроено в сайт: смена, доза, пуск и стоп уходят на `http://127.0.0.1:5173/api/v1`. Сайт на 5173 проксирует запись на локальный API `8000`, в тестовую АГЗС `AGZS-TEST`. В существующую заправку эти данные не пишутся. На сервер пока не выкладываем.

```powershell
cd desktop
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[ui]"
$env:AGZS_ENV = "emulator"
$env:AGZS_PUMP_DRIVER = "emulator"
agzs-station --ui
```

Те же две переменные можно записать в `desktop/.env`. Вход в окне — логин владельца тестовой АГЗС, не логин платформы. Без `--ui` процесс только печатает, что касса готова.

### Тесты

```bash
cd backend && pip install pytest && PYTHONPATH=. pytest tests/ -q
```

## Учёт и режимы хранения

| Режим | Когда | Где данные |
|---|---|---|
| `ACCOUNT_STORE=memory` | локальный стенд, pytest | память; опционально снимок в `STATE_PATH` |
| `ACCOUNT_STORE=postgres` | площадка | Postgres; ключ, шкала, книга, история замеров |

На площадке при старте `api`:

1. применяются миграции Alembic;
2. если таблица станций пуста и есть `/data/state.json` — снимок один раз переносится в Postgres;
3. если файла нет — создаётся стартовая АГЗС Актау · 12 мкр.

Газовозы, партии и карта-симуляция на фронте пока не пишутся в Postgres.

## Вход

- `admin` из env (`ADMIN_USERNAME` / `ADMIN_PASSWORD`) видит все АГЗС и создаёт логины станций.
- Логин станции: `POST /api/v1/stations/{station_id}/users` (только admin). Пароль в ответе один раз, в базе — pbkdf2.
- Пользователь станции видит только свою заправку и свой `X-Device-Token`.
- `GET /api/v1/auth/me` отдаёт `role` (`admin` \| `station`) и `station_id`.

## Публичная витрина

`GET /api/v1/public/levels` — код, название, ёмкость, остаток, процент, время замера, `online`.

`online=false`, если замера нет дольше `SENSOR_STALE_SECONDS` (по умолчанию 60). Последний процент на сайте остаётся, подпись — «нет связи».

## Shelly Plus Uni

Прибор в сети станции сам шлёт напряжение наружу. Сервер до локального IP не ходит.

```
Shelly  --POST /api/v1/ingest/level-->  API  -->  Postgres
                              X-Device-Token
```

- URL берётся из `PUBLIC_BASE_URL` (в карточке резервуара поле `ingest_url`).
- Ключ — `X-Device-Token` с карточки резервуара.
- Если задан `INGEST_TOKEN`, запросы без валидного ключа резервуара или сессии отклоняются.
- Вольты → литры по двум точкам шкалы. Циферблат 5–95 %: ниже/выше этих рисок сайт не уходит.
- История: `GET /api/v1/stations/{id}/devices/{tank_id}/levels` (`since`, `changes_only`).
- В кабинете администратора блок «Изменения остатка сегодня» показывает смены уровня с полуночи (повторные пакеты Shelly с тем же остатком скрыты).
- Смена Wi‑Fi на Shelly не стирает скрипт; сброс к заводским — нужно залить снова.

Установка скрипта с машины в одной сети с прибором:

```bash
python backend/scripts/install_shelly_level.py \
  --shelly 192.168.0.104 \
  --url http://93.171.232.47/api/v1/ingest/level \
  --token КЛЮЧ_РЕЗЕРВУАРА
```

## Площадка

Сайт: [http://93.171.232.47](http://93.171.232.47).  
Имя `vds39595.vpsza500.kz` снаружи пока не резолвится — витрина и Shelly ходят на IP.

Каталог: `/opt/lpg`. Секреты только в `/opt/lpg/deploy/.env` (не в git). Образец: [`deploy/.env.example`](deploy/.env.example).

Снаружи порт 80. Nginx отдаёт фронт и проксирует `/api/` и `/health` в `api`. Postgres наружу не открыт.

```bash
cd /opt/lpg
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build
```

### Переменные площадки

| Переменная | Назначение |
|---|---|
| `POSTGRES_PASSWORD` | пароль БД |
| `ACCOUNT_STORE` | `postgres` на площадке |
| `PUBLIC_BASE_URL` | публичный адрес сайта для Shelly |
| `SENSOR_STALE_SECONDS` | порог «нет связи» (сек.) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | вход администратора |
| `AUTH_SECRET` | подпись сессий |
| `INGEST_TOKEN` | общий запасной ключ ingest (опционально) |
| `CORS_ORIGINS` | разрешённые origin для браузера |
| `STATE_PATH` | путь к JSON для разового импорта (`/data/state.json`) |

## Цепочка учёта

```
Поставщик → Завод → Партия → Газовоз → АГЗС → Резервуар → Колонка → Фискальная реализация
```

Баланс АГЗС: `остаток = предыдущий + приёмки − отпуски`; сверка с фактом уровня → недостача / излишек / ошибка измерения / незарегистрированное движение.

Одна поставка LPG связывает завод, газовоз, АГЗС и резервуар: отгруженный, доставленный, принятый, отпущенный и фискальный объём.
