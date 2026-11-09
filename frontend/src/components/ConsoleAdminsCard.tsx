import { useEffect, useState } from "react";
import { api, type StationUser } from "../api/client";
import { messageOf } from "../catalog";

export default function ConsoleAdminsCard({
  stationId,
  canCreate = false,
}: {
  stationId: string;
  canCreate?: boolean;
}) {
  const [admins, setAdmins] = useState<StationUser[]>([]);
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
      .consoleAdmins(stationId)
      .then((rows) => {
        if (alive) setAdmins(rows);
      })
      .catch((err: unknown) => {
        if (alive) setError(messageOf(err));
      });
    return () => {
      alive = false;
    };
  }, [stationId]);

  async function createAdmin() {
    setBusy(true);
    setError(null);
    try {
      const created = await api.createConsoleAdmin(stationId, { username, password });
      setAdmins((current) => [...current.filter((row) => row.id !== created.id), created]);
      setIssued(`${created.username} / ${created.password}`);
      setUsername("");
      setPassword("");
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="dash-card" style={{ margin: "0 0 16px" }}>
      <h3>Администраторы пульта</h3>
      <p className="dash-muted">
        Эти логины открывают пульт колонок только этой заправки. Цену газа они не меняют.
      </p>
      {admins.length === 0 ? <p className="dash-muted">Администратор пульта ещё не создан.</p> : null}
      <ul>
        {admins.map((admin) => (
          <li key={admin.id}>
            <strong>{admin.username}</strong>
          </li>
        ))}
      </ul>
      {canCreate ? (
      <form
        className="admin-form"
        onSubmit={(event) => {
          event.preventDefault();
          void createAdmin();
        }}
      >
        <label>
          Логин пульта
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
            {busy ? "Сохраняем…" : "Создать администратора пульта"}
          </button>
        </div>
      </form>
      ) : null}
      {issued ? <p>Пароль показан один раз: {issued}</p> : null}
      {error ? <p className="tank-error">{error}</p> : null}
    </section>
  );
}
