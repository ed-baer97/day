import { useEffect, useState } from "react";
import { api, type StationUser } from "../api/client";
import { messageOf } from "../catalog";

export default function StationOwnerCard({ stationId }: { stationId: string }) {
  const [owners, setOwners] = useState<StationUser[]>([]);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [issued, setIssued] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

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
    try {
      const created = await api.createStationUser(stationId, { username, password });
      setOwners((current) => [...current.filter((row) => row.id !== created.id), created]);
      setIssued(created.password);
      setUsername("");
      setPassword("");
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="dash-card">
      <h3>Владелец заправки</h3>
      <p className="dash-muted">
        Владелец видит свои заправки, задаёт цену газа и создаёт администраторов пульта. Один логин можно привязать к
        нескольким заправкам: укажите его ещё раз на другой АГЗС.
      </p>
      {owners.length === 0 ? <p className="dash-muted">Владелец ещё не назначен.</p> : null}
      <ul>
        {owners.map((owner) => (
          <li key={owner.id}>
            <strong>{owner.username}</strong>
          </li>
        ))}
      </ul>
      <form
        className="admin-form"
        onSubmit={(event) => {
          event.preventDefault();
          void createOwner();
        }}
      >
        <label>
          Логин владельца
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="off" required />
        </label>
        <label>
          Пароль
          <input
            type="text"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete="new-password"
            minLength={6}
            required
          />
        </label>
        <div className="admin-actions span-3">
          <button type="submit" className="btn small" disabled={busy}>
            {busy ? "Сохраняем…" : "Назначить владельца"}
          </button>
        </div>
      </form>
      {issued ? <p>Пароль показан один раз: {issued}</p> : null}
      {error ? <p className="tank-error">{error}</p> : null}
    </section>
  );
}
