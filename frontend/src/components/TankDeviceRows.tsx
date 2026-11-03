import { useEffect, useRef, useState } from "react";
import { api, type ShellyLink, type TankDevice } from "../api/client";
import { useCatalog } from "../catalog";
import { liters } from "../format";
import { tankSensorBadge, tankSensorLabel, usePublicLevels } from "../liveLevels";
import { useToast } from "./Toast";

type Row = {
  id: string;
  code: string;
  capacity: string;
  token: string;
  path: string;
  shellyHost: string;
  shelly: ShellyLink | null;
  zeroVolts: string;
  fullVolts: string;
  manualLiters: string;
  receiptLiters: string;
};

function messageOf(err: unknown): string {
  if (!(err instanceof Error) || !err.message) return "Не удалось сохранить";
  try {
    const parsed = JSON.parse(err.message) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* ответ не JSON */
  }
  return err.message;
}

function ingestUrl(path: string) {
  if (path.startsWith("http")) return path;
  return `${window.location.origin}${path}`;
}

export default function TankDeviceRows({ stationId }: { stationId: string }) {
  const { byCode } = usePublicLevels();
  const toast = useToast();
  const [rows, setRows] = useState<Row[]>([]);
  const [code, setCode] = useState("");
  const [capacity, setCapacity] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [expandedToolsId, setExpandedToolsId] = useState<string | null>(null);
  const shellyFresh = useRef<Record<string, number>>({});

  const catalog = useCatalog();
  const stationCode = catalog.stations.find((row) => row.id === stationId)?.code;
  const live = stationCode ? byCode.get(stationCode) : undefined;

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    api
      .tankDevices(stationId)
      .then((devices) => {
        if (!live) return;
        setRows(devices.map((device) => toRow(device)));
      })
      .catch((err) => {
        if (!live) return;
        setRows([]);
        setError(messageOf(err));
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [stationId]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      const started = Date.now();
      api
        .tankDevices(stationId)
        .then((devices) => {
          const byId = new Map(devices.map((device) => [device.id, device.shelly]));
          setRows((current) =>
            current.map((row) => {
              if (!byId.has(row.id)) return row;
              if ((shellyFresh.current[row.id] ?? 0) >= started) return row;
              return { ...row, shelly: byId.get(row.id) ?? null };
            })
          );
        })
        .catch(() => undefined);
    }, 8000);
    return () => window.clearInterval(timer);
  }, [stationId]);

  async function addTank() {
    const volume = Number(capacity.replace(",", "."));
    if (!code.trim() || !Number.isFinite(volume) || volume <= 0) {
      setError("Укажите код и объём в литрах");
      return;
    }
    setSavingId("new");
    setError(null);
    try {
      const created = await api.createTankDevice(stationId, {
        code: code.trim(),
        capacity_liters: volume,
      });
      setRows((current) => [...current, toRow(created)]);
      setCode("");
      setCapacity("");
      toast.ok(`Резервуар ${created.code} добавлен`);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSavingId(null);
    }
  }

  async function saveRow(row: Row) {
    const volume = Number(row.capacity.replace(",", "."));
    if (!row.code.trim() || !Number.isFinite(volume) || volume <= 0) {
      setError("Укажите код и объём в литрах");
      return;
    }
    setSavingId(row.id);
    setError(null);
    try {
      const updated = await api.updateTankDevice(stationId, row.id, {
        code: row.code.trim(),
        capacity_liters: volume,
      });
      setRows((current) =>
        current.map((item) =>
          item.id === row.id
            ? {
                ...toRow(updated),
                shellyHost: item.shellyHost,
                zeroVolts: item.zeroVolts,
                fullVolts: item.fullVolts,
                manualLiters: item.manualLiters,
              }
            : item
        )
      );
      toast.ok(`Резервуар ${row.code} сохранён`);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSavingId(null);
    }
  }

  async function removeRow(row: Row) {
    setSavingId(`del:${row.id}`);
    setError(null);
    try {
      await api.deleteTankDevice(stationId, row.id);
      setRows((current) => current.filter((item) => item.id !== row.id));
      toast.ok(`Резервуар ${row.code} удалён`);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSavingId(null);
    }
  }

  async function connectShelly(row: Row) {
    const host = row.shellyHost.trim();
    if (!host) {
      setError("Укажите IP Shelly");
      return;
    }
    setSavingId(`shelly:${row.id}`);
    setError(null);
    try {
      const updated = await api.connectShelly(stationId, row.id, host);
      shellyFresh.current[row.id] = Date.now();
      setRows((current) =>
        current.map((item) =>
          item.id === row.id
            ? { ...toRow(updated), code: item.code, capacity: item.capacity }
            : item
        )
      );
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSavingId(null);
    }
  }

  async function disconnectShelly(row: Row) {
    setSavingId(`shelly:${row.id}`);
    setError(null);
    try {
      const updated = await api.disconnectShelly(stationId, row.id);
      shellyFresh.current[row.id] = Date.now();
      setRows((current) =>
        current.map((item) =>
          item.id === row.id
            ? {
                ...toRow(updated),
                code: item.code,
                capacity: item.capacity,
                shellyHost: item.shellyHost,
              }
            : item
        )
      );
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSavingId(null);
    }
  }

  async function submitCalibration(row: Row) {
    const z = Number(row.zeroVolts.replace(",", "."));
    const f = Number(row.fullVolts.replace(",", "."));
    const cap = Number(row.capacity.replace(",", "."));
    if (!Number.isFinite(z) || !Number.isFinite(f) || z === f) {
      setError("Напряжения 0% и 100% должны быть разными числами");
      return;
    }
    setSavingId(`cal:${row.id}`);
    setError(null);
    try {
      await api.calibrateTank({
        station_id: stationId,
        tank_id: row.id,
        low_volts: z,
        low_percent: 0,
        high_volts: f,
        high_percent: 100,
        capacity_liters: Number.isFinite(cap) && cap > 0 ? cap : undefined,
      });
      toast.ok(`Калибровка ${row.code} сохранена (${z} В … ${f} В)`);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSavingId(null);
    }
  }

  async function submitManualLevel(row: Row) {
    const lit = Number(row.manualLiters.replace(",", "."));
    if (!Number.isFinite(lit) || lit < 0) {
      setError("Укажите корректный остаток в литрах (≥ 0)");
      return;
    }
    setSavingId(`lvl:${row.id}`);
    setError(null);
    try {
      await api.ingestLevel({
        station_id: stationId,
        tank_id: row.id,
        actual_remainder_liters: lit,
        recorded_at: new Date().toISOString(),
      });
      toast.ok(`Замер остатка ${row.code}: ${Math.round(lit)} л опубликован`);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSavingId(null);
    }
  }

  async function submitReceipt(row: Row) {
    const lit = Number(row.receiptLiters.replace(",", "."));
    if (!Number.isFinite(lit) || lit <= 0) {
      setError("Укажите принятый объём слива (> 0 л)");
      return;
    }
    setSavingId(`rec:${row.id}`);
    setError(null);
    try {
      await api.ingestReceipt({
        station_id: stationId,
        tank_id: row.id,
        volume_liters: lit,
        recorded_at: new Date().toISOString(),
      });
      setRows((current) =>
        current.map((item) =>
          item.id === row.id
            ? {
                ...item,
                receiptLiters: "",
                manualLiters: String(
                  Math.min(Number(item.capacity) || 20000, (Number(item.manualLiters) || 0) + lit)
                ),
              }
            : item
        )
      );
      toast.ok(`Приход ${Math.round(lit)} л принят на ${row.code}`);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSavingId(null);
    }
  }

  async function copyApi(row: Row) {
    const text = `${ingestUrl(row.path)}\nX-Device-Token: ${row.token}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(row.id);
    } catch {
      setCopied(null);
      setError("Не удалось скопировать адрес");
    }
  }

  return (
    <div className="tank-rows">
      <p className="dash-muted">
        Управление ёмкостями АГЗС: настройка объёма, подключение датчиков Shelly (с защитой от SSRF),
        калибровка вольтметра и ручной ввод фактического уровня или слива газовоза.
      </p>
      {loading ? <p className="dash-muted">Загрузка…</p> : null}
      {rows.map((row) => {
        const isExpanded = expandedToolsId === row.id;
        const measured = live?.tanks.find((tank) => tank.code === row.code);
        return (
          <div className="tank-block" key={row.id}>
            {measured ? (
              <p className="dash-muted">
                <span className={`badge ${tankSensorBadge(measured)}`}>{tankSensorLabel(measured)}</span>
                {" · "}
                {measured.remainder_liters == null
                  ? "количество газа ещё не пришло"
                  : `${liters(measured.remainder_liters)} из ${liters(measured.capacity_liters)}`}
                {measured.fill_percent != null ? ` · ${Math.round(measured.fill_percent)}%` : ""}
              </p>
            ) : null}
            <div className="tank-row">
              <label>
                Код резервуара
                <input
                  value={row.code}
                  onChange={(event) =>
                    setRows((current) =>
                      current.map((item) =>
                        item.id === row.id ? { ...item, code: event.target.value } : item
                      )
                    )
                  }
                />
              </label>
              <label>
                Объём, л
                <input
                  inputMode="decimal"
                  value={row.capacity}
                  onChange={(event) =>
                    setRows((current) =>
                      current.map((item) =>
                        item.id === row.id ? { ...item, capacity: event.target.value } : item
                      )
                    )
                  }
                />
              </label>
              <div className="tank-row-btns">
                <button
                  type="button"
                  className="btn small"
                  disabled={savingId === row.id}
                  onClick={() => saveRow(row)}
                >
                  Сохранить
                </button>
                <button
                  type="button"
                  className="btn secondary small"
                  onClick={() => setExpandedToolsId(isExpanded ? null : row.id)}
                >
                  {isExpanded ? "Скрыть замер/калибровку" : "Замер и калибровка"}
                </button>
                <button
                  type="button"
                  className="btn secondary small text-danger"
                  disabled={savingId === `del:${row.id}`}
                  onClick={() => removeRow(row)}
                >
                  Удалить
                </button>
              </div>
            </div>

            <form
              className="shelly-line"
              onSubmit={(event) => {
                event.preventDefault();
                void connectShelly(row);
              }}
            >
              <label>
                Shelly IP (локальная сеть датчика)
                <input
                  placeholder="192.168.0.104"
                  value={row.shellyHost}
                  onChange={(event) =>
                    setRows((current) =>
                      current.map((item) =>
                        item.id === row.id ? { ...item, shellyHost: event.target.value } : item
                      )
                    )
                  }
                />
              </label>
              <button
                type="submit"
                className="btn small"
                disabled={savingId === `shelly:${row.id}` || !row.shellyHost.trim()}
              >
                {savingId === `shelly:${row.id}`
                  ? "Проверяю…"
                  : row.shelly?.host === row.shellyHost.trim()
                    ? "Проверить"
                    : "Подключить"}
              </button>
              {row.shelly ? (
                <button
                  type="button"
                  className="btn secondary small"
                  disabled={savingId === `shelly:${row.id}`}
                  onClick={() => disconnectShelly(row)}
                >
                  Отключить
                </button>
              ) : null}
              <p className={row.shelly?.online ? "shelly-status online" : "shelly-status"}>
                {shellyText(row.shelly, savingId === `shelly:${row.id}`)}
              </p>
            </form>

            {isExpanded && (
              <div className="tank-tools-grid">
                <div className="tank-tool-box">
                  <strong>Ручной ввод остатка (публикуется на лэндинге)</strong>
                  <div className="tank-tool-inline">
                    <label>
                      Фактический остаток, л
                      <input
                        inputMode="decimal"
                        value={row.manualLiters}
                        onChange={(e) =>
                          setRows((cur) =>
                            cur.map((it) =>
                              it.id === row.id ? { ...it, manualLiters: e.target.value } : it
                            )
                          )
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="btn small"
                      disabled={savingId === `lvl:${row.id}`}
                      onClick={() => submitManualLevel(row)}
                    >
                      Обновить остаток
                    </button>
                  </div>
                </div>

                <div className="tank-tool-box">
                  <strong>Оформить приход / слив в резервуар</strong>
                  <div className="tank-tool-inline">
                    <label>
                      Принятый объём, л
                      <input
                        inputMode="decimal"
                        placeholder="4500"
                        value={row.receiptLiters}
                        onChange={(e) =>
                          setRows((cur) =>
                            cur.map((it) =>
                              it.id === row.id ? { ...it, receiptLiters: e.target.value } : it
                            )
                          )
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="btn small"
                      disabled={savingId === `rec:${row.id}`}
                      onClick={() => submitReceipt(row)}
                    >
                      Записать приход
                    </button>
                  </div>
                </div>

                <div className="tank-tool-box">
                  <strong>Калибровка датчика напряжения (0% … 100%)</strong>
                  <div className="tank-tool-inline">
                    <label>
                      0% (В)
                      <input
                        inputMode="decimal"
                        value={row.zeroVolts}
                        onChange={(e) =>
                          setRows((cur) =>
                            cur.map((it) =>
                              it.id === row.id ? { ...it, zeroVolts: e.target.value } : it
                            )
                          )
                        }
                      />
                    </label>
                    <label>
                      100% (В)
                      <input
                        inputMode="decimal"
                        value={row.fullVolts}
                        onChange={(e) =>
                          setRows((cur) =>
                            cur.map((it) =>
                              it.id === row.id ? { ...it, fullVolts: e.target.value } : it
                            )
                          )
                        }
                      />
                    </label>
                    <button
                      type="button"
                      className="btn secondary small"
                      disabled={savingId === `cal:${row.id}`}
                      onClick={() => submitCalibration(row)}
                    >
                      Калибровать
                    </button>
                  </div>
                </div>
              </div>
            )}

            <div className="tank-api">
              <span>API датчика</span>
              <code>{ingestUrl(row.path)}</code>
              <code>X-Device-Token: {row.token}</code>
              <button type="button" className="btn secondary small" onClick={() => copyApi(row)}>
                {copied === row.id ? "Скопировано" : "Копировать"}
              </button>
            </div>
          </div>
        );
      })}
      <div className="tank-block">
        <div className="tank-row">
          <label>
            Новый резервуар (код)
            <input
              placeholder="R-2"
              value={code}
              onChange={(event) => setCode(event.target.value)}
            />
          </label>
          <label>
            Объём, л
            <input
              placeholder="10000"
              inputMode="decimal"
              value={capacity}
              onChange={(event) => setCapacity(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="btn small"
            disabled={savingId === "new"}
            onClick={addTank}
          >
            Добавить резервуар
          </button>
        </div>
      </div>
      {error ? <p className="tank-error">{error}</p> : null}
    </div>
  );
}

function toRow(device: TankDevice, fallbackRemainder?: number): Row {
  return {
    id: device.id,
    code: device.code,
    capacity: String(device.capacity_liters),
    token: device.ingest_token,
    path: device.level_path,
    shellyHost: device.shelly?.host ?? "",
    shelly: device.shelly,
    zeroVolts: "0.5",
    fullVolts: "4.5",
    manualLiters: fallbackRemainder != null ? String(fallbackRemainder) : String(Math.round(device.capacity_liters * 0.5)),
    receiptLiters: "",
  };
}

function shellyText(link: ShellyLink | null, pending: boolean): string {
  if (pending) return "Проверяю Shelly…";
  if (!link) return "Сервер сам опросит прибор по этому IP.";
  if (!link.online) return link.last_error || "Нет связи";
  const parts = ["На связи"];
  if (link.model) parts.push(link.model);
  if (link.firmware) parts.push(link.firmware);
  if (link.rssi != null) parts.push(`${link.rssi} dBm`);
  if (link.volts != null) {
    parts.push(
      `${link.volts.toLocaleString("ru-RU", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })} В`
    );
  } else if (link.sensor_ready) {
    parts.push("напряжения нет");
  } else {
    parts.push("вольтметр не включён");
  }
  if (link.applied) parts.push("записано в остаток");
  else if (link.volts != null && !link.last_error) parts.push("в остаток после калибровки");
  else if (link.last_error) parts.push(link.last_error);
  return parts.join(" · ");
}
