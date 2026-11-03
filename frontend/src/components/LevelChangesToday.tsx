import { useEffect, useState } from "react";
import { api, type LevelReading, type TankDevice } from "../api/client";
import { dateTime, liters, signedLiters } from "../format";

function startOfTodayIso() {
  const stamp = new Date();
  stamp.setHours(0, 0, 0, 0);
  return stamp.toISOString();
}

function percentLabel(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) return "—";
  const rounded = Math.round(value * 10) / 10;
  return `${rounded.toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
}

export default function LevelChangesToday({ stationId }: { stationId: string }) {
  const [devices, setDevices] = useState<TankDevice[]>([]);
  const [tankId, setTankId] = useState<string>("");
  const [rows, setRows] = useState<LevelReading[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;
    api
      .tankDevices(stationId)
      .then((list) => {
        if (!live) return;
        setDevices(list);
        setTankId((current) => current || list[0]?.id || "");
      })
      .catch(() => {
        if (!live) return;
        setDevices([]);
        setTankId("");
      });
    return () => {
      live = false;
    };
  }, [stationId]);

  useEffect(() => {
    if (!tankId) {
      setRows([]);
      setLoading(false);
      return;
    }
    let live = true;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const next = await api.tankLevels(stationId, tankId, startOfTodayIso());
        if (!live) return;
        setRows(next);
      } catch (err) {
        if (!live) return;
        setRows([]);
        setError(err instanceof Error ? err.message : "Не удалось загрузить журнал");
      } finally {
        if (live) setLoading(false);
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [stationId, tankId]);

  if (devices.length === 0) {
    return (
      <section className="admin-level-log">
        <h3 className="admin-sub">Изменения остатка сегодня</h3>
        <p className="dash-muted">Резервуаров пока нет — журнал появится после добавления датчика.</p>
      </section>
    );
  }

  return (
    <section className="admin-level-log">
      <div className="admin-level-log-head">
        <h3 className="admin-sub">Изменения остатка сегодня</h3>
        {devices.length > 1 ? (
          <select
            className="st-select"
            aria-label="Резервуар"
            value={tankId}
            onChange={(event) => setTankId(event.target.value)}
          >
            {devices.map((device) => (
              <option key={device.id} value={device.id}>
                {device.code}
              </option>
            ))}
          </select>
        ) : (
          <span className="dash-muted">Резервуар {devices[0]?.code}</span>
        )}
      </div>
      <p className="dash-muted">
        Публикуются смены остатка с полуночи по местному времени. Повторные пакеты Shelly с тем же
        уровнем скрыты.
      </p>
      {error ? <p className="tank-error">{error}</p> : null}
      {loading && rows.length === 0 ? <p className="dash-muted">Загрузка…</p> : null}
      {!loading && rows.length === 0 && !error ? (
        <p className="dash-muted">За сегодня смен остатка ещё не было.</p>
      ) : null}
      {rows.length > 0 ? (
        <div className="dash-table-wrap">
          <table className="dash-table">
            <thead>
              <tr>
                <th>Время</th>
                <th>Остаток</th>
                <th>%</th>
                <th>Изменение</th>
                <th>В</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{dateTime(row.recorded_at)}</td>
                  <td>{liters(row.remainder_liters)}</td>
                  <td>{percentLabel(row.fill_percent)}</td>
                  <td>
                    {row.delta_liters == null ? "старт дня" : signedLiters(row.delta_liters)}
                  </td>
                  <td>
                    {row.volts == null
                      ? "—"
                      : row.volts.toLocaleString("ru-RU", {
                          minimumFractionDigits: 2,
                          maximumFractionDigits: 2,
                        })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
