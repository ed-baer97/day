import { useSim, type SimSpeed } from "../sim/SimContext";

const SPEEDS: SimSpeed[] = [1, 5, 20];

function fmtClock(iso: string) {
  try {
    return new Date(iso).toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function SimControls() {
  const { playing, speed, toggle, setSpeed, reset, state, overview } = useSim();
  const truckA = state.trucks[0];

  return (
    <div className="sim-bar panel">
      <div className="sim-bar-inner">
        <span className="kicker">Симуляция процесса</span>
        <div className="sim-controls">
          <button type="button" className="btn small" onClick={toggle}>
            {playing ? "Пауза" : "Старт"}
          </button>
          <button type="button" className="btn secondary small" onClick={reset}>
            Сброс
          </button>
          <div className="speed-group" role="group" aria-label="Скорость">
            {SPEEDS.map((s) => (
              <button
                key={s}
                type="button"
                className={`btn small${speed === s ? "" : " secondary"}`}
                onClick={() => setSpeed(s)}
              >
                {s}×
              </button>
            ))}
          </div>
        </div>
        <div className="sim-meta">
          <span>
            время <strong>{fmtClock(state.clockLabel)}</strong>
          </span>
          <span>
            фаза <strong>{truckA?.phase ?? "—"}</strong>
          </span>
          <span>
            партия <strong>{state.batch.trail_code}</strong>
          </span>
          <span>
            события <strong className={overview.open_events ? "text-danger" : ""}>{overview.open_events}</strong>
          </span>
        </div>
      </div>
    </div>
  );
}
