import { useCallback, useEffect, useMemo, useState } from "react";
import { isAdmin } from "../access";
import {
  api,
  type AdminStationOverview,
  type EdgeFleetSummary,
  type OwnerAccount,
} from "../api/client";
import { useAuth } from "../auth";
import { messageOf, useCatalog } from "../catalog";
import { stationRegion } from "../format";
import { isLowFill, usePublicLevels } from "../liveLevels";
import AdminAccessTab from "../pages/admin/AdminAccessTab";
import AdminEdgeTab from "../pages/admin/AdminEdgeTab";
import AdminReconcileTab from "../pages/admin/AdminReconcileTab";
import AdminStationsTab, { type StationAdminFilter } from "../pages/admin/AdminStationsTab";
import AdminTrucksTab from "../pages/admin/AdminTrucksTab";
import { ADMIN_SECTIONS, type AdminTab, type EnrichedStation } from "../pages/admin/types";
import { freeVolumeLiters, POLL_MS, safeRefillLiters } from "../policy";
import type { DiscrepancyEvent } from "../types";
import { useToast } from "./Toast";

function scrollAdminTop() {
  document.querySelector(".page.dash-page")?.scrollTo({ top: 0 });
}

export default function AdminPage({
  tab,
  stationId,
  truckId,
  onSelectTab,
  onSelectStationId,
  onSelectTruckId,
  onOpenStationDashboard,
  onOpenStationMap,
  onOpenTruckMap,
}: {
  tab: AdminTab;
  stationId: string | null;
  truckId: string | null;
  onSelectTab: (tab: AdminTab) => void;
  onSelectStationId: (id: string | "new" | null) => void;
  onSelectTruckId: (id: string | "new" | null) => void;
  onOpenStationDashboard?: (id: string) => void;
  onOpenStationMap?: (id: string) => void;
  onOpenTruckMap?: (id: string) => void;
}) {
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const { session } = useAuth();
  const toast = useToast();
  const admin = isAdmin(session);

  // Фильтры и пагинация для списка АГЗС
  const [stQuery, setStQuery] = useState("");
  const [stRegion, setStRegion] = useState<string>("all");
  const [stFilter, setStFilter] = useState<StationAdminFilter>("all");
  const [stPageSize, setStPageSize] = useState<number>(10);
  const [stPage, setStPage] = useState<number>(1);

  // Фильтры для газовозов
  const [trQuery, setTrQuery] = useState("");
  const [trStatus, setTrStatus] = useState<string>("all");

  // Централизованные данные кабинета администратора
  const [overviewList, setOverviewList] = useState<AdminStationOverview[]>([]);
  const [events, setEvents] = useState<DiscrepancyEvent[]>([]);
  const [owners, setOwners] = useState<OwnerAccount[]>([]);
  const [edgeFleet, setEdgeFleet] = useState<EdgeFleetSummary | null>(null);
  const [edgeLoading, setEdgeLoading] = useState(false);

  const refreshOverview = useCallback(async () => {
    if (!admin) return;
    try {
      const rows = await api.stationsOverview();
      setOverviewList(rows);
    } catch {
      /* фоновое обновление */
    }
  }, [admin]);

  const refreshEvents = useCallback(async () => {
    if (!admin) return;
    try {
      const rows = await api.events(undefined, false);
      setEvents(rows);
    } catch {
      /* фоновое обновление */
    }
  }, [admin]);

  const refreshOwners = useCallback(async () => {
    if (!admin) return;
    try {
      const rows = await api.owners();
      setOwners(rows);
    } catch {
      /* фоновое обновление */
    }
  }, [admin]);

  const refreshEdgeFleet = useCallback(async () => {
    if (!admin) return;
    setEdgeLoading(true);
    try {
      const summary = await api.edgeFleet();
      setEdgeFleet(summary);
    } catch {
      /* фоновое обновление */
    } finally {
      setEdgeLoading(false);
    }
  }, [admin]);

  useEffect(() => {
    if (!admin) return;
    void refreshOverview();
    void refreshEvents();
    void refreshOwners();
    void refreshEdgeFleet();
    const timer = window.setInterval(() => {
      void refreshOverview();
      void refreshEvents();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [admin, refreshOverview, refreshEvents, refreshOwners, refreshEdgeFleet]);

  useEffect(() => {
    if (!admin) return;
    if (tab === "edge") void refreshEdgeFleet();
    if (tab === "reconcile") {
      void refreshOverview();
      void refreshEvents();
    }
    if (tab === "access") {
      void refreshOwners();
      void refreshOverview();
    }
  }, [admin, tab, refreshEdgeFleet, refreshOverview, refreshEvents, refreshOwners]);

  const overviewById = useMemo(() => {
    const map = new Map<string, AdminStationOverview>();
    for (const item of overviewList) map.set(item.id, item);
    return map;
  }, [overviewList]);

  const enrichedCatalogStations = useMemo<EnrichedStation[]>(
    () =>
      catalog.stations.map((row) => {
        const overview = overviewById.get(row.id) ?? null;
        const live = byCode.get(row.code) ?? null;
        const region = stationRegion(row);

        if (overview) {
          const tanks = overview.tanks;
          const tanksCount = tanks.length;
          const calibratedCount = tanks.filter((t) => t.calibrated).length;
          const cap = tanks.reduce((sum, t) => sum + (t.capacity_liters || 0), 0);
          const knownActual = tanks.filter((t) => t.actual_remainder_liters != null);
          const actual = knownActual.length
            ? knownActual.reduce((sum, t) => sum + (t.actual_remainder_liters ?? 0), 0)
            : null;
          const fill =
            actual != null && cap > 0 ? Math.round((actual / cap) * 100) : null;
          const free = freeVolumeLiters(cap, actual);
          const safeRefill = safeRefillLiters(cap, actual);
          const online = tanks.some((t) => t.online && t.actual_remainder_liters != null);
          const knownCalc = tanks.filter((t) => t.calculated_remainder_liters != null);
          const bookCalc = knownCalc.length
            ? knownCalc.reduce((sum, t) => sum + (t.calculated_remainder_liters ?? 0), 0)
            : null;
          const bookDelta =
            bookCalc != null && actual != null ? Math.round(actual - bookCalc) : null;
          const balanceStatus =
            tanks.find((t) => t.balance_status === "shortage" || t.balance_status === "surplus")
              ?.balance_status ??
            tanks.find((t) => t.balance_status === "warn")?.balance_status ??
            (knownCalc.length > 0 ? "ok" : "unknown");
          return {
            row,
            overview,
            cap,
            actual,
            fill,
            free,
            safeRefill,
            online,
            live,
            region,
            tanksCount,
            calibratedCount,
            bookCalc,
            bookDelta,
            balanceStatus,
          };
        }

        const hasLive = !!live && live.tanks.length > 0;
        const cap = hasLive && live.capacity > 0 ? live.capacity : 0;
        const actual = hasLive ? live.remainder : null;
        const fill = hasLive && live.fill != null ? Math.round(live.fill) : null;
        const free = freeVolumeLiters(cap, actual);
        const safeRefill = safeRefillLiters(cap, actual);
        const online = !!live && live.tanks.some((t) => t.online && t.remainder_liters != null);
        return {
          row,
          overview: null,
          cap,
          actual,
          fill,
          free,
          safeRefill,
          online,
          live,
          region,
          tanksCount: live?.tanks.length ?? 0,
          calibratedCount: 0,
          bookCalc: null,
          bookDelta: null,
          balanceStatus: "unknown",
        };
      }),
    [catalog.stations, overviewById, byCode]
  );

  const filteredStations = useMemo(() => {
    const q = stQuery.trim().toLowerCase();
    return enrichedCatalogStations.filter((item) => {
      if (q) {
        const hit = [item.row.name, item.row.code, item.row.address, item.region].some((p) =>
          p?.toLowerCase().includes(q)
        );
        if (!hit) return false;
      }
      if (stRegion !== "all" && item.region !== stRegion) return false;
      if (stFilter === "active" && !item.row.is_active) return false;
      if (stFilter === "inactive" && item.row.is_active) return false;
      if (stFilter === "issue" && !(item.tanksCount > 0 && !item.online)) return false;
      if (stFilter === "no_sensor" && item.tanksCount > 0) return false;
      if (stFilter === "low" && !isLowFill(item.fill)) return false;
      return true;
    });
  }, [enrichedCatalogStations, stQuery, stRegion, stFilter]);

  const totalStPages = Math.max(1, Math.ceil(filteredStations.length / stPageSize));
  const safeStPage = Math.min(stPage, totalStPages);
  const pagedStations = useMemo(() => {
    const start = (safeStPage - 1) * stPageSize;
    return filteredStations.slice(start, start + stPageSize);
  }, [filteredStations, safeStPage, stPageSize]);

  const filteredTrucks = useMemo(() => {
    const q = trQuery.trim().toLowerCase();
    return catalog.trucks.filter((row) => {
      if (q) {
        const hit = [row.plate_number, row.carrier_name].some((p) => p?.toLowerCase().includes(q));
        if (!hit) return false;
      }
      if (trStatus !== "all" && row.status !== trStatus) return false;
      return true;
    });
  }, [catalog.trucks, trQuery, trStatus]);

  const station = catalog.stations.find((row) => row.id === stationId) ?? null;
  const stationEnriched =
    enrichedCatalogStations.find((item) => item.row.id === stationId) ?? null;
  const navStationsList = useMemo(
    () =>
      filteredStations.some((f) => f.row.id === stationId)
        ? filteredStations.map((f) => f.row)
        : catalog.stations,
    [filteredStations, catalog.stations, stationId]
  );
  const navIndex = navStationsList.findIndex((row) => row.id === stationId);
  const prevStation =
    navIndex > 0 ? navStationsList[navIndex - 1] : navStationsList[navStationsList.length - 1];
  const nextStation =
    navIndex >= 0 && navIndex < navStationsList.length - 1
      ? navStationsList[navIndex + 1]
      : navStationsList[0];

  const truck = catalog.trucks.find((row) => row.id === truckId) ?? null;
  const heading =
    tab === "stations"
      ? stationId === "new"
        ? "Новая АГЗС"
        : (station?.name ?? "АГЗС и оборудование")
      : tab === "trucks"
        ? truckId === "new"
          ? "Новый газовоз"
          : (truck?.plate_number ?? "Автопарк газовозов")
        : tab === "edge"
          ? "Edge-узлы и OTA-обновления"
          : tab === "reconcile"
            ? "Сверка баланса и инциденты"
            : "Пользователи, владельцы и токены";

  async function handleResolveEvent(id: string, note: string) {
    try {
      const resolved = await api.resolveEvent(id, note);
      setEvents((cur) => cur.map((item) => (item.id === id ? resolved : item)));
      toast.ok("Событие отмечено как закрытое");
    } catch (err) {
      toast.err(messageOf(err));
    }
  }

  if (!admin) {
    return (
      <div className="dash">
        <p className="empty">Раздел только для администратора.</p>
      </div>
    );
  }

  return (
    <div className="dash admin">
      <div className="admin-shell">
        <nav className="admin-nav" aria-label="Разделы администратора">
          <p className="kicker">Разделы админки</p>
          {ADMIN_SECTIONS.map((item) => {
            const count =
              item.id === "stations"
                ? catalog.stations.length
                : item.id === "trucks"
                  ? catalog.trucks.length
                  : item.id === "edge"
                    ? edgeFleet?.total_nodes ?? 0
                    : item.id === "reconcile"
                      ? events.filter((e) => !e.is_resolved).length
                      : owners.length;
            return (
              <button
                key={item.id}
                type="button"
                className={tab === item.id ? "active" : ""}
                aria-current={tab === item.id ? "page" : undefined}
                onClick={() => {
                  onSelectTab(item.id);
                  scrollAdminTop();
                }}
              >
                <span className="admin-nav-label">
                  {item.label}
                  <em>{count}</em>
                </span>
                <small>{item.note}</small>
              </button>
            );
          })}
        </nav>

        <div className="admin-main">
          <header className="admin-toolbar">
            <div>
              <p className="kicker">
                Администратор платформы ·{" "}
                {ADMIN_SECTIONS.find((s) => s.id === tab)?.label ?? "Управление"}
              </p>
              <h2>{heading}</h2>
            </div>
          </header>
          {catalog.error ? <p className="tank-error">{catalog.error}</p> : null}

          {tab === "stations" && (
            <AdminStationsTab
              catalog={catalog}
              enriched={enrichedCatalogStations}
              owners={owners}
              edgeFleet={edgeFleet}
              stationId={stationId}
              setStationId={onSelectStationId}
              station={station}
              stationEnriched={stationEnriched}
              prevStation={prevStation}
              nextStation={nextStation}
              query={stQuery}
              setQuery={setStQuery}
              region={stRegion}
              setRegion={setStRegion}
              filter={stFilter}
              setFilter={setStFilter}
              pageSize={stPageSize}
              setPageSize={setStPageSize}
              setPage={setStPage}
              filtered={filteredStations}
              paged={pagedStations}
              totalPages={totalStPages}
              safePage={safeStPage}
              onOpenStationDashboard={onOpenStationDashboard}
              onOpenStationMap={onOpenStationMap}
              onOpenAccessTab={() => {
                onSelectTab("access");
                scrollAdminTop();
              }}
              onRefreshOverview={() => void refreshOverview()}
              onRefreshOwners={() => void refreshOwners()}
              toast={toast}
              scrollTop={scrollAdminTop}
            />
          )}

          {tab === "trucks" && (
            <AdminTrucksTab
              catalog={catalog}
              truckId={truckId}
              setTruckId={onSelectTruckId}
              truck={truck}
              query={trQuery}
              setQuery={setTrQuery}
              status={trStatus}
              setStatus={setTrStatus}
              filtered={filteredTrucks}
              onOpenTruckMap={onOpenTruckMap}
              toast={toast}
              scrollTop={scrollAdminTop}
            />
          )}

          {tab === "edge" && (
            <AdminEdgeTab
              fleet={edgeFleet}
              stations={catalog.stations}
              loading={edgeLoading}
              onRefresh={refreshEdgeFleet}
              onOpenStation={(sid) => {
                onSelectStationId(sid);
                scrollAdminTop();
              }}
              toast={toast}
            />
          )}

          {tab === "reconcile" && (
            <AdminReconcileTab
              enriched={enrichedCatalogStations}
              events={events}
              stations={catalog.stations}
              onResolve={handleResolveEvent}
              onRefresh={async () => {
                await Promise.all([refreshOverview(), refreshEvents()]);
              }}
              onOpenStation={(sid) => {
                onSelectStationId(sid);
                scrollAdminTop();
              }}
              toast={toast}
            />
          )}

          {tab === "access" && (
            <AdminAccessTab
              username={session?.username}
              stations={catalog.stations}
              overview={overviewList}
              owners={owners}
              onRefreshOwners={refreshOwners}
              onRefreshOverview={refreshOverview}
              onOpenStation={(sid) => {
                onSelectStationId(sid);
                scrollAdminTop();
              }}
              toast={toast}
            />
          )}
        </div>
      </div>
    </div>
  );
}
