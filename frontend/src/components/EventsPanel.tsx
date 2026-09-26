import { useSim } from "../sim/SimContext";
import Empty from "./Empty";

export default function EventsPanel() {
  const { state } = useSim();
  const open = state.events.filter((e) => !e.is_resolved);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Расхождения</h2>
        {open.length > 0 ? <span className="badge danger">{open.length}</span> : null}
      </div>
      <div className="panel-body" style={{ maxHeight: 180 }}>
        {open.length === 0 ? (
          <Empty title="Нет открытых событий" hint="Недостача/излишек появятся ближе к концу цикла" />
        ) : (
          <ul className="trail-list">
            {open.map((ev) => (
              <li key={ev.id}>
                <span className="when">{new Date(ev.detected_at).toLocaleString("ru-RU")}</span>
                <span className="title" style={{ color: "var(--coral)" }}>
                  {ev.title} · {ev.delta_liters ?? "—"} л
                </span>
                <span className="desc">{ev.description}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
