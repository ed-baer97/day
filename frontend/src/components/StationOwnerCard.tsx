import { useEffect, useState } from "react";
import { api, type OwnerAccount, type StationUser } from "../api/client";
import { messageOf } from "../catalog";
import ConfirmModal from "./ConfirmModal";
import { useToast } from "./Toast";

export default function StationOwnerCard({
  stationId,
  allOwners = [],
  onChanged,
  onOpenAccessTab,
}: {
  stationId: string;
  allOwners?: OwnerAccount[];
  onChanged?: () => void;
  onOpenAccessTab?: () => void;
}) {
  const toast = useToast();
  const [owners, setOwners] = useState<StationUser[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [issued, setIssued] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [detachTarget, setDetachTarget] = useState<StationUser | null>(null);

  const normalizedLogin = username.trim().toLowerCase();
  const isExistingOwner =
    normalizedLogin.length > 0 &&
    allOwners.some((owner) => owner.username.toLowerCase() === normalizedLogin);

  useEffect(() => {
    let alive = true;
    setIssued(null);
    setError(null);
    api
      .stationUsers(stationId)
      .then((rows) => {
        if (alive) setOwners(rows);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        const text = messageOf(err);
        if (text !== "Not Found") setError(text);
      });
    return () => {
      alive = false;
    };
  }, [stationId]);

  async function createOwner() {
    setBusy(true);
    setError(null);
    setIssued(null);
    try {
      const created = await api.createStationUser(stationId, {
        username,
        password: isExistingOwner ? "" : password,
      });
      setOwners((current) => [...current.filter((row) => row.id !== created.id), created]);
      if (created.password_applied !== false && created.password) {
        setIssued(created.password);
        toast.ok(`Владелец ${created.username} создан и привязан`);
      } else {
        toast.ok(`Существующий владелец ${created.username} привязан с прежним паролем`);
      }
      setUsername("");
      setPassword("");
      onChanged?.();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirmDetach() {
    if (!detachTarget) return;
    setBusy(true);
    setError(null);
    try {
      await api.detachStationUser(stationId, detachTarget.username);
      setOwners((current) => current.filter((row) => row.username !== detachTarget.username));
      toast.ok(`Владелец ${detachTarget.username} отвязан от АГЗС`);
      setDetachTarget(null);
      onChanged?.();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="dash-card">
      <div className="card-head-inline">
        <h3 style={{ margin: 0 }}>Владелец заправки</h3>
        {onOpenAccessTab ? (
          <button type="button" className="btn secondary small" onClick={onOpenAccessTab}>
            Все владельцы и сброс паролей →
          </button>
        ) : null}
      </div>
      <p className="dash-muted">
        Владелец видит свои заправки, остатки, отпуск по колонкам и журнал замеров. Один логин
        можно привязать к нескольким АГЗС.
      </p>

      {owners.length === 0 ? (
        <p className="dash-muted">Владелец ещё не назначен.</p>
      ) : (
        <div className="owner-chips" style={{ marginBottom: 12 }}>
          {owners.map((owner) => (
            <span key={owner.id} className="owner-chip">
              <strong>{owner.username}</strong>
              <button
                type="button"
                className="owner-chip-remove"
                title={`Отвязать ${owner.username}`}
                onClick={() => setDetachTarget(owner)}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <form
        className="admin-form"
        onSubmit={(event) => {
          event.preventDefault();
          void createOwner();
        }}
      >
        <label>
          Логин владельца
          <input
            list={`owners-suggest-${stationId}`}
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="off"
            required
          />
          <datalist id={`owners-suggest-${stationId}`}>
            {allOwners.map((owner) => (
              <option key={owner.id} value={owner.username} />
            ))}
          </datalist>
        </label>
        {isExistingOwner ? (
          <div className="span-2" style={{ display: "flex", alignItems: "flex-end" }}>
            <p className="dash-muted" style={{ margin: 0 }}>
              Логин уже существует: при привязке сохранится текущий пароль владельца.
            </p>
          </div>
        ) : (
          <label>
            Пароль (не менее 6 символов)
            <input
              type="text"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete="new-password"
              minLength={6}
              required
            />
          </label>
        )}
        <div className="admin-actions span-3">
          <button type="submit" className="btn small" disabled={busy}>
            {busy
              ? "Сохраняем…"
              : isExistingOwner
                ? "Привязать существующего владельца"
                : "Назначить владельца"}
          </button>
        </div>
      </form>
      {issued ? <p>Пароль показан один раз: <code>{issued}</code></p> : null}
      {error ? <p className="tank-error">{error}</p> : null}

      <ConfirmModal
        open={detachTarget !== null}
        title="Отвязать владельца?"
        message={`Пользователь «${detachTarget?.username ?? ""}» потеряет доступ к этой АГЗС.`}
        details="Если у владельца нет других привязанных АГЗС, его учётная запись будет удалена."
        confirmLabel="Отвязать"
        danger
        busy={busy}
        onConfirm={() => void confirmDetach()}
        onCancel={() => setDetachTarget(null)}
      />
    </section>
  );
}
