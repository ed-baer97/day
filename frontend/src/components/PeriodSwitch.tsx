import { canShiftForward, localDateKey, shiftPeriod, todayPeriod, type PeriodPreset, type ViewPeriod } from "../period";
import { useViewPeriod } from "../liveLevels";

const PRESETS: { id: PeriodPreset; label: string }[] = [
  { id: "today", label: "Сегодня" },
  { id: "day", label: "День" },
  { id: "week", label: "Неделя" },
  { id: "month", label: "Месяц" },
];

export default function PeriodSwitch() {
  const { period, setPeriod, range } = useViewPeriod();
  const today = localDateKey(new Date());

  function select(preset: PeriodPreset) {
    if (preset === "today") {
      setPeriod(todayPeriod());
      return;
    }
    setPeriod({ preset, day: period.preset === "today" ? today : period.day });
  }

  function move(delta: number) {
    setPeriod(shiftPeriod(period, delta));
  }

  function pickDay(day: string) {
    const next: ViewPeriod = { preset: period.preset === "today" ? "day" : period.preset, day };
    setPeriod(day > today ? { ...next, day: today } : next);
  }

  return (
    <div className="period-switch">
      <div className="mini-tabs" role="group" aria-label="Период">
        {PRESETS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={period.preset === item.id ? "active" : ""}
            onClick={() => select(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {period.preset === "today" ? null : (
        <div className="period-nav">
          <button type="button" className="btn secondary small" onClick={() => move(-1)} aria-label="Предыдущий период">
            ‹
          </button>
          <input
            type="date"
            className="period-date"
            aria-label="Дата"
            max={today}
            value={period.day > today ? today : period.day}
            onChange={(event) => {
              if (event.target.value) pickDay(event.target.value);
            }}
          />
          <button
            type="button"
            className="btn secondary small"
            onClick={() => move(1)}
            disabled={!canShiftForward(period)}
            aria-label="Следующий период"
          >
            ›
          </button>
          <span className="dash-muted">{range.title}</span>
        </div>
      )}
    </div>
  );
}
