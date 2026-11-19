# Станционный узел АГЗС: Компьютер — АСКА-02 — Блок питания — УЗСГ-01 (`station-edge`)

Автономный узел и программный пульт управления для мини-ПК на заправке (Windows 10/11 или Linux), реализующий полный обмен по **Протоколу v3.10 («Искра 1.72», ООО «Техно Проект»)** с газораздаточной колонкой **УЗСГ-01 / УЗГС-01**:

1. **Телеметрия и учёт наливов:** опрашивает колонку командой «Тест» (`0x34`) через адаптер **АСКА-02** (FTDI FT232R, `9600 8N1`), разбирает 23-байтные кадры, корректно различает уставку дозы в поле `Price` (в литрах, деньгах или массе) и реально налитый объём в поле `Volume`.
2. **Работа с Блоком питания (БП) без Пульта управления (ПУ):** выполняет «Сброс» (`'07' → '05'`) командой `0x37` после завершения заправки (снижение расхода `< 4,5 л/мин` по РЭ п. 15.5 или 10-секундная отсечка по ДТФ по РЭ п. 5.3.4), поддерживает ручное управление кнопками колонки (`0.16`/`0.17`/`0.18`), задание дозы (`0x39`), «Пуск» (`0x35`), «Останов» (`0x36`), установку цены (`0.15`) и чтение счётчиков (`0.11`, `0.19`, `0.12`, `0.14`).
3. **Надёжное хранение и доставка на VPS:** сохраняет каждую закрытую заправку в локальную **SQLite WAL** (`station_edge.db`) и гарантированно доставляет на центральный сервер (`POST /api/v1/ingest/dispense` или пакетно `/dispenses/batch` с заголовком `X-Device-Token`) через очередь `outbox_queue` без дублей (`external_txn_id`).

---

## 1. Аппаратная схема: АСКА-02 + Блок питания + УЗСГ-01

### Почему без пульта требуется «Сброс» (`0x37`) после заправки
При замене штатного Пульта управления (ПУ) на связку **Блок питания (БП) + АСКА-02**:
- В БП нет процессора ПП2 и физических кнопок ПУ («СБРОС», «ПУСК», «СТОП»).
- По умолчанию на самой колонке кнопки «ПУСК/СТОП» активны (бит 6 байта 17 `Status` = `1`), а кнопка «СБРОС» на колонке **заблокирована** (бит 5 = `0`, байт 17 = `0x50`/`0x51`).
- После завершения заправки (при снижении расхода `< 4,5 л/мин` по РЭ п. 15.5 или при 10-секундной отсечке без жидкой фазы по ДТФ по РЭ п. 5.3.4) колонка переходит в состояние `'07'` («Останов») и ждёт от АСУ (ПК) команду **«Сброс» (`0x37`)** для возврата в `'05'` («Готовность»).
- **Штатный цикл с блоком питания** уже включён в `serve`: через 15 секунд после `'07'` уходит `0x37`, колонка возвращается в `'05'`. Пауза `'04'` не сбрасывается, повторный пуск остаётся за кнопкой «ПУСК». Команда `0x38` / `0.16` в этот цикл не входит: шесть цифр поля `Price` на живой колонке ещё не проверены. Ручной сброс: `python -m agzs_edge unlock`.

### Клеммник и подключение линий
- Съёмный клеммник (`XP1`) с проводами к **БУН** (насос `НАСОС+`/`НАСОС-` контакты А4/Б3) и кассе переносится со старого ПУ на Блок питания.
- Линия связи с АСКА-02 — два средних контакта разъёма `RJ-11` (контакты 2 и 3) к клемме «К АСКА 01». Если вторая зелёная лампа на АСКА-02 не мигает при передаче «Тест», поменять эти две жилы местами.

---

## 2. Быстрый старт и настройка (Windows 10/11 и Linux)

### Установка

```powershell
cd station-edge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

В `.env` настройте порт и привязку к VPS (`AGZS_SERIAL_PORT`, `AGZS_PUMP_ADDRESSES`, `AGZS_DEVICE_TOKEN`, `AGZS_STATION_ID`, `AGZS_TANK_ID`, `AGZS_DISPENSER_MAP`). Для блока питания вместо пульта в примере уже задан штатный цикл:

```ini
AGZS_READ_ONLY=0
AGZS_AUTO_RESET=1
AGZS_AUTO_RESET_DELAY_SEC=15.0
AGZS_AUTO_RESET_STOPPED_DELAY_SEC=0
AGZS_INTER_FRAME_DELAY_SEC=0.05
AGZS_COUNTER_RECONCILE_INTERVAL_SEC=0
AGZS_LOCK_BUTTONS_ON_UPDATE=0
```

- Адреса колонок в `AGZS_PUMP_ADDRESSES` поддерживаются в диапазоне `1..8`.
- `AGZS_AUTO_RESET_DELAY_SEC=15.0` даёт оператору и водителю время прочитать чередующиеся литры/сумму на табло после `'07'`. Пауза `'04'` по умолчанию не сбрасывается автоматически (`AGZS_AUTO_RESET_STOPPED_DELAY_SEC=0`), так как по РЭ п. 15.7.1–15.7.2 из неё допускается повторный пуск кнопкой «ПУСК».
- Автоматическая отправка команды `0x38` (`AGZS_LOCK_BUTTONS_ON_UPDATE=0`, `AGZS_COUNTER_RECONCILE_INTERVAL_SEC=0`) по умолчанию выключена до проверки 6-байтового формата поля `Price` на живом контроллере АСКА-02; при явном включении `AGZS_COUNTER_RECONCILE_INTERVAL_SEC > 0` служба в простое `'05'` сверяет счётчик (`0.11`) с таблицей `counter_audits`.

---

## 3. Команды CLI (`python -m agzs_edge`)

### Диагностика и мониторинг
- `diagnose` — проверка USB/FTDI, COM-порта, офлайн-кодека и разовый опрос «Тест» (`0x34`):
  ```powershell
  python -m agzs_edge diagnose --port COM7 --addr 1
  ```
- `probe` — опрос выбранного адреса или всех адресов `1..8` (включая подбор BCC `--checksum all`):
  ```powershell
  python -m agzs_edge probe --port COM7 --all-addresses
  ```
- `listen` — живой вывод 23-байтных кадров в консоль без записи в БД:
  ```powershell
  python -m agzs_edge listen --port COM7 --addr 1
  ```
- `watch-fill` — наблюдение одного налива до паузы без изменения БД и VPS:
  ```powershell
  python -m agzs_edge watch-fill --addr 1 --seconds 300
  ```

### Боевая служба учёта (блок питания вместо пульта)
- `serve` — опрос, расчёт `dispensed_ml`, запись в SQLite, отправка на VPS и возврат колонки из `'07'` в `'05'`:
  ```powershell
  python -m agzs_edge serve
  ```
- Проверка локальной БД и очереди на VPS / принудительная выгрузка:
  ```powershell
  python -m agzs_edge status
  python -m agzs_edge flush
  ```
- Вывод табло статистики по колонкам за смену (номер колонки, статус, время, объём, цена, сумма и итог за смену):
  ```powershell
  python -m agzs_edge monitor --once
  python -m agzs_edge monitor --shift-start-hour 8 --shift-hours 12
  ```
- Проверка всего контура без подключённой колонки (встроенный имитатор):
  ```powershell
  python -m agzs_edge serve --emulator --cycles 8 --no-sync
  python -m agzs_edge status
  ```

### Управление колонкой с ПК (Протокол v3.10)
- **Снять блокировку из `'07'`/`'04'` в `'05'` (команда `0x37`):**
  ```powershell
  python -m agzs_edge unlock --addr 1
  ```
- **Управление кнопками на корпусе УЗСГ-01 (команда `0x38`: `0.16` / `0.17` / `0.18`):**
  ```powershell
  python -m agzs_edge buttons --addr 1 --mode enable
  python -m agzs_edge buttons --addr 1 --mode disable
  python -m agzs_edge buttons --addr 1 --mode lock-reset
  ```
- **Задание дозы (`0x39`), ПУСК (`0x35`), ОСТАНОВ (`0x36`), цена (`0.15`), счётчики (`0.11`, `0.19`, `0.12`, `0.14`):**
  ```powershell
  python -m agzs_edge set-dose --addr 1 --liters 20
  python -m agzs_edge set-dose --addr 1 --full-tank
  python -m agzs_edge start --addr 1 --liters 20
  python -m agzs_edge stop --addr 1
  python -m agzs_edge set-price --addr 1 --price 72.00
  python -m agzs_edge counters --addr 1
  ```
- **Интерактивный пульт оператора на ПК:**
  ```powershell
  python -m agzs_edge console --addr 1
  ```

---

## 4. Табло статистики на мониторе Linux-сервера (`/dev/tty1` без GUI и без пароля)

Если на АГЗС стоит сервер Linux без графического интерфейса, команда `monitor --kiosk` позволяет при подключении монитора сразу выводить на экран `/dev/tty1` таблицу по колонкам (номер колонки, время, объём, цена, сумма и «ИТОГО ЗА СМЕНУ») без входа под паролем администратора. Скрипт открывает `station_edge.db` строго в режиме чтения (`read_only=True`).

### Настройка автозапуска на `/dev/tty1` через `systemd`

1. Создайте системного пользователя без shell (если `station-edge.service` работает под другим пользователем — добавьте права чтения на каталог `/opt/station-edge` и файл `station_edge.db` или запускайте оба сервиса от одного пользователя `station-edge`):
   ```bash
   sudo useradd -r -s /usr/sbin/nologin -G tty,dialout station-edge
   sudo chown -R station-edge:tty /opt/station-edge
   ```
2. Настройте смену в `/opt/station-edge/.env`:
   ```ini
   AGZS_SHIFT_START_HOUR=8
   AGZS_SHIFT_HOURS=12
   AGZS_MONITOR_REFRESH_SEC=2.0
   AGZS_CURRENCY=₸
   ```
3. Установите юнит [`station-edge-monitor.service`](station-edge-monitor.service) и вытесните экран ввода пароля `getty@tty1`:
   ```bash
   sudo cp /opt/station-edge/station-edge-monitor.service /etc/systemd/system/
   sudo systemctl disable --now getty@tty1.service
   sudo systemctl daemon-reload
   sudo systemctl enable --now station-edge-monitor.service
   ```
4. **Крупный шрифт, отключение затухания и защита от клавиатуры:**
   - Юнит автоматически применяет `setfont Uni3-TerminusBold24x12` (пакет `kbd` / `console-setup`) и `setterm -blank 0 -powerdown 0`, а также запускает монитор с флагом `--kiosk` (игнорирование `Ctrl+C`, `Ctrl+Z`, `Ctrl+\`).
   - Если управление сервером идёт только по SSH и нужно запретить переключение на `tty2`–`tty6` при подключении клавиатуры, задайте в `/etc/systemd/logind.conf`:
     ```ini
     NAutoVTs=1
     ReserveVT=1
     ```
     и выполните `sudo systemctl restart systemd-logind`.

---

## 5. Массовое обновление сотен АГЗС (Pull-Updater + Canary + Ansible)

Для безопасного обновления сотен мини-ПК за сотовым NAT (4G/CGNAT) без потери активных наливов предусмотрен двухуровневый контур:

1. **Graceful Shutdown в `station-edge.service` (`KillSignal=SIGTERM`, `TimeoutStopSec=180`):**
   - При остановке или рестарте демон не обрывает активный налив (`'01'`/`'02'`/`'03'`), а дожидается перехода колонки в останов, записи транзакции в `station_edge.db`, отправки авто-сброса `0x37` и выгрузки `outbox_queue` на VPS.
2. **Pull-автообновление во время простоя и 3 кольца раскатки (`python -m agzs_edge update` + `station-edge-updater.timer`):**
   - Поддерживаются 3 кольца: `ring0` (`canary`, 1–2 станции у инженера, обкатка сутки), `ring1` (10% станций, обкатка 1 смену) и `ring2` (`stable`, остальные 90% станций).
   - Каждые 10 минут (со случайным разбросом `RandomizedDelaySec=120`) таймер проверяет `GET /api/v1/ingest/edge/release`. Обновление запускается только во время **простоя станции** (нет активного налива `'01'`/`'02'`/`'03'` и прошло не менее `AGZS_UPDATE_IDLE_QUIET_SEC=60` секунд после последнего закрытого налива).
   - Во время установки и рестарта на диск рядом с БД записывается файл состояния `station_edge_update_state.json`: на мониторе `/dev/tty1` бесправного пользователя появляется окно **«ОБНОВЛЕНИЕ — КОЛОНКИ НЕДОСТУПНЫ»**, а при внезапном отключении питания `station-edge-updater.service` (`Before=station-edge.service`) при следующем включении сам возобновит и доведёт обновление до конца с авто-откатом при сбое.
   - Посмотреть статус всех станций сети: `GET /api/v1/ingest/edge/fleet`.

```bash
# Проверка наличия обновления на станции без установки
python -m agzs_edge update --check

# Запуск безопасного обновления в окно простоя (ожидание тишины и окончания налива до 180 секунд)
python -m agzs_edge update --wait-idle-sec 180 --restart-cmd "systemctl restart station-edge.service station-edge-monitor.service"

# Установка таймера, авто-возобновления при старте, udev-правила /dev/aska02 и юнита с Graceful Shutdown на Linux
sudo cp 99-aska02.rules /etc/udev/rules.d/ && sudo udevadm control --reload-rules && sudo udevadm trigger
sudo cp station-edge.service station-edge-updater.service station-edge-updater.timer /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable station-edge-updater.service && sudo systemctl enable --now station-edge-updater.timer
```

Для централизованной волновой раскатки (`serial: "20%"`) через Headscale / WireGuard используйте шаблоны [`../deploy/fleet/hosts.example.ini`](../deploy/fleet/hosts.example.ini) и [`../deploy/fleet/update-stations.yml`](../deploy/fleet/update-stations.yml).

---

## 6. Автотесты

```powershell
cd station-edge
pytest tests/ -q
```
