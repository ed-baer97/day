import { useEffect, useState } from "react";
import {
  api,
  type CatalogStation,
  type ColumnsMode,
  type EdgeNodeStatus,
} from "../../api/client";
import { messageOf, useCatalog } from "../../catalog";
import { dateTime } from "../../format";

const MODES: { value: ColumnsMode; label: string; hint: string }[] = [
  {
    value: "none",
    label: "Отключены",
    hint: "Учёт только по уровню резервуара",
  },
  {
    value: "virtual",
    label: "Виртуальные",
    hint: "Расчёт по снижению уровня (авто-перехват при поступлении station-edge)",
  },
  {
    value: "edge",
    label: "Реальные ТРК (Edge)",
    hint: "Только реальные транзакции АСКА-02 / УЗСГ-01 и честная сверка Δ с датчиком",
  },
];

export default function StationColumnsCard({
  station,
  edgeNode,
  onSaved,
  toast,
}: {
  station: CatalogStation;
  edgeNode?: EdgeNodeStatus | null;
  onSaved?: () => void;
  toast: { ok: (message: string) => void };
}) {
  const { saveStation } = useCatalog();
  const [mode, setMode] = useState<ColumnsMode>(station.columns_mode ?? "none");
  const [count, setCount] = useState<number>(station.columns_count ?? 2);
  const [recentDispensesCount, setRecentDispensesCount] = useState<number | null>(null);
  const [lastDispenseAt, setLastDispenseAt] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setMode(station.columns_mode ?? "none");
    setCount(station.columns_count ?? 2);
  }, [station.id, station.columns_mode, station.columns_count]);

  useEffect(() => {
    let alive = true;
    const since = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
    api
      .stationDispenses(station.id, since, 50)
      .then((rows) => {
        if (!alive) return;
        setRecentDispensesCount(rows.length);
        setLastDispenseAt(rows[0]?.finished_at ?? rows[0]?.started_at ?? null);
      })
      .catch(() => {
        if (!alive) return;
        setRecentDispensesCount(null);
        setLastDispenseAt(null);
      });
    return () => {
      alive = false;
    };
  }, [station.id]);

  async function persistColumns(nextMode: ColumnsMode, nextCount: number) {
    setSaving(true);
    setError(null);
    try {
      await saveStation(station.id, {
        code: station.code,
        name: station.name,
        address: station.address ?? null,
        lat: station.lat,
        lon: station.lon,
        is_active: station.is_active,
        columns_mode: nextMode,
        columns_count: nextMode === "none" ? nextCount : Math.max(1, Math.min(8, nextCount)),
      });
      toast.ok(
        nextMode === "none"
          ? "Колонки отключены"
          : nextMode === "virtual"
            ? `Включены виртуальные колонки (${nextCount})`
            : `Включены реальные ТРК station-edge (${nextCount})`
      );
      onSaved?.();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setSaving(false);
    }
  }

  const edgeDetected = (recentDispensesCount ?? 0) > 0 || !!edgeNode;
  const dirty =
    mode !== (station.columns_mode ?? "none") || count !== (station.columns_count ?? 2);

  return (
    <section className="dash-card">
      <div className="card-head-inline">
        <div>
          <h3 style={{ margin: 0 }}>Колонки (ТРК): виртуальные и реальные</h3>
          <p className="dash-muted" style={{ margin: "4px 0 0" }}>
            Виртуальные колонки оценивают отпуск по падению уровня резервуара до установки
            адаптера АСКА-02. Переключение на реальные ТРК выполняется без правки кода.
          </p>
        </div>
        <span
          className={`badge ${
            mode === "edge" ? "ok" : mode === "virtual" ? "warn" : ""
          }`}
        >
          {mode === "edge"
            ? `Реальные ТРК · ${count} кол.`
            : mode === "virtual"
              ? `Виртуальные · ${count} кол.`
              : "Колонки отключены"}
        </span>
      </div>

      {edgeDetected && mode !== "edge" ? (
        <div className="edge-detect-banner" style={{ marginTop: 10 }}>
          <div>
            <strong>Обнаружен сигнал реальных ТРК (station-edge)</strong>
            <div className="dash-muted">
              {(recentDispensesCount ?? 0) > 0
                ? `Наливов за 24 ч: ${recentDispensesCount}${lastDispenseAt ? ` (последний ${dateTime(lastDispenseAt)})` : ""}`
                : `Активный узел версии ${edgeNode?.current_version}`}
            </div>
          </div>
          <button
            type="button"
            className="btn small"
            disabled={saving}
            onClick={() => {
              const targetCount = Math.max(
                1,
                Math.min(8, edgeNode?.active_pumps || count || 2)
              );
              setMode("edge");
              setCount(targetCount);
              void persistColumns("edge", targetCount);
            }}
          >
            Переключить на реальные ТРК (1 клик)
          </button>
        </div>
      ) : null}

      <div className="mode-segmented" style={{ marginTop: 12 }}>
        {MODES.map((item) => (
          <button
            key={item.value}
            type="button"
            className={mode === item.value ? "active" : ""}
            onClick={() => setMode(item.value)}
          >
            <strong>{item.label}</strong>
            <small>{item.hint}</small>
          </button>
        ))}
      </div>

      <div className="admin-form" style={{ marginTop: 12 }}>
        <label>
          Количество колонок (1–8)
          <select
            value={count}
            disabled={mode === "none"}
            onChange={(e) => setCount(Number(e.target.value))}
          >
            {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <div className="span-2" style={{ display: "flex", alignItems: "flex-end", gap: 10 }}>
          <button
            type="button"
            className="btn small"
            disabled={saving || !dirty}
            onClick={() => void persistColumns(mode, count)}
          >
            {saving ? "Сохраняем…" : "Сохранить режим колонок"}
          </button>
          <span className="dash-muted">
            {recentDispensesCount != null
              ? `Транзакций ТРК за 24 ч: ${recentDispensesCount}`
              : "Проверка транзакций ТРК…"}
          </span>
        </div>
      </div>

      {error ? (
        <p className="tank-error" style={{ marginTop: 8 }}>
          {error}
        </p>
      ) : null}
    </section>
  );
}
