import { useMemo, useState } from "react";
import { phaseLabel } from "../format";
import { useSim } from "../sim/SimContext";
import type { MapPoint } from "../types";

export default function MapChrome({
  selectedId,
  onSelect,
}: {
  selectedId?: string | null;
  onSelect: (point: MapPoint) => void;
}) {
  const { overview, state } = useSim();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(true);

  const phaseByTruck = useMemo(() => {
    const m = new Map<string, string>();
    for (const t of state.trucks) m.set(t.detail.id, t.phase);
    return m;
  }, [state.trucks]);

  const items = useMemo(() => {
    const q = query.trim().toLowerCase();
    return overview.points
      .filter((p) => p.kind !== "truck" || !p.id.startsWith("alert-"))
      .filter((p) => !q || p.name.toLowerCase().includes(q) || p.kind.includes(q))
      .sort((a, b) => {
        const order = { factory: 0, station: 1, truck: 2 } as const;
        return order[a.kind] - order[b.kind] || a.name.localeCompare(b.name, "ru");
      });
  }, [overview.points, query]);

  return (
    <aside className={`map-chrome${open ? " open" : ""}`}>
      <div className="map-chrome-head">
        <div>
          <p className="kicker">Объекты</p>
          <strong>{overview.points.filter((p) => p.kind === "truck").length} газовозов</strong>
        </div>
        <button
          type="button"
          className="btn ghost small"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
        >
          {open ? "Свернуть" : "Список"}
        </button>
      </div>

      {open && (
        <>
          <div className="search-row">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Поиск АГЗС, завода, номера…"
              aria-label="Поиск объектов"
            />
          </div>

          <ul className="object-list">
            {items.map((p) => {
              const meta =
                p.kind === "truck"
                  ? phaseLabel(phaseByTruck.get(p.id))
                  : p.kind === "factory"
                    ? "завод"
                    : "АГЗС";
              return (
                <li key={p.id}>
                  <button
                    type="button"
                    className={`object-row${selectedId === p.id ? " active" : ""}`}
                    onClick={() => onSelect(p)}
                  >
                    <span className={`dot ${p.kind}`} aria-hidden />
                    <span className="object-name">{p.name}</span>
                    <em>{meta}</em>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="legend" aria-label="Условные обозначения">
            <span className="legend-item">
              <i className="dot factory" /> завод
            </span>
            <span className="legend-item">
              <i className="dot station" /> АГЗС
            </span>
            <span className="legend-item">
              <i className="dot truck" /> газовоз
            </span>
            <span className="legend-item">
              <i className="dot alert" /> расхождение
            </span>
          </div>
        </>
      )}
    </aside>
  );
}
