import { useSim, type SimSpeed } from "../sim/SimContext";

const SPEEDS: SimSpeed[] = [1, 5, 20];

export default function SimDock() {
  const { playing, speed, toggle, setSpeed, reset, state } = useSim();
  const clock = new Date(state.simTimeMs).toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div className="sim-dock" role="toolbar" aria-label="Управление симуляцией">
      <button
        type="button"
        className={`sim-btn primary${playing ? " is-playing" : ""}`}
        onClick={toggle}
        aria-pressed={playing}
      >
        {playing ? "Пауза" : "Пуск"}
      </button>

      <div className="sim-speeds" role="group" aria-label="Скорость">
        {SPEEDS.map((s) => (
          <button
            key={s}
            type="button"
            className={`sim-btn${speed === s ? " active" : ""}`}
            onClick={() => setSpeed(s)}
            aria-pressed={speed === s}
          >
            {s}×
          </button>
        ))}
      </div>

      <time className="sim-clock" dateTime={new Date(state.simTimeMs).toISOString()}>
        {clock}
      </time>

      <button type="button" className="sim-btn" onClick={reset}>
        Сброс
      </button>
    </div>
  );
}
