# Цифровой след LPG

Сквозной контроль СУГ: завод → газовоз → АГЗС → резервуар → ТРК → продажа.  
Приоритет: сбор данных, цифровой след партии, физический баланс и детекция расхождений (не управление оборудованием).

## Структура

```
backend/          FastAPI, модели домена, REST + ingest
frontend/         React + MapLibre (визуальный язык LogHub)
docker-compose.yml  PostgreSQL (+ API)
docs (Agent Store)  план архитектуры / MVP
```

## Быстрый старт

### База

```bash
docker compose up -d db
```

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Health: `GET http://localhost:8000/health`  
OpenAPI: `http://localhost:8000/docs`

API prefix: `/api/v1` — stations, trucks, batches (+ trail), balance, events, ingest, map.

На MVP-0 роутеры отдают демо-данные в памяти; SQLAlchemy-модели и sketch миграции Alembic готовы к подключению Postgres в MVP-1.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

UI: `http://localhost:5173` — карта, панели газовоза/АГЗС, поиск цифрового следа партии.  
Тема и токены — по [LogHub](https://github.com/ed-baer97/LogHub) (Caspian/forest: `#0b100e`, teal `#2ec4b6`, Manrope + Fraunces).

### Тесты баланса

```bash
cd backend && pip install pytest && PYTHONPATH=. pytest tests/ -q
```

## Документация

- План архитектуры и MVP: Agent Store `docs/lpg-digital-trail-plan.md`
- Design reference LogHub: Agent Store `docs/loghub-design-reference.md`

## Цепочка учёта

```
Поставщик → Завод → Партия → Газовоз → Маршрут → АГЗС → Резервуар → Отпуск ТРК → Продажа
```

Баланс АГЗС: `остаток = предыдущий + приёмки − отпуски`; сверка с фактом уровня → события недостача / излишек / ошибка измерения / незарегистрированное движение.
