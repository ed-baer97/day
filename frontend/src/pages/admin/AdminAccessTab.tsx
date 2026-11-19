import { useMemo, useState } from "react";
import {
  api,
  type AdminStationOverview,
  type AdminTankOverview,
  type CatalogStation,
  type OwnerAccount,
} from "../../api/client";
import { messageOf } from "../../catalog";
import ConfirmModal from "../../components/ConfirmModal";
import { SENSOR_STALE_SECONDS } from "../../policy";

function generateRandomPassword(length = 10): string {
  const chars = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  let out = "";
  for (let i = 0; i < length; i += 1) {
    out += chars[Math.floor(Math.random() * chars.length)];
  }
  return out;
}

function maskToken(token: string): string {
  if (token.length <= 8) return "••••••••";
  return `••••••••${token.slice(-6)}`;
}

export default function AdminAccessTab({
  username,
  stations,
  overview,
  owners,
  onRefreshOwners,
  onRefreshOverview,
  onOpenStation,
  toast,
}: {
  username?: string | null;
  stations: CatalogStation[];
  overview: AdminStationOverview[];
  owners: OwnerAccount[];
  onRefreshOwners: () => Promise<void>;
  onRefreshOverview: () => Promise<void>;
  onOpenStation: (id: string) => void;
  toast: { ok: (msg: string) => void; err: (msg: string) => void };
}) {
  // Создание нового владельца
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newStationIds, setNewStationIds] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [ownerFormError, setOwnerFormError] = useState<string | null>(null);
  const [issuedSecret, setIssuedSecret] = useState<{ username: string; password: string } | null>(
    null
  );

  // Редактирование станций / сброс пароля владельца
  const [editingStationsFor, setEditingStationsFor] = useState<string | null>(null);
  const [editStationIds, setEditStationIds] = useState<string[]>([]);
  const [resetPasswordFor, setResetPasswordFor] = useState<string | null>(null);
  const [resetPasswordValue, setResetPasswordValue] = useState("");
  const [ownerActionBusy, setOwnerActionBusy] = useState(false);
  const [deleteOwnerTarget, setDeleteOwnerTarget] = useState<OwnerAccount | null>(null);

  // Токены устройств
  const [tokenQuery, setTokenQuery] = useState("");
  const [revealedTokens, setRevealedTokens] = useState<Record<string, boolean>>({});
  const [rotateTarget, setRotateTarget] = useState<{
    stationId: string;
    stationName: string;
    tank: AdminTankOverview;
  } | null>(null);
  const [rotateBusy, setRotateBusy] = useState(false);

  const stationsWithOwnersCount = useMemo(() => {
    const covered = new Set<string>();
    for (const owner of owners) {
      for (const sid of owner.station_ids) covered.add(sid);
    }
    return stations.filter((s) => covered.has(s.id)).length;
  }, [owners, stations]);

  const allTokenRows = useMemo(() => {
    const q = tokenQuery.trim().toLowerCase();
    const list: { station: AdminStationOverview; tank: AdminTankOverview }[] = [];
    for (const st of overview) {
      for (const tank of st.tanks) {
        if (q) {
          const hit = [st.name, st.code, tank.code].some((p) => p.toLowerCase().includes(q));
          if (!hit) continue;
        }
        list.push({ station: st, tank });
      }
    }
    return list;
  }, [overview, tokenQuery]);

  const totalTokensCount = useMemo(
    () => overview.reduce((sum, st) => sum + st.tanks.length, 0),
    [overview]
  );

  function toggleStationId(sid: string, list: string[], setList: (next: string[]) => void) {
    if (list.includes(sid)) setList(list.filter((item) => item !== sid));
    else setList([...list, sid]);
  }

  async function handleCreateOwner() {
    if (!newUsername.trim() || newPassword.length < 6) {
      setOwnerFormError("Укажите логин и пароль не короче 6 символов");
      return;
    }
    if (newStationIds.length === 0) {
      setOwnerFormError("Выберите хотя бы одну АГЗС для владельца");
      return;
    }
    setCreating(true);
    setOwnerFormError(null);
    try {
      const created = await api.createOwner({
        username: newUsername.trim(),
        password: newPassword,
        station_ids: newStationIds,
      });
      setIssuedSecret({ username: created.username, password: created.password });
      setNewUsername("");
      setNewPassword("");
      setNewStationIds([]);
      await onRefreshOwners();
      toast.ok(`Владелец ${created.username} создан`);
    } catch (err) {
      setOwnerFormError(messageOf(err));
    } finally {
      setCreating(false);
    }
  }

  async function saveEditedStations(targetUsername: string) {
    if (editStationIds.length === 0) {
      toast.err("Оставьте хотя бы одну АГЗС или удалите владельца");
      return;
    }
    setOwnerActionBusy(true);
    try {
      await api.updateOwner(targetUsername, { station_ids: editStationIds });
      setEditingStationsFor(null);
      await onRefreshOwners();
      toast.ok(`Список АГЗС для ${targetUsername} обновлён`);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setOwnerActionBusy(false);
    }
  }

  async function saveResetPassword(targetUsername: string) {
    if (resetPasswordValue.length < 6) {
      toast.err("Пароль должен быть не короче 6 символов");
      return;
    }
    setOwnerActionBusy(true);
    try {
      await api.updateOwner(targetUsername, { password: resetPasswordValue });
      setIssuedSecret({ username: targetUsername, password: resetPasswordValue });
      setResetPasswordFor(null);
      setResetPasswordValue("");
      toast.ok(`Пароль владельца ${targetUsername} обновлён`);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setOwnerActionBusy(false);
    }
  }

  async function confirmDeleteOwner() {
    if (!deleteOwnerTarget) return;
    setOwnerActionBusy(true);
    try {
      await api.deleteOwner(deleteOwnerTarget.username);
      setDeleteOwnerTarget(null);
      await onRefreshOwners();
      toast.ok(`Владелец ${deleteOwnerTarget.username} удалён`);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setOwnerActionBusy(false);
    }
  }

  async function confirmRotateToken() {
    if (!rotateTarget) return;
    setRotateBusy(true);
    try {
      const updated = await api.rotateTankToken(rotateTarget.stationId, rotateTarget.tank.id);
      setRevealedTokens((cur) => ({ ...cur, [updated.id]: true }));
      setRotateTarget(null);
      await onRefreshOverview();
      toast.ok(`Токен ${rotateTarget.stationName} (${rotateTarget.tank.code}) перевыпущен`);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setRotateBusy(false);
    }
  }

  async function copyText(text: string, label: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.ok(`${label} скопирован`);
    } catch {
      toast.err("Не удалось скопировать в буфер обмена");
    }
  }

  return (
    <div className="admin-workspace">
      <div className="dash-kpis">
        <div className="dash-kpi">
          <span>Владельцев АГЗС</span>
          <strong>{owners.length}</strong>
          <em>учётные записи станционного уровня</em>
        </div>
        <div className="dash-kpi">
          <span>АГЗС с владельцем</span>
          <strong>
            {stationsWithOwnersCount} / {stations.length}
          </strong>
          <em>станций под управлением владельцев</em>
        </div>
        <div className="dash-kpi">
          <span>Токенов устройств</span>
          <strong>{totalTokensCount}</strong>
          <em>активных ключей X-Device-Token</em>
        </div>
        <div className="dash-kpi">
          <span>Текущая сессия</span>
          <strong>{username || "admin"}</strong>
          <em>sessionStorage · серверный отзыв jti</em>
        </div>
      </div>

      {issuedSecret ? (
        <section className="dash-card edge-detect-banner">
          <div>
            <strong>
              Пароль для владельца {issuedSecret.username} (показан один раз):
            </strong>{" "}
            <code>{issuedSecret.password}</code>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              type="button"
              className="btn small"
              onClick={() => void copyText(issuedSecret.password, "Пароль")}
            >
              Копировать пароль
            </button>
            <button
              type="button"
              className="btn secondary small"
              onClick={() => setIssuedSecret(null)}
            >
              Скрыть
            </button>
          </div>
        </section>
      ) : null}

      <section className="dash-card">
        <h3>Владельцы АГЗС ({owners.length})</h3>
        <p className="dash-muted">
          Один логин может управлять одной или несколькими заправками (только чтение своих
          АГЗС, остатков, колонок, журнала и адреса телеметрии).
        </p>

        <form
          className="admin-form"
          style={{ marginTop: 10, marginBottom: 16 }}
          onSubmit={(e) => {
            e.preventDefault();
            void handleCreateOwner();
          }}
        >
          <label>
            Логин нового владельца
            <input
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              placeholder="rekon_owner"
              autoComplete="off"
              required
            />
          </label>
          <label>
            Пароль (не короче 6 символов)
            <div style={{ display: "flex", gap: 6 }}>
              <input
                type="text"
                style={{ flex: 1, minWidth: 0 }}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
                minLength={6}
                required
              />
              <button
                type="button"
                className="btn secondary small"
                onClick={() => setNewPassword(generateRandomPassword())}
              >
                Сгенерировать
              </button>
            </div>
          </label>
          <div style={{ display: "flex", alignItems: "flex-end" }}>
            <button type="submit" className="btn small" disabled={creating}>
              {creating ? "Создаём…" : "Создать владельца"}
            </button>
          </div>
          <div className="span-3">
            <div className="card-head-inline" style={{ marginBottom: 6 }}>
              <span className="dash-muted">Привязать к АГЗС:</span>
              <div style={{ display: "flex", gap: 6 }}>
                <button
                  type="button"
                  className="btn secondary small"
                  onClick={() => setNewStationIds(stations.map((s) => s.id))}
                >
                  Выбрать все
                </button>
                <button
                  type="button"
                  className="btn secondary small"
                  onClick={() => setNewStationIds([])}
                >
                  Снять выбор
                </button>
              </div>
            </div>
            <div className="owner-checklist">
              {stations.map((st) => (
                <label key={st.id} className="admin-check">
                  <input
                    type="checkbox"
                    checked={newStationIds.includes(st.id)}
                    onChange={() => toggleStationId(st.id, newStationIds, setNewStationIds)}
                  />
                  <span>
                    {st.name} ({st.code})
                  </span>
                </label>
              ))}
            </div>
          </div>
          {ownerFormError ? <p className="tank-error span-3">{ownerFormError}</p> : null}
        </form>

        {owners.length === 0 ? (
          <p className="dash-muted">Владельцев АГЗС пока не создано.</p>
        ) : (
          <div className="dash-table-wrap">
            <table className="dash-table">
              <thead>
                <tr>
                  <th>Логин</th>
                  <th>Привязанные АГЗС</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>
                {owners.map((owner) => {
                  const isEditingStations = editingStationsFor === owner.username;
                  const isResetting = resetPasswordFor === owner.username;
                  return (
                    <tr key={owner.username}>
                      <td>
                        <strong>{owner.username}</strong>
                      </td>
                      <td>
                        <div className="owner-chips">
                          {owner.station_ids.map((sid) => {
                            const st = stations.find((s) => s.id === sid);
                            return (
                              <button
                                key={sid}
                                type="button"
                                className="owner-chip link-chip"
                                onClick={() => onOpenStation(sid)}
                              >
                                {st ? `${st.name} (${st.code})` : sid}
                              </button>
                            );
                          })}
                        </div>
                        {isEditingStations ? (
                          <div style={{ marginTop: 8 }}>
                            <div className="owner-checklist">
                              {stations.map((st) => (
                                <label key={st.id} className="admin-check">
                                  <input
                                    type="checkbox"
                                    checked={editStationIds.includes(st.id)}
                                    onChange={() =>
                                      toggleStationId(st.id, editStationIds, setEditStationIds)
                                    }
                                  />
                                  <span>
                                    {st.name} ({st.code})
                                  </span>
                                </label>
                              ))}
                            </div>
                            <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                              <button
                                type="button"
                                className="btn small"
                                disabled={ownerActionBusy}
                                onClick={() => void saveEditedStations(owner.username)}
                              >
                                Сохранить АГЗС
                              </button>
                              <button
                                type="button"
                                className="btn secondary small"
                                onClick={() => setEditingStationsFor(null)}
                              >
                                Отмена
                              </button>
                            </div>
                          </div>
                        ) : null}
                        {isResetting ? (
                          <form
                            className="inline-resolve-form"
                            style={{ marginTop: 8 }}
                            onSubmit={(e) => {
                              e.preventDefault();
                              void saveResetPassword(owner.username);
                            }}
                          >
                            <input
                              type="text"
                              value={resetPasswordValue}
                              onChange={(e) => setResetPasswordValue(e.target.value)}
                              placeholder="Новый пароль (≥ 6 симв.)"
                              minLength={6}
                              required
                            />
                            <button
                              type="button"
                              className="btn secondary small"
                              onClick={() => setResetPasswordValue(generateRandomPassword())}
                            >
                              Сгенерировать
                            </button>
                            <button
                              type="submit"
                              className="btn small"
                              disabled={ownerActionBusy}
                            >
                              Сохранить пароль
                            </button>
                            <button
                              type="button"
                              className="btn secondary small"
                              onClick={() => setResetPasswordFor(null)}
                            >
                              Отмена
                            </button>
                          </form>
                        ) : null}
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => {
                              setEditingStationsFor(isEditingStations ? null : owner.username);
                              setEditStationIds(owner.station_ids);
                              setResetPasswordFor(null);
                            }}
                          >
                            Станции
                          </button>
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => {
                              setResetPasswordFor(isResetting ? null : owner.username);
                              setResetPasswordValue("");
                              setEditingStationsFor(null);
                            }}
                          >
                            Сбросить пароль
                          </button>
                          <button
                            type="button"
                            className="btn secondary small text-danger"
                            onClick={() => setDeleteOwnerTarget(owner)}
                          >
                            Удалить
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="dash-card">
        <div className="card-head-inline">
          <div>
            <h3 style={{ margin: 0 }}>Токены устройств (X-Device-Token)</h3>
            <p className="dash-muted" style={{ margin: "4px 0 0" }}>
              Каждый токен привязан строго к своему резервуару и АГЗС.
            </p>
          </div>
          <input
            type="search"
            className="st-select"
            placeholder="Фильтр по АГЗС или резервуару…"
            value={tokenQuery}
            onChange={(e) => setTokenQuery(e.target.value)}
          />
        </div>

        {allTokenRows.length === 0 ? (
          <p className="dash-muted" style={{ marginTop: 10 }}>
            Резервуары и токены не найдены.
          </p>
        ) : (
          <div className="dash-table-wrap" style={{ marginTop: 10 }}>
            <table className="dash-table">
              <thead>
                <tr>
                  <th>АГЗС</th>
                  <th>Резервуар</th>
                  <th>Датчик / Shelly</th>
                  <th>X-Device-Token</th>
                  <th>Управление</th>
                </tr>
              </thead>
              <tbody>
                {allTokenRows.map(({ station, tank }) => {
                  const revealed = !!revealedTokens[tank.id];
                  return (
                    <tr key={tank.id}>
                      <td>
                        <button
                          type="button"
                          className="link-inline"
                          onClick={() => onOpenStation(station.id)}
                        >
                          <strong>{station.name}</strong>
                        </button>
                        <div className="dash-muted">{station.code}</div>
                      </td>
                      <td>
                        <strong>{tank.code}</strong>
                      </td>
                      <td>
                        <span
                          className={`badge ${
                            tank.actual_remainder_liters == null
                              ? "warn"
                              : tank.online
                                ? "ok"
                                : "danger"
                          }`}
                        >
                          {tank.actual_remainder_liters == null
                            ? "замера нет"
                            : tank.online
                              ? "на связи"
                              : "нет связи"}
                        </span>
                        {tank.shelly ? (
                          <div className="dash-muted">Shelly {tank.shelly.host}</div>
                        ) : null}
                      </td>
                      <td>
                        <code className="token-code">
                          {revealed ? tank.ingest_token : maskToken(tank.ingest_token)}
                        </code>
                      </td>
                      <td>
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() =>
                              setRevealedTokens((cur) => ({
                                ...cur,
                                [tank.id]: !cur[tank.id],
                              }))
                            }
                          >
                            {revealed ? "Скрыть" : "Показать"}
                          </button>
                          <button
                            type="button"
                            className="btn secondary small"
                            onClick={() => void copyText(tank.ingest_token, "Токен")}
                          >
                            Копировать
                          </button>
                          <button
                            type="button"
                            className="btn secondary small text-danger"
                            onClick={() =>
                              setRotateTarget({
                                stationId: station.id,
                                stationName: station.name,
                                tank,
                              })
                            }
                          >
                            Перевыпустить
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <details className="dash-card security-details">
        <summary>
          <strong>Памятка по разграничению данных и механизмам защиты</strong>
          <span className="dash-muted"> (нажмите, чтобы развернуть)</span>
        </summary>
        <div style={{ marginTop: 12 }}>
          <table className="dash-table">
            <thead>
              <tr>
                <th>Категория данных</th>
                <th>Публичная витрина</th>
                <th>Закрытый контур</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Активные АГЗС, остаток и % в резервуаре, статус связи ({SENSOR_STALE_SECONDS} сек)</td>
                <td>
                  <span className="badge ok">Открыто (GET /public/levels)</span>
                </td>
                <td>
                  <span className="badge ok">Доступно</span>
                </td>
              </tr>
              <tr>
                <td>Книжный остаток, расхождения, снимки баланса и транзакции ТРК</td>
                <td>
                  <span className="badge danger">Скрыто</span>
                </td>
                <td>
                  <span className="badge ok">Только авторизованным ролям</span>
                </td>
              </tr>
              <tr>
                <td>Скрытые АГЗС, газовозы, GPS-трекинг, партии, владельцы и OTA-парк</td>
                <td>
                  <span className="badge danger">Скрыто</span>
                </td>
                <td>
                  <span className="badge ok">Только администратор платформы</span>
                </td>
              </tr>
              <tr>
                <td>IP-адреса Shelly и ключи X-Device-Token</td>
                <td>
                  <span className="badge danger">Скрыто</span>
                </td>
                <td>
                  <span className="badge ok">Администратор / своя станция</span>
                </td>
              </tr>
            </tbody>
          </table>
          <ul className="trail-list" style={{ marginTop: 12 }}>
            <li>
              <span className="title">IDOR-изоляция телеметрии и ролевых токенов</span>
              <span className="desc">
                <code>X-Device-Token</code> привязан к конкретным <code>tank_id</code> и{" "}
                <code>station_id</code>; токен владельца ограничен списком привязанных АГЗС.
              </span>
            </li>
            <li>
              <span className="title">SSRF-фильтр для опроса Shelly</span>
              <span className="desc">
                Блокируется обращение к loopback, link-local metadata и служебным хостам при
                привязке датчика.
              </span>
            </li>
            <li>
              <span className="title">Ограничение перебора паролей и отзыв сессий</span>
              <span className="desc">
                Rate-limit на <code>POST /auth/login</code> (5 неудачных попыток за 60 сек → HTTP
                429) и серверный отзыв токена при выходе.
              </span>
            </li>
          </ul>
        </div>
      </details>

      <ConfirmModal
        open={deleteOwnerTarget !== null}
        title="Удалить владельца АГЗС?"
        message={`Учётная запись «${deleteOwnerTarget?.username ?? ""}» будет полностью удалена.`}
        details="Пользователь потеряет доступ ко всем привязанным станциям."
        confirmLabel="Удалить владельца"
        danger
        busy={ownerActionBusy}
        onConfirm={() => void confirmDeleteOwner()}
        onCancel={() => setDeleteOwnerTarget(null)}
      />

      <ConfirmModal
        open={rotateTarget !== null}
        title="Перевыпустить X-Device-Token?"
        message={`Текущий токен резервуара ${rotateTarget?.tank.code ?? ""} (${rotateTarget?.stationName ?? ""}) сразу станет недействительным.`}
        details="После перевыпуска обновите токен в скрипте Shelly и настройках station-edge."
        confirmLabel="Перевыпустить токен"
        danger
        busy={rotateBusy}
        onConfirm={() => void confirmRotateToken()}
        onCancel={() => setRotateTarget(null)}
      />
    </div>
  );
}
