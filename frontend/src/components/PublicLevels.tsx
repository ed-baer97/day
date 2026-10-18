import { useEffect, useState } from "react";
import { api, type PublicStation } from "../api/client";
import { dateTime, liters } from "../format";
import Logo from "./Logo";

function percentLabel(value: number) {
  const rounded = Math.round(value * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toLocaleString("ru-RU", { maximumFractionDigits: 1 });
}

export default function PublicLevels({
  theme,
  onToggleTheme,
  onOpenApp,
}: {
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onOpenApp: () => void;
}) {
  const [stations, setStations] = useState<PublicStation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let live = true;

    async function load() {
      try {
        const rows = await api.publicLevels();
        if (!live) return;
        setStations(rows);
        setUpdatedAt(new Date());
        setError(null);
      } catch {
        if (!live) return;
        setError("Не удалось обновить уровни");
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
  }, []);

  return (
    <div className="public">
      <header className="public-bar">
        <div className="public-brand">
          <Logo size={36} alt="Цифровой след LPG" />
          <div>
            <p className="kicker">Открытые данные</p>
            <strong>Цифровой след LPG</strong>
          </div>
        </div>
        <div className="public-actions">
          <button type="button" className="btn secondary small" onClick={onToggleTheme}>
            {theme === "dark" ? "Светлая" : "Тёмная"}
          </button>
          <button type="button" className="btn small" onClick={onOpenApp}>
            Учёт
          </button>
        </div>
      </header>

      <main className="public-main">
        <p className="kicker">Заправки</p>
        <h1>Заполненность хранилищ</h1>
        <p className="public-lead">
          Сколько газа сейчас в резервуарах. Цифра обновляется по замеру датчика.
        </p>
        {updatedAt ? <p className="public-fresh">Обновлено {dateTime(updatedAt.toISOString())}</p> : null}
        {error ? <p className="tank-error">{error}</p> : null}

        <div className="public-grid">
          {stations.map((station) => (
            <article className="public-card" key={station.code}>
              <header>
                <h2>{station.name}</h2>
                <p>{station.address || station.code}</p>
              </header>
              {station.tanks.length === 0 ? (
                <p className="dash-muted">Резервуаров пока нет</p>
              ) : (
                station.tanks.map((tank) => {
                  const width = tank.fill_percent == null ? 0 : Math.max(0, Math.min(100, tank.fill_percent));
                  return (
                    <div className="public-tank" key={tank.code}>
                      <div className="public-tank-head">
                        <span>Резервуар {tank.code}</span>
                        <strong>{tank.fill_percent == null ? "—" : `${percentLabel(tank.fill_percent)}%`}</strong>
                      </div>
                      <div className="public-track" aria-hidden="true">
                        <i style={{ width: `${width}%` }} />
                      </div>
                      <p>
                        {tank.remainder_liters == null
                          ? "Замера ещё нет"
                          : `${liters(tank.remainder_liters)} из ${liters(tank.capacity_liters)}`}
                      </p>
                      <p className="dash-muted">
                        {tank.measured_at ? `Замер ${dateTime(tank.measured_at)}` : "Датчик ещё не присылал уровень"}
                      </p>
                    </div>
                  );
                })
              )}
            </article>
          ))}
        </div>
        {loading && stations.length === 0 ? <p className="dash-muted">Загрузка…</p> : null}
        {stations.length === 0 && !error && !loading ? <p className="dash-muted">Заправки появятся здесь.</p> : null}
      </main>
    </div>
  );
}
