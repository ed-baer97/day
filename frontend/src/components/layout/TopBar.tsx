import Logo from "../Logo";
import { useSim } from "../../sim/SimContext";
import { useTheme } from "../../theme";

export type AppPage = "map" | "dashboard" | "supply";

const PAGES: { id: AppPage; label: string }[] = [
  { id: "map", label: "Карта" },
  { id: "dashboard", label: "Сводка" },
  { id: "supply", label: "Поставка" },
];

export default function TopBar({
  page,
  onNavigate,
}: {
  page: AppPage;
  onNavigate: (page: AppPage) => void;
}) {
  const { theme, toggle } = useTheme();
  const { overview } = useSim();
  const hasAlerts = overview.open_events > 0;

  return (
    <header className="topbar">
      <div className="brand">
        <Logo size={36} className="mark" alt="Цифровой след LPG" />
        <div className="brand-text">
          <h1>Цифровой след LPG</h1>
          <span>Мангыстау · КазГаз → АГЗС</span>
        </div>
      </div>

      <nav className="nav-pages" aria-label="Разделы">
        {PAGES.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`nav-page${page === p.id ? " active" : ""}`}
            onClick={() => onNavigate(p.id)}
            aria-current={page === p.id ? "page" : undefined}
          >
            {p.label}
          </button>
        ))}
      </nav>

      <div className="topbar-actions">
        <div className="stats-chip" aria-live="polite">
          <span>
            рейсы <strong>{overview.active_trips}</strong>
          </span>
          <span className={hasAlerts ? "stat-alert" : undefined}>
            события <strong>{overview.open_events}</strong>
          </span>
        </div>
        <button
          className="btn ghost small theme-toggle"
          type="button"
          onClick={toggle}
          aria-label={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
          title={theme === "dark" ? "Светлая тема" : "Тёмная тема"}
        >
          {theme === "dark" ? "Светлая" : "Тёмная"}
        </button>
      </div>
    </header>
  );
}
