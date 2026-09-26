import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { BatchTrail } from "../types";
import Empty from "./Empty";
import { useToast } from "./Toast";

export default function BatchTrailPanel() {
  const [code, setCode] = useState("LPG-2026-00041");
  const [trail, setTrail] = useState<BatchTrail | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();

  async function load(nextCode = code) {
    const q = nextCode.trim();
    if (!q) return;
    setBusy(true);
    try {
      const data = await api.trailByCode(q);
      setTrail(data);
      toast.ok(`След ${data.batch.trail_code}`);
    } catch (e) {
      setTrail(null);
      toast.err(e instanceof Error ? e.message : "Не найдено");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void load("LPG-2026-00041");
    // eslint-disable-next-line react-hooks/exhaustive-deps -- demo preload once
  }, []);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Цифровой след</h2>
      </div>
      <div className="panel-body">
        <div className="search-row">
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="LPG-…"
            aria-label="Код партии"
            onKeyDown={(e) => {
              if (e.key === "Enter") void load();
            }}
          />
          <button type="button" className="btn small" disabled={busy} onClick={() => void load()}>
            Найти
          </button>
        </div>

        {!trail ? (
          <Empty title="Партия не загружена" hint="Введите trail_code, напр. LPG-2026-00041" />
        ) : (
          <>
            <div style={{ marginBottom: 10, fontSize: 13 }}>
              <strong style={{ fontFamily: "var(--serif)" }}>{trail.batch.trail_code}</strong>
              <span className="badge ok" style={{ marginLeft: 8 }}>
                {trail.batch.status}
              </span>
              <div style={{ color: "var(--muted)", marginTop: 4 }}>
                {trail.batch.volume_liters.toLocaleString("ru-RU")} л · цепочка: {trail.chain.join(" → ")}
              </div>
            </div>
            <ul className="trail-list">
              {trail.events.map((ev) => (
                <li key={ev.id}>
                  <span className="when">{new Date(ev.occurred_at).toLocaleString("ru-RU")}</span>
                  <span className="title">
                    [{ev.node_type}] {ev.title}
                  </span>
                  {ev.description ? <span className="desc">{ev.description}</span> : null}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </section>
  );
}
