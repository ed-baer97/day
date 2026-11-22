import { useEffect, useMemo, useState } from "react";
import {
  api,
  type CatalogStation,
  type EdgeFleetSummary,
  type EdgeReleaseManifest,
} from "../../api/client";
import { messageOf } from "../../catalog";
import ConfirmModal from "../../components/ConfirmModal";
import { dateTime } from "../../format";

type NodeFilter = "all" | "outdated" | "issues";

export default function AdminEdgeTab({
  fleet,
  stations,
  loading,
  onRefresh,
  onOpenStation,
  toast,
}: {
  fleet: EdgeFleetSummary | null;
  stations: CatalogStation[];
  loading: boolean;
  onRefresh: () => Promise<void>;
  onOpenStation: (stationId: string) => void;
  toast: { ok: (msg: string) => void; err: (msg: string) => void };
}) {
  const [nodeFilter, setNodeFilter] = useState<NodeFilter>("all");
  const [query, setQuery] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  // Форма публикации OTA-релиза
  const [channel, setChannel] = useState<"ring0" | "ring1" | "ring2">("ring0");
  const [version, setVersion] = useState("");
  const [artifactUrl, setArtifactUrl] = useState("");
  const [sha256, setSha256] = useState("");
  const [minVersion, setMinVersion] = useState("");
  const [notes, setNotes] = useState("");
  const [signature, setSignature] = useState("");
  const [canaryCodes, setCanaryCodes] = useState<string[]>([]);
  const [ring1Codes, setRing1Codes] = useState<string[]>([]);
  const [extraCodesText, setExtraCodesText] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [confirmRing2, setConfirmRing2] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    if (!fleet) return;
    setCanaryCodes(fleet.canary_stations ?? []);
    setRing1Codes(fleet.ring1_stations ?? []);
  }, [fleet]);

  function loadRingToForm(ring: "ring0" | "ring1" | "ring2") {
    const rel = fleet?.releases[ring];
    setChannel(ring);
    if (!rel) return;
    setVersion(rel.version);
    setArtifactUrl(rel.artifact_url);
    setSha256(rel.sha256);
    setMinVersion(rel.min_version ?? "");
    setNotes(rel.notes ?? "");
    setSignature(rel.signature ?? "");
    setExtraCodesText("");
    setFormError(null);
  }

  const totalOutbox = useMemo(
    () => (fleet?.nodes ?? []).reduce((sum, node) => sum + (node.outbox_pending || 0), 0),
    [fleet]
  );

  const filteredNodes = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (fleet?.nodes ?? []).filter((node) => {
      if (q && !node.station_code.toLowerCase().includes(q)) return false;
      if (nodeFilter === "outdated" && node.up_to_date) return false;
      if (nodeFilter === "issues" && !node.last_error && node.outbox_pending === 0) return false;
      return true;
    });
  }, [fleet, query, nodeFilter]);

  function toggleStationCode(code: string, list: string[], setList: (next: string[]) => void) {
    if (list.includes(code)) setList(list.filter((c) => c !== code));
    else setList([...list, code]);
  }

  function validateForm(): EdgeReleaseManifest | null {
    const cleanedVer = version.trim();
    const cleanedUrl = artifactUrl.trim();
    const cleanedSha = sha256.trim().toLowerCase();
    if (!cleanedVer || !cleanedUrl) {
      setFormError("Укажите версию и URL пакета");
      return null;
    }
    if (!/^[0-9a-f]{64}$/.test(cleanedSha) || cleanedSha === "0".repeat(64)) {
      setFormError("Укажите реальный SHA-256 (64 hex-символа, не нули)");
      return null;
    }
    setFormError(null);
    return {
      version: cleanedVer,
      artifact_url: cleanedUrl,
      sha256: cleanedSha,
      channel,
      min_version: minVersion.trim() || null,
      notes: notes.trim(),
      signature: signature.trim() || null,
    };
  }

  async function doPublish(manifest: EdgeReleaseManifest) {
    const extra = extraCodesText
      .split(/[,;\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    const ringStations =
      channel === "ring0"
        ? Array.from(new Set([...canaryCodes, ...extra]))
        : channel === "ring1"
          ? Array.from(new Set([...ring1Codes, ...extra]))
          : undefined;

    setPublishing(true);
    setFormError(null);
    try {
      await api.publishEdgeRelease(
        manifest,
        channel === "ring0"
          ? { canary_stations: ringStations }
          : channel === "ring1"
            ? { ring1_stations: ringStations }
            : undefined
      );
      setConfirmRing2(false);
      await onRefresh();
      toast.ok(`Релиз ${manifest.version} опубликован в ${channel}`);
    } catch (err) {
      setFormError(messageOf(err));
    } finally {
      setPublishing(false);
    }
  }

  function handleFormSubmit() {
    const manifest = validateForm();
    if (!manifest) return;
    if (channel === "ring2") {
      setConfirmRing2(true);
      return;
    }
    void doPublish(manifest);
  }

  const activeList = channel === "ring0" ? canaryCodes : ring1Codes;
  const setActiveList = channel === "ring0" ? setCanaryCodes : setRing1Codes;

  return (
    <div className="admin-workspace">
      <div className="dash-kpis">
        <div className="dash-kpi">
          <span>Узлов station-edge</span>
          <strong>{fleet?.total_nodes ?? 0}</strong>
          <em>зарегистрировано по heartbeat</em>
        </div>
        <div className="dash-kpi">
          <span>Актуальная версия</span>
          <strong style={{ color: "var(--sea)" }}>{fleet?.up_to_date_nodes ?? 0}</strong>
          <em>обновление не требуется</em>
        </div>
        <div className="dash-kpi">
          <span>Требуют обновления</span>
          <strong className={(fleet?.outdated_nodes ?? 0) > 0 ? "text-danger" : ""}>
            {fleet?.outdated_nodes ?? 0}
          </strong>
          <em>отстают от целевого кольца</em>
        </div>
        <div className="dash-kpi">
          <span>Очередь outbox</span>
          <strong className={totalOutbox > 0 ? "text-danger" : ""}>{totalOutbox}</strong>
          <em>неотправленных событий на АГЗС</em>
        </div>
      </div>

      <section className="dash-card">
        <div className="card-head-inline">
          <div>
            <h3 style={{ margin: 0 }}>Кольца раскатки OTA (ring0 / ring1 / ring2)</h3>
            <p className="dash-muted" style={{ margin: "4px 0 0" }}>
              Поэтапное обновление АСКА-02 шлюзов: canary → 10% сети → массовая раскатка в простой.
            </p>
          </div>
          <button
            type="button"
            className="btn secondary small"
            disabled={refreshing || loading}
            onClick={async () => {
              setRefreshing(true);
              try {
                await onRefresh();
              } finally {
                setRefreshing(false);
              }
            }}
          >
            {refreshing ? "Обновление…" : "Обновить сводку"}
          </button>
        </div>

        <div className="edge-rings-grid" style={{ marginTop: 12 }}>
          {(["ring0", "ring1", "ring2"] as const).map((ring) => {
            const rel = fleet?.releases[ring];
            const ringStations =
              ring === "ring0"
                ? fleet?.canary_stations ?? []
                : ring === "ring1"
                  ? fleet?.ring1_stations ?? []
                  : null;
            return (
              <article key={ring} className="edge-ring-card">
                <div className="card-head-inline" style={{ marginBottom: 6 }}>
                  <strong>
                    {ring === "ring0"
                      ? "Кольцо 0 (Canary)"
                      : ring === "ring1"
                        ? "Кольцо 1 (10% сети)"
                        : "Кольцо 2 (Stable 90%)"}
                  </strong>
                  <span className="badge ok">{rel?.version ?? "—"}</span>
                </div>
                {rel ? (
                  <>
                    <div className="dash-muted" style={{ wordBreak: "break-all" }}>
                      {rel.artifact_url}
                    </div>
                    <div className="dash-muted" style={{ marginTop: 4 }}>
                      SHA-256: <code>{rel.sha256.slice(0, 12)}…</code> ·{" "}
                      {rel.signature ? (
                        <span className="badge ok">
                          {rel.signature.startsWith("ed25519:") ? "Ed25519 подписан" : "HMAC подписан"}
                        </span>
                      ) : (
                        <span className="badge warn">без подписи</span>
                      )}
                    </div>
                    {ringStations !== null ? (
                      <div className="dash-muted" style={{ marginTop: 6 }}>
                        АГЗС кольца:{" "}
                        {ringStations.length > 0 ? ringStations.join(", ") : "не назначены"}
                      </div>
                    ) : (
                      <div className="dash-muted" style={{ marginTop: 6 }}>
                        АГЗС кольца: все остальные станции
                      </div>
                    )}
                    {rel.notes ? (
                      <p className="dash-muted" style={{ margin: "6px 0 0" }}>
                        {rel.notes}
                      </p>
                    ) : null}
                  </>
                ) : (
                  <p className="dash-muted">Манифест ещё не задан.</p>
                )}
                <div style={{ marginTop: 10 }}>
                  <button
                    type="button"
                    className="btn secondary small"
                    onClick={() => loadRingToForm(ring)}
                  >
                    Загрузить в форму
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="dash-card">
        <div className="card-head-inline">
          <h3>Станционные узлы station-edge ({filteredNodes.length})</h3>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <input
              type="search"
              className="st-select"
              placeholder="Поиск по коду АГЗС…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <div className="mini-tabs">
              <button
                type="button"
                className={nodeFilter === "all" ? "active" : ""}
                onClick={() => setNodeFilter("all")}
              >
                Все
              </button>
              <button
                type="button"
                className={nodeFilter === "outdated" ? "active" : ""}
                onClick={() => setNodeFilter("outdated")}
              >
                Устарели
              </button>
              <button
                type="button"
                className={nodeFilter === "issues" ? "active" : ""}
                onClick={() => setNodeFilter("issues")}
              >
                Ошибки / Очередь
              </button>
            </div>
          </div>
        </div>

        {loading && !fleet ? (
          <p className="dash-muted">Загрузка состояния узлов…</p>
        ) : filteredNodes.length === 0 ? (
          <p className="dash-muted">
            {(fleet?.nodes.length ?? 0) === 0
              ? "Пока ни один узел station-edge не прислал heartbeat. После запуска agzs-edge на АГЗС здесь появятся версии, очередь outbox и статус обновлений."
              : "По выбранному фильтру узлов не найдено."}
          </p>
        ) : (
          <div className="dash-table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th>АГЗС</th>
                  <th>Кольцо</th>
                  <th>Версия</th>
                  <th>Активных ТРК</th>
                  <th>Очередь outbox</th>
                  <th>Статус / Ошибка</th>
                  <th>Последний контакт</th>
                </tr>
              </thead>
              <tbody>
                {filteredNodes.map((node) => {
                  const matchedStation = stations.find(
                    (s) => s.code.toLowerCase() === node.station_code.toLowerCase()
                  );
                  return (
                    <tr key={node.station_code}>
                      <td>
                        {matchedStation ? (
                          <button
                            type="button"
                            className="link-inline"
                            onClick={() => onOpenStation(matchedStation.id)}
                          >
                            <strong>{node.station_code}</strong>
                          </button>
                        ) : (
                          <strong>{node.station_code}</strong>
                        )}
                        {matchedStation ? (
                          <div className="dash-muted">{matchedStation.name}</div>
                        ) : null}
                      </td>
                      <td>
                        <span className="badge">{node.channel}</span>
                      </td>
                      <td>
                        <span className={`badge ${node.up_to_date ? "ok" : "warn"}`}>
                          {node.current_version} → {node.target_version}
                        </span>
                      </td>
                      <td>{node.active_pumps}</td>
                      <td>
                        <strong className={node.outbox_pending > 0 ? "text-danger" : ""}>
                          {node.outbox_pending}
                        </strong>
                      </td>
                      <td>
                        <span className={`badge ${node.last_error ? "danger" : "ok"}`}>
                          {node.update_status}
                        </span>
                        {node.last_error ? (
                          <div className="dash-muted text-danger">{node.last_error}</div>
                        ) : null}
                      </td>
                      <td>{dateTime(node.last_seen_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="dash-card">
        <h3>Публикация OTA-релиза</h3>
        <form
          className="admin-form"
          style={{ marginTop: 10 }}
          onSubmit={(e) => {
            e.preventDefault();
            handleFormSubmit();
          }}
        >
          <label>
            Целевое кольцо
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value as "ring0" | "ring1" | "ring2")}
            >
              <option value="ring0">ring0 (canary, 1–2 тестовые АГЗС)</option>
              <option value="ring1">ring1 (10% станций)</option>
              <option value="ring2">ring2 (stable, остальные 90%)</option>
            </select>
          </label>
          <label>
            Версия
            <input value={version} onChange={(e) => setVersion(e.target.value)} required />
          </label>
          <label>
            Мин. версия (необязательно)
            <input
              placeholder="0.1.0"
              value={minVersion}
              onChange={(e) => setMinVersion(e.target.value)}
            />
          </label>
          <label className="span-3">
            URL артефакта (.whl)
            <input value={artifactUrl} onChange={(e) => setArtifactUrl(e.target.value)} required />
          </label>
          <label className="span-2">
            SHA-256 (64 hex-символа)
            <input value={sha256} onChange={(e) => setSha256(e.target.value)} required />
          </label>
          <label>
            Подпись релиза (Ed25519 / HMAC, опционально)
            <input
              placeholder="автоподпись сервером при пустом поле"
              value={signature}
              onChange={(e) => setSignature(e.target.value)}
            />
          </label>
          <label className="span-3">
            Примечание к релизу
            <input
              placeholder="Исправление синхронизации АСКА-02..."
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </label>

          {channel !== "ring2" ? (
            <div className="span-3">
              <p className="dash-muted" style={{ margin: "0 0 6px" }}>
                Станции кольца {channel} (выберите из каталога или допишите коды через запятую):
              </p>
              {stations.length > 0 ? (
                <div className="owner-checklist" style={{ marginBottom: 8 }}>
                  {stations.map((st) => (
                    <label key={st.id} className="admin-check">
                      <input
                        type="checkbox"
                        checked={activeList.includes(st.code)}
                        onChange={() => toggleStationCode(st.code, activeList, setActiveList)}
                      />
                      <span>
                        {st.code} · {st.name}
                      </span>
                    </label>
                  ))}
                </div>
              ) : null}
              <label>
                Дополнительные коды АГЗС (через запятую)
                <input
                  placeholder="AKT-R0-1, AKT-R0-2"
                  value={extraCodesText}
                  onChange={(e) => setExtraCodesText(e.target.value)}
                />
              </label>
            </div>
          ) : null}

          {formError ? <p className="tank-error span-3">{formError}</p> : null}

          <div className="admin-actions span-3">
            <button type="submit" className="btn small" disabled={publishing}>
              {publishing ? "Публикуем…" : `Опубликовать в ${channel}`}
            </button>
          </div>
        </form>
      </section>

      <ConfirmModal
        open={confirmRing2}
        title="Опубликовать релиз в основное кольцо ring2?"
        message={`Версия ${version} станет целевой для всех станций стабильного кольца (90% сети).`}
        details="Убедитесь, что релиз прошёл обкатку в ring0 и ring1 и не прерывает активный налив."
        confirmLabel="Опубликовать в ring2"
        busy={publishing}
        onConfirm={() => {
          const manifest = validateForm();
          if (manifest) void doPublish(manifest);
        }}
        onCancel={() => setConfirmRing2(false)}
      />
    </div>
  );
}
