import { useMemo, useState, type ReactNode } from "react";
import type { CatalogStation } from "../api/client";
import { useCatalog } from "../catalog";
import { liters, REGIONS, stationRegion } from "../format";
import { SensorStatus, usePublicLevels, type LiveLevel } from "../liveLevels";
import StationDetailPage from "./StationDetailPage";

type StatusFilter = "all" | "low" | "offline" | "no_sensor";

export default function Dashboard({
  stationId,
  onOpenStation,
  onOpenAdminStation,
  onOpenMapStation,
}: {
  stationId: string | null;
  onOpenStation: (id: string | null) => void;
  onOpenAdminStation?: (id: string) => void;
  onOpenMapStation?: (id: string) => void;
}) {
  if (stationId) {
    return (
      <StationDetailPage
        stationId={stationId}
        onBack={() => onOpenStation(null)}
        onSelectStation={(id) => onOpenStation(id)}
        onOpenAdmin={onOpenAdminStation}
        onOpenMap={onOpenMapStation}
      />
    );
  }
  return (
    <Overview
      onOpenStation={onOpenStation}
      onOpenAdminStation={onOpenAdminStation}
      onOpenMapStation={onOpenMapStation}
    />
  );
}

function Overview({
  onOpenStation,
  onOpenAdminStation,
  onOpenMapStation,
}: {
  onOpenStation: (id: string) => void;
  onOpenAdminStation?: (id: string) => void;
  onOpenMapStation?: (id: string) => void;
}) {
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const [query, setQuery] = useState("");
  const [regionFilter, setRegionFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");

  const rows = useMemo(() => {
    return catalog.stations
      .filter((station) => station.is_active)
      .map((station) => {
        const live = byCode.get(station.code) ?? null;
        const hasTanks = !!live && live.tanks.length > 0;
        const fill = hasTanks && live.fill != null ? Math.round(live.fill) : null;
        const online = !!live && live.tanks.some((tank) => tank.online === true && tank.remainder_liters != null);
        return { station, live, hasTanks, fill, online, region: stationRegion(station) };
      });
  }, [catalog.stations, byCode]);

  const totals = useMemo(() => {
    let litersSum = 0;
    let online = 0;
    let offline = 0;
    let noSensor = 0;
    let low = 0;
    for (const row of rows) {
      if (!row.hasTanks) noSensor++;
      else if (row.online) online++;
      else offline++;
      if (row.fill != null && row.fill < 25) low++;
      if (row.live?.remainder != null) litersSum += row.live.remainder;
    }
    return { litersSum, online, offline, noSensor, low, all: rows.length };
  }, [rows]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (q) {
        const hit = [row.station.name, row.station.code, row.station.address, row.region].some((part) =>
          part?.toLowerCase().includes(q)
        );
        if (!hit) return false;
      }
      if (regionFilter !== "all" && row.region !== regionFilter) return false;
      if (statusFilter === "low" && (row.fill == null || row.fill >= 25)) return false;
      if (statusFilter === "offline" && !(row.hasTanks && !row.online)) return false;
      if (statusFilter === "no_sensor" && row.hasTanks) return false;
      return true;
    });
  }, [rows, query, regionFilter, statusFilter]);

  return (
    <div className="dash">
      <header className="dash-hero">
        <p className="kicker">Подключённые АГЗС</p>
        <h2>Остаток газа по датчикам ({totals.all})</h2>
      </header>

      <div className="dash-kpis">
        <div className="dash-kpi">
          <span>Газ в резервуарах</span>
          <strong>{liters(totals.litersSum)}</strong>
          <em>только свежие и последние замеры</em>
        </div>
        <div className="dash-kpi">
          <span>Датчик на связи</span>
          <strong>{totals.online}</strong>
          <em>замер свежий</em>
        </div>
        <div className="dash-kpi">
          <span>Нет связи</span>
          <strong className={totals.offline ? "text-danger" : ""}>{totals.offline}</strong>
          <em>резервуар есть, замер устарел или пуст</em>
        </div>
        <div className="dash-kpi">
          <span>Датчик не подключён</span>
          <strong>{totals.noSensor}</strong>
          <em>в кабинете резервуара нет</em>
        </div>
      </div>

      <section className="dash-section">
        <div className="st-filter-bar">
          <input
            type="search"
            className="st-search-input"
            value={query}
            placeholder="Поиск по названию, коду или адресу…"
            onChange={(event) => setQuery(event.target.value)}
          />
          <select
            className="st-select"
            value={regionFilter}
            aria-label="Район"
            onChange={(event) => setRegionFilter(event.target.value)}
          >
            <option value="all">Все районы ({rows.length})</option>
            {REGIONS.map((region) => {
              const count = rows.filter((row) => row.region === region).length;
              if (!count) return null;
              return (
                <option key={region} value={region}>
                  {region} ({count})
                </option>
              );
            })}
          </select>
        </div>
        <div className="st-status-pills" role="group" aria-label="Фильтр">
          <Filter active={statusFilter === "all"} onClick={() => setStatusFilter("all")}>
            Все ({totals.all})
          </Filter>
          <Filter active={statusFilter === "low"} onClick={() => setStatusFilter("low")}>
            Мало газа ({totals.low})
          </Filter>
          <Filter active={statusFilter === "offline"} onClick={() => setStatusFilter("offline")}>
            Нет связи ({totals.offline})
          </Filter>
          <Filter active={statusFilter === "no_sensor"} onClick={() => setStatusFilter("no_sensor")}>
            Без датчика ({totals.noSensor})
          </Filter>
        </div>

        {catalog.error ? <p className="tank-error">{catalog.error}</p> : null}
        {!catalog.ready ? <p className="dash-muted">Загрузка станций…</p> : null}
        {catalog.ready && visible.length === 0 ? (
          <p className="empty">Подключённых АГЗС по этому фильтру нет.</p>
        ) : (
          <ul className="st-list">
            {visible.map(({ station, live, hasTanks, fill, region }) => (
              <StationRow
                key={station.id}
                station={station}
                region={region}
                fill={fill}
                gas={hasTanks ? live?.remainder ?? null : null}
                cap={hasTanks ? live?.capacity ?? 0 : 0}
                live={hasTanks ? live : null}
                onOpen={() => onOpenStation(station.id)}
                onMap={onOpenMapStation ? () => onOpenMapStation(station.id) : undefined}
                onAdmin={onOpenAdminStation ? () => onOpenAdminStation(station.id) : undefined}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Filter({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className={`filter-pill${active ? " active" : ""}`} onClick={onClick}>
      {children}
    </button>
  );
}

function StationRow({
  station,
  region,
  fill,
  gas,
  cap,
  live,
  onOpen,
  onMap,
  onAdmin,
}: {
  station: CatalogStation;
  region: string;
  fill: number | null;
  gas: number | null;
  cap: number;
  live: LiveLevel | null;
  onOpen: () => void;
  onMap?: () => void;
  onAdmin?: () => void;
}) {
  return (
    <li className="st-list-item">
      <div className="st-row" onClick={onOpen}>
        <div className="st-row-main">
          <strong>{station.name}</strong>
          <span>
            {station.code} · {region}
          </span>
        </div>
        <div className="st-row-fill">
          <div className="fill-bar">
            <i
              style={{
                width: `${fill ?? 0}%`,
                background: fill != null && fill < 25 ? "var(--coral)" : "var(--sea)",
              }}
            />
          </div>
          <span>
            {gas == null ? "замера нет" : `${liters(gas)} из ${liters(cap)}`} ·{" "}
            <strong className={fill != null && fill < 25 ? "text-danger" : ""}>
              {fill == null ? "—" : `${fill}%`}
            </strong>
          </span>
          {live && live.tanks.length > 0 ? <SensorStatus level={live} /> : <span className="badge warn">датчик не подключён</span>}
        </div>
        <div className="st-row-actions" onClick={(event) => event.stopPropagation()}>
          {onMap ? (
            <button type="button" className="btn secondary small" onClick={onMap}>
              Карта
            </button>
          ) : null}
          {onAdmin ? (
            <button type="button" className="btn secondary small" onClick={onAdmin}>
              Админка
            </button>
          ) : null}
        </div>
      </div>
    </li>
  );
}
