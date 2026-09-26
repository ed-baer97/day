import { useSim } from "../sim/SimContext";
import Empty from "./Empty";

const CHAIN = [
  "supplier",
  "factory",
  "batch",
  "truck",
  "route",
  "station",
  "tank",
  "dispense",
  "sale",
];

export default function BatchTrailPanel() {
  const { state } = useSim();
  const { batch } = state;
  const events = [...batch.events].slice(-14).reverse();

  return (
    <div className="detail-embed">
      <div className="panel-head">
        <h2>Цифровой след</h2>
        <span className="badge ok">{batch.status}</span>
      </div>
      <div className="panel-body">
        <div style={{ marginBottom: 10, fontSize: 13 }}>
          <strong style={{ fontFamily: "var(--serif)" }}>{batch.trail_code}</strong>
          <div style={{ color: "var(--muted)", marginTop: 4 }}>
            {batch.volume_liters.toLocaleString("ru-RU")} л · {CHAIN.join(" → ")}
          </div>
        </div>
        {events.length === 0 ? (
          <Empty title="Ожидание событий" hint="Запустите симуляцию" />
        ) : (
          <ul className="trail-list">
            {events.map((ev) => (
              <li key={ev.id}>
                <span className="when">{new Date(ev.occurred_at).toLocaleString("ru-RU")}</span>
                <span className="title">
                  [{ev.node_type}] {ev.title}
                </span>
                {ev.description ? <span className="desc">{ev.description}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
