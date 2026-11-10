import { useEffect, useState } from "react";
import { api, type LevelReading, type TankDevice } from "../api/client";
import { dateTime, liters, percentLabel, signedLiters } from "../format";
import { useViewPeriod } from "../liveLevels";
import { POLL_MS } from "../policy";
import PeriodSwitch from "./PeriodSwitch";

export default function LevelChangesToday({ stationId }: { stationId: string }) {
  const { range } = useViewPeriod();
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

  const sinceMs = range.start.getTime();
  const untilMs = range.end.getTime();
  const followLive = range.includesNow;

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
        const next = await api.tankLevels(stationId, tankId, new Date(sinceMs).toISOString(), 5000);
        if (!live) return;
        setRows(next.filter((row) => new Date(row.recorded_at).getTime() < untilMs));
      } catch (err) {
        if (!live) return;
        setRows([]);
        setError(err instanceof Error ? err.message : "Не удалось загрузить журнал");
      } finally {
        if (live) setLoading(false);
      }
    }
    void load();
    if (!followLive) {
      return () => {
        live = false;
      };
    }
    const timer = window.setInterval(() => void load(), POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [stationId, tankId, sinceMs, untilMs, followLive]);

  if (devices.length === 0) {
    return (
      <section className="admin-level-log">
        <h3 className="admin-sub">{range.journalTitle}</h3>
        <p className="dash-muted">Резервуаров пока нет — журнал появится после добавления датчика.</p>
      </section>
    );
  }

  return (
    <section className="admin-level-log">
      <div className="admin-level-log-head">
        <div>
          <h3 className="admin-sub">{range.journalTitle}</h3>
          <PeriodSwitch />
        </div>
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
        В журнал попадает сдвиг от последнего записанного замера на 0,02 В и больше. Шум 0,01 В в базу не пишется.
      </p>
      {error ? <p className="tank-error">{error}</p> : null}
      {loading && rows.length === 0 ? <p className="dash-muted">Загрузка…</p> : null}
      {!loading && rows.length === 0 && !error ? (
        <p className="dash-muted">{range.emptyJournal}</p>
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
