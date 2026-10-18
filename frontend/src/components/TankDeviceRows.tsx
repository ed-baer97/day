import { useEffect, useRef, useState } from "react";
import { api, type ShellyLink, type TankDevice } from "../api/client";

type Row = {
  id: string;
  code: string;
  capacity: string;
  token: string;
  path: string;
  shellyHost: string;
  shelly: ShellyLink | null;
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
  const [rows, setRows] = useState<Row[]>([]);
  const [code, setCode] = useState("");
  const [capacity, setCapacity] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const shellyFresh = useRef<Record<string, number>>({});

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    api
      .tankDevices(stationId)
      .then((devices) => {
        if (!live) return;
        setRows(devices.map(toRow));
      })
      .catch((err: unknown) => {
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
          item.id === row.id ? { ...toRow(updated), shellyHost: item.shellyHost } : item
        )
      );
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
          item.id === row.id ? { ...toRow(updated), code: item.code, capacity: item.capacity } : item
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
            ? { ...toRow(updated), code: item.code, capacity: item.capacity, shellyHost: item.shellyHost }
            : item
        )
      );
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
        Объём хранится на этой строке. Сервер сам опрашивает Shelly по IP. Напряжение попадает в
        остаток после калибровки.
      </p>
      {loading ? <p className="dash-muted">Загрузка…</p> : null}
      {rows.map((row) => (
        <div className="tank-block" key={row.id}>
          <div className="tank-row">
            <label>
              Код
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
            <button
              type="button"
              className="btn small"
              disabled={savingId === row.id}
              onClick={() => saveRow(row)}
            >
              Сохранить
            </button>
          </div>
          <form
            className="shelly-line"
            onSubmit={(event) => {
              event.preventDefault();
              void connectShelly(row);
            }}
          >
            <label>
              Shelly IP
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
          <div className="tank-api">
            <span>API</span>
            <code>{ingestUrl(row.path)}</code>
            <code>X-Device-Token: {row.token}</code>
            <button type="button" className="btn secondary small" onClick={() => copyApi(row)}>
              {copied === row.id ? "Скопировано" : "Копировать"}
            </button>
          </div>
        </div>
      ))}
      <div className="tank-block">
        <div className="tank-row">
          <label>
            Код
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
          <button type="button" className="btn small" disabled={savingId === "new"} onClick={addTank}>
            Добавить
          </button>
        </div>
      </div>
      {error ? <p className="tank-error">{error}</p> : null}
    </div>
  );
}

function toRow(device: TankDevice): Row {
  return {
    id: device.id,
    code: device.code,
    capacity: String(device.capacity_liters),
    token: device.ingest_token,
    path: device.level_path,
    shellyHost: device.shelly?.host ?? "",
    shelly: device.shelly,
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
