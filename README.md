# Цифровой след LPG

Сквозной контроль СУГ: завод → газовоз → АГЗС → резервуар → ТРК → продажа.  
Приоритет: сбор данных, цифровой след партии, физический баланс и детекция расхождений (не управление оборудованием).

## Структура

```
backend/            FastAPI, учёт, ingest, миграции Alembic
frontend/           React + MapLibre (визуальный язык LogHub)
station-edge/       автономный узел станции: опрос УЗГС-01 через АСКА-02 (Искра 1.72), локальная БД SQLite и отправка отпусков на VPS
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

### Станционный узел АСКА-02 + УЗГС-01 (`station-edge/`)

Автономный пакет для компьютера на АГЗС (Windows 10/11 и Linux), к которому кабелем USB подключён адаптер **АСКА-02** (`FTDI FT232R`, порт `COM7` / `/dev/ttyUSB0`, линия `9600 8N1`).

- **Только чтение (безопасность):** шлёт исключительно команду «Тест» протокола **Искра 1.72** (код `4`, адреса `1–6`). Пуск, дозу и стоп на живую колонку компьютер не отправляет (газ включает пистолет и кнопка на пульте УЗГС-01).
- **Разбор 23-байтного кадра и расчёт `dispensed_ml`:**
  - *Обычная доза*: поле объёма в кадре — остаток, оно уменьшается (`отпущено = задали − осталось`; например, задали `20 000 мл`, в кадре `12 500` — налито `7 500 мл`).
  - *«До полного»*: дозы заранее нет, поле объёма уже содержит отпущенные миллилитры.
- **Локальная БД и очередь на VPS:** закрытая заправка пишется как `dispensed_ml` в локальную `station_edge.db` (SQLite WAL) и ставится в очередь `outbox_queue` для отправки на `POST /api/v1/ingest/dispense` или пакетно на `POST /api/v1/ingest/dispenses/batch` (`X-Device-Token`). Повторная отправка того же `external_txn_id` не создаёт вторую заправку на VPS. Воркер `OutboxSyncWorker` автоматически объединяет накопившиеся заправки в пакеты до 50 штук за 1 HTTP-запрос.

```powershell
cd station-edge
pip install -r requirements.txt
Copy-Item .env.example .env

# Разовый опрос адресов 1..6 командой «Тест» (проверка живой пары «К АСКА 01» на средних контактах RJ-11):
python -m agzs_edge probe --port COM7 --all-addresses

# Боевой запуск на станции (COM7 -> SQLite -> VPS):
python -m agzs_edge serve

# Проверка на Windows без колонки (встроенный имитатор кадров):
python -m agzs_edge serve --emulator --cycles 8 --no-sync
python -m agzs_edge status
```

Подробная памятка по клеммам «К АСКА 01», контактам RJ-11, индикаторам АСКА-02 и калибровке смещений кадра — в [`station-edge/README.md`](station-edge/README.md).

### Тесты

```bash
cd backend && pip install pytest && PYTHONPATH=. pytest tests/ -q
cd ../station-edge && PYTHONPATH=. pytest tests/ -q
```

## Учёт и режимы хранения

| Режим | Когда | Где данные |
|---|---|---|
| `ACCOUNT_STORE=memory` | локальный стенд, pytest | память; опционально снимок в `STATE_PATH` |
| `ACCOUNT_STORE=postgres` | площадка (высокая нагрузка, `workers > 1`) | Postgres: станции, газовозы, резервуары, токены, шкала, книга, замеры уровня (`level_readings`), транзакции отпуска (`dispense_records`) и приёмки (`receipt_records`) с индексами и строковой блокировкой `FOR UPDATE` |

На площадке при старте `api`:

1. применяются миграции Alembic (`0001`–`0003`);
2. если таблица станций пуста и есть `/data/state.json` — снимок один раз переносится в Postgres;
3. если файла нет — создаётся стартовая АГЗС Актау · 12 мкр.

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
