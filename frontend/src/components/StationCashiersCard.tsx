import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type CashierAccount, type CatalogStation } from "../api/client";
import { messageOf } from "../catalog";
import ConfirmModal from "./ConfirmModal";
import { useToast } from "./Toast";

function generateRandomPassword(length = 10): string {
  const chars = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let out = "";
  for (let i = 0; i < length; i += 1) {
    out += chars[Math.floor(Math.random() * chars.length)];
  }
  return out;
}

export default function StationCashiersCard({
  stationId,
  stations = [],
  canManage,
  onOpenStation,
}: {
  stationId?: string;
  stations?: CatalogStation[];
  canManage: boolean;
  onOpenStation?: (id: string) => void;
}) {
  const toast = useToast();
  const [cashiers, setCashiers] = useState<CashierAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [targetStationId, setTargetStationId] = useState(stationId ?? stations[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [issuedSecret, setIssuedSecret] = useState<{
    username: string;
    password: string;
    stationName: string;
  } | null>(null);

  const [resetTarget, setResetTarget] = useState<CashierAccount | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [reassignStationId, setReassignStationId] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<CashierAccount | null>(null);

  const effectiveStationId = stationId ?? targetStationId;

  useEffect(() => {
    if (stationId) {
      setTargetStationId(stationId);
      return;
    }
    if (stations.length > 0 && !stations.some((st) => st.id === targetStationId)) {
      setTargetStationId(stations[0].id);
    }
  }, [stationId, stations, targetStationId]);

  const stationById = useMemo(() => {
    const map = new Map<string, CatalogStation>();
    for (const st of stations) map.set(st.id, st);
    return map;
  }, [stations]);

  const loadCashiers = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = stationId ? await api.stationCashiers(stationId) : await api.cashiers();
      setCashiers(rows);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setLoading(false);
    }
  }, [stationId]);

  useEffect(() => {
    void loadCashiers();
  }, [loadCashiers]);

  function stationLabel(sid: string): string {
    const st = stationById.get(sid);
    return st ? `${st.name} (${st.code})` : sid;
  }

  async function copyPassword(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.ok("Пароль скопирован");
    } catch {
      toast.err("Не удалось скопировать пароль");
    }
  }

  async function handleCreate() {
    if (!effectiveStationId) {
      setError("Выберите заправку для кассира");
      return;
    }
    if (!username.trim() || password.length < 6) {
      setError("Укажите логин кассира и пароль не короче 6 символов");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await api.createStationCashier(effectiveStationId, {
        username: username.trim(),
        password,
      });
      setIssuedSecret({
        username: created.username,
        password: created.password,
        stationName: stationLabel(created.station_id),
      });
      setUsername("");
      setPassword("");
      await loadCashiers();
      toast.ok(`Кассир ${created.username} создан и прикреплён`);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateCashier(target: CashierAccount) {
    const body: { password?: string; station_id?: string } = {};
    if (resetPassword.trim()) {
      if (resetPassword.length < 6) {
        toast.err("Пароль не короче 6 символов");
        return;
      }
      body.password = resetPassword;
    }
    if (!stationId && reassignStationId && reassignStationId !== target.station_id) {
      body.station_id = reassignStationId;
    }
    if (!body.password && !body.station_id) {
      setResetTarget(null);
      return;
    }
    setBusy(true);
    try {
      const updated = await api.updateStationCashier(target.station_id, target.username, body);
      if (body.password) {
        setIssuedSecret({
          username: updated.username,
          password: body.password,
          stationName: stationLabel(updated.station_id),
        });
      }
      setResetTarget(null);
      setResetPassword("");
      await loadCashiers();
      toast.ok(`Данные кассира ${updated.username} обновлены`);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await api.deleteStationCashier(deleteTarget.station_id, deleteTarget.username);
      setDeleteTarget(null);
      await loadCashiers();
      toast.ok(`Кассир ${deleteTarget.username} удалён`);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="dash-card">
      <div className="card-head-inline">
        <div>
          <h3 style={{ margin: 0 }}>Кассиры ({cashiers.length})</h3>
          <p className="dash-muted" style={{ margin: "4px 0 0" }}>
            {canManage
              ? "Кассир прикрепляется к конкретной заправке, видит объём в цистерне, фактический расход по колонкам, открывает и закрывает смены."
              : "Список кассиров заправки (только чтение). Создавать и прикреплять кассиров может владелец АГЗС."}
          </p>
        </div>
      </div>

      {issuedSecret ? (
        <div className="edge-detect-banner" style={{ marginTop: 12 }}>
          <div>
            <strong>
              Пароль кассира {issuedSecret.username} ({issuedSecret.stationName}) показан один раз:
            </strong>{" "}
            <code>{issuedSecret.password}</code>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className="btn small"
              onClick={() => void copyPassword(issuedSecret.password)}
            >
              Копировать
            </button>
            <button
              type="button"
              className="btn secondary small"
              onClick={() => setIssuedSecret(null)}
            >
              Скрыть
            </button>
          </div>
        </div>
      ) : null}

      {canManage ? (
        <form
          className="admin-form"
          style={{ marginTop: 12, marginBottom: 14 }}
          onSubmit={(e) => {
            e.preventDefault();
            void handleCreate();
          }}
        >
          {!stationId && stations.length > 0 ? (
            <label>
              Заправка
              <select
                value={effectiveStationId}
                onChange={(e) => setTargetStationId(e.target.value)}
                required
              >
                {stations.map((st) => (
                  <option key={st.id} value={st.id}>
                    {st.name} ({st.code})
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label>
            Логин кассира
            <input
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="cashier_akt12"
              autoComplete="off"
              required
            />
          </label>
          <label>
            Пароль (не менее 6 символов)
            <div style={{ display: "flex", gap: 6 }}>
              <input
                type="text"
                style={{ flex: 1, minWidth: 0 }}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                minLength={6}
                required
              />
              <button
                type="button"
                className="btn secondary small"
                onClick={() => setPassword(generateRandomPassword())}
              >
                Сгенерировать
              </button>
            </div>
          </label>
          <div className="admin-actions" style={{ display: "flex", alignItems: "flex-end" }}>
            <button type="submit" className="btn small" disabled={busy || !effectiveStationId}>
              {busy ? "Сохраняем…" : "Создать кассира"}
            </button>
          </div>
        </form>
      ) : null}

      {error ? <p className="tank-error">{error}</p> : null}

      {loading && cashiers.length === 0 ? (
        <p className="dash-muted">Загрузка кассиров…</p>
      ) : cashiers.length === 0 ? (
        <p className="dash-muted" style={{ marginBottom: 0 }}>
          Кассиров пока нет.
        </p>
      ) : (
        <div className="dash-table-wrap" style={{ marginTop: 8 }}>
          <table className="dash-table">
            <thead>
              <tr>
                <th>Логин кассира</th>
                {!stationId ? <th>Привязанная АГЗС</th> : null}
                {canManage ? <th>Управление</th> : null}
              </tr>
            </thead>
            <tbody>
              {cashiers.map((row) => {
                const isEditing = resetTarget?.id === row.id;
                return (
                  <tr key={row.id}>
                    <td>
                      <strong>{row.username}</strong>
                      {isEditing ? (
                        <form
                          className="inline-resolve-form"
                          style={{ marginTop: 8 }}
                          onSubmit={(e) => {
                            e.preventDefault();
                            void handleUpdateCashier(row);
                          }}
                        >
                          {!stationId && stations.length > 1 ? (
                            <select
                              className="st-select"
                              value={reassignStationId}
                              onChange={(e) => setReassignStationId(e.target.value)}
                            >
                              {stations.map((st) => (
                                <option key={st.id} value={st.id}>
                                  {st.name} ({st.code})
                                </option>
                              ))}
                            </select>
                          ) : null}
                          <input
                            type="text"
                            value={resetPassword}
                            onChange={(e) => setResetPassword(e.target.value)}
                            placeholder="Новый пароль (опционально, ≥ 6)"
                            minLength={resetPassword ? 6 : undefined}
                          />
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => setResetPassword(generateRandomPassword())}
                          >
                            Сгенерировать
                          </button>
                          <button type="submit" className="btn small" disabled={busy}>
                            Сохранить
                          </button>
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => setResetTarget(null)}
                          >
                            Отмена
                          </button>
                        </form>
                      ) : null}
                    </td>
                    {!stationId ? (
                      <td>
                        {onOpenStation ? (
                          <button
                            type="button"
                            className="link-inline"
                            onClick={() => onOpenStation(row.station_id)}
                          >
                            <strong>{stationLabel(row.station_id)}</strong>
                          </button>
                        ) : (
                          <strong>{stationLabel(row.station_id)}</strong>
                        )}
                      </td>
                    ) : null}
                    {canManage ? (
                      <td>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => {
                              setResetTarget(isEditing ? null : row);
                              setResetPassword("");
                              setReassignStationId(row.station_id);
                            }}
                          >
                            {stationId ? "Сбросить пароль" : "Изменить"}
                          </button>
                          <button
                            type="button"
                            className="btn secondary small text-danger"
                            onClick={() => setDeleteTarget(row)}
                          >
                            Удалить
                          </button>
                        </div>
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmModal
        open={deleteTarget !== null}
        title="Удалить кассира?"
        message={`Учётная запись кассира «${deleteTarget?.username ?? ""}» будет удалена.`}
        details="Кассир сразу потеряет доступ к сменам и показаниям этой заправки."
        confirmLabel="Удалить кассира"
        danger
        busy={busy}
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleteTarget(null)}
      />
    </section>
  );
}
