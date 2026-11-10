import type { CatalogStation } from "../api/client";
import { stationRegion } from "../format";
import type { AppScreen } from "./Topbar";

export default function BreadcrumbBar({
  screen,
  isStationSide,
  admin,
  activeContextStation,
  dashStationId,
  adminStationId,
  mapSelectedId,
  onGoHomeDashboard,
  onClearSectionSelection,
  onOpenStationPage,
  onOpenStationOnMap,
  onOpenAdminStation,
}: {
  screen: AppScreen;
  isStationSide: boolean;
  admin: boolean;
  activeContextStation: CatalogStation | null;
  dashStationId: string | null;
  adminStationId: string | null;
  mapSelectedId?: string;
  onGoHomeDashboard: () => void;
  onClearSectionSelection: () => void;
  onOpenStationPage: (id: string) => void;
  onOpenStationOnMap: (id: string) => void;
  onOpenAdminStation: (id: string) => void;
}) {
  return (
    <div className="breadcrumb-bar" role="navigation" aria-label="Путь по разделу">
      <div className="breadcrumb-trail">
        <button type="button" className="breadcrumb-link" onClick={onGoHomeDashboard}>
          {isStationSide ? "Кабинет АГЗС" : "Диспетчерская"}
        </button>
        <span className="breadcrumb-sep">/</span>
        <button
          type="button"
          className={`breadcrumb-link${!activeContextStation ? " current" : ""}`}
          onClick={onClearSectionSelection}
        >
          {screen === "dashboard"
            ? "Мониторинг сети АГЗС"
            : screen === "map"
              ? "Интерактивная карта"
              : screen === "supply"
                ? "Контур поставок и газовозов"
                : "Панель администратора"}
        </button>
        {activeContextStation ? (
          <>
            <span className="breadcrumb-sep">/</span>
            <span className="dash-muted">{stationRegion(activeContextStation)}</span>
            <span className="breadcrumb-sep">/</span>
            <strong className="breadcrumb-current">
              {activeContextStation.name} ({activeContextStation.code})
            </strong>
          </>
        ) : null}
      </div>

      {activeContextStation ? (
        <div className="breadcrumb-actions">
          <span className="dash-muted">Режим просмотра станции:</span>
          <button
            type="button"
            className={`filter-pill${screen === "dashboard" && dashStationId === activeContextStation.id ? " active" : ""}`}
            onClick={() => onOpenStationPage(activeContextStation.id)}
          >
            Сводка и графики
          </button>
          {!isStationSide ? (
            <button
              type="button"
              className={`filter-pill${screen === "map" && mapSelectedId === activeContextStation.id ? " active" : ""}`}
              onClick={() => onOpenStationOnMap(activeContextStation.id)}
            >
              На карте
            </button>
          ) : null}
          {admin ? (
            <button
              type="button"
              className={`filter-pill${screen === "admin" && adminStationId === activeContextStation.id ? " active" : ""}`}
              onClick={() => onOpenAdminStation(activeContextStation.id)}
            >
              Настройки в админке
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
