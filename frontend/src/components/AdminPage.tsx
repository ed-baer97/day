import { useEffect, useMemo, useState } from "react";
import {
  api,
  type BatchRecord,
} from "../api/client";
import { isAdmin } from "../access";
import { useAuth } from "../auth";
import { messageOf, useCatalog } from "../catalog";
import { stationRegion } from "../format";
import { isLowFill, usePublicLevels } from "../liveLevels";
import type { DiscrepancyEvent } from "../types";
import { useToast } from "./Toast";
import { ADMIN_SECTIONS, type AdminTab } from "../pages/admin/types";
import AdminReconcileTab from "../pages/admin/AdminReconcileTab";
import AdminSecurityTab from "../pages/admin/AdminSecurityTab";
import AdminStationsTab from "../pages/admin/AdminStationsTab";
import AdminSuppliesTab from "../pages/admin/AdminSuppliesTab";
import AdminTrucksTab from "../pages/admin/AdminTrucksTab";

function scrollAdminTop() {
  document.querySelector(".page.dash-page")?.scrollTo({ top: 0 });
}

export default function AdminPage({
  initialTab,
  initialStationId,
  initialTruckId,
  onOpenStationDashboard,
  onOpenStationMap,
  onTrailChange,
}: {
  initialTab?: AdminTab;
  initialStationId?: string | null;
  initialTruckId?: string | null;
  onOpenStationDashboard?: (id: string) => void;
  onOpenStationMap?: (id: string) => void;
  onTrailChange?: (trail: {
    tab: AdminTab;
    stationId: string | "new" | null;
    truckId: string | "new" | null;
  }) => void;
}) {
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();
  const { session } = useAuth();
  const toast = useToast();
  const admin = isAdmin(session);

  const [tab, setTab] = useState<AdminTab>(initialTab ?? (initialTruckId ? "trucks" : "stations"));
  const [stationId, setStationId] = useState<string | "new" | null>(initialStationId ?? null);
  const [truckId, setTruckId] = useState<string | "new" | null>(initialTruckId ?? null);

  // Фильтры и пагинация для большого количества АГЗС в админке
  const [stQuery, setStQuery] = useState("");
  const [stRegion, setStRegion] = useState<string>("all");
  const [stFilter, setStFilter] = useState<"all" | "active" | "inactive" | "issue" | "low">("all");
  const [stPageSize, setStPageSize] = useState<number>(10);
  const [stPage, setStPage] = useState<number>(1);

  // Фильтры для газовозов
  const [trQuery, setTrQuery] = useState("");
  const [trStatus, setTrStatus] = useState<string>("all");

  // Партии и события для вкладок Поставки и Сверка
  const [batches, setBatches] = useState<BatchRecord[]>([]);
  const [events, setEvents] = useState<DiscrepancyEvent[]>([]);
  const [batchCode, setBatchCode] = useState("");
  const [batchGrade, setBatchGrade] = useState("ПБТ (пропан-бутан технический)");
  const [batchVol, setBatchVol] = useState("18000");
  const [batchNotes, setBatchNotes] = useState("");
  const [batchSaving, setBatchSaving] = useState(false);

  useEffect(() => {
    if (!initialTab) return;
    setTab(initialTab);
    if (initialTab === "stations") setStationId(initialStationId ?? null);
    if (initialTab === "trucks") setTruckId(initialTruckId ?? null);
  }, [initialTab, initialStationId, initialTruckId]);

  useEffect(() => {
    onTrailChange?.({ tab, stationId, truckId });
  }, [onTrailChange, tab, stationId, truckId]);

  useEffect(() => {
    if (!admin) return;
    let alive = true;
    api
      .batches()
      .then((rows) => {
        if (alive) setBatches(rows);
      })
      .catch(() => undefined);
    api
      .events(undefined, false)
      .then((rows) => {
        if (alive) setEvents(rows);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [admin, tab]);

  const enrichedCatalogStations = useMemo(
    () =>
      catalog.stations.map((row) => {
        const live = byCode.get(row.code) ?? null;
        const hasLive = !!live && live.tanks.length > 0;
        const cap = hasLive && live.capacity > 0 ? live.capacity : 0;
        const actual = hasLive ? live.remainder : null;
        const fill = hasLive && live.fill != null ? Math.round(live.fill) : null;
        const free = actual != null && cap > 0 ? Math.max(0, cap - actual) : null;
        const safeRefill =
          actual != null && cap > 0 ? Math.max(0, Math.round(cap * 0.85) - actual) : null;
        const online = !!live && live.tanks.some((t) => t.online && t.remainder_liters != null);
        const region = stationRegion(row);
        return { row, cap, actual, fill, free, safeRefill, online, live, region };
      }),
    [catalog.stations, byCode]
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
      if (
        stFilter === "issue" &&
        !(item.live && item.live.tanks.length > 0 && !item.live.tanks.some((tank) => tank.online))
      )
        return false;
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

  const stationIndex = catalog.stations.findIndex((row) => row.id === stationId);
  const station = stationIndex >= 0 ? catalog.stations[stationIndex] : null;
  const stationEnriched = enrichedCatalogStations.find((item) => item.row.id === stationId) ?? null;
  const prevStation =
    stationIndex > 0
      ? catalog.stations[stationIndex - 1]
      : catalog.stations[catalog.stations.length - 1];
  const nextStation =
    stationIndex >= 0 && stationIndex < catalog.stations.length - 1
      ? catalog.stations[stationIndex + 1]
      : catalog.stations[0];

  const truck = catalog.trucks.find((row) => row.id === truckId) ?? null;
  const heading =
    tab === "stations"
      ? stationId === "new"
        ? "Новая АГЗС"
        : (station?.name ?? "Управление сетью АГЗС")
      : tab === "trucks"
        ? truckId === "new"
          ? "Новый газовоз"
          : (truck?.plate_number ?? "Парк газовозов")
        : tab === "supplies"
          ? "Планирование подвоза и партии LPG"
          : tab === "reconcile"
            ? "Сверка баланса и аудит датчиков"
            : "Безопасность и разграничение доступа";

  async function handleCreateBatch() {
    const vol = Number(batchVol.replace(",", "."));
    if (!batchCode.trim() || !Number.isFinite(vol) || vol <= 0) {
      toast.err("Укажите код партии и объём (> 0 л)");
      return;
    }
    setBatchSaving(true);
    try {
      const created = await api.createBatch({
        trail_code: batchCode.trim(),
        product_grade: batchGrade.trim() || undefined,
        volume_liters: vol,
        notes: batchNotes.trim() || undefined,
      });
      setBatches((cur) => [created, ...cur]);
      setBatchCode("");
      setBatchNotes("");
      toast.ok(`Партия ${created.trail_code} зарегистрирована`);
    } catch (err) {
      toast.err(messageOf(err));
    } finally {
      setBatchSaving(false);
    }
  }

  async function handleResolveEvent(id: string) {
    try {
      const resolved = await api.resolveEvent(id, "Проверено администратором");
      setEvents((cur) => cur.map((item) => (item.id === id ? resolved : item)));
      toast.ok("Событие отмечено как решённое");
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

  const deliveryNeeds = [...enrichedCatalogStations]
    .filter((item) => item.row.is_active)
    .sort((a, b) => (a.fill ?? 101) - (b.fill ?? 101));

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
                  : item.id === "supplies"
                    ? batches.length
                    : item.id === "reconcile"
                      ? events.filter((e) => !e.is_resolved).length
                      : null;
            return (
              <button
                key={item.id}
                type="button"
                className={tab === item.id ? "active" : ""}
                aria-current={tab === item.id ? "page" : undefined}
                onClick={() => {
                  setTab(item.id);
                  scrollAdminTop();
                }}
              >
                <span className="admin-nav-label">
                  {item.label}
                  {count != null ? <em>{count}</em> : null}
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
              stationId={stationId}
              setStationId={setStationId}
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
              toast={toast}
              scrollTop={scrollAdminTop}
            />
          )}

          {tab === "trucks" && (
            <AdminTrucksTab
              catalog={catalog}
              truckId={truckId}
              setTruckId={setTruckId}
              truck={truck}
              query={trQuery}
              setQuery={setTrQuery}
              status={trStatus}
              setStatus={setTrStatus}
              filtered={filteredTrucks}
              toast={toast}
              scrollTop={scrollAdminTop}
            />
          )}

          {tab === "supplies" && (
            <AdminSuppliesTab
              batches={batches}
              deliveryNeeds={deliveryNeeds}
              batchCode={batchCode}
              setBatchCode={setBatchCode}
              batchGrade={batchGrade}
              setBatchGrade={setBatchGrade}
              batchVol={batchVol}
              setBatchVol={setBatchVol}
              batchNotes={batchNotes}
              setBatchNotes={setBatchNotes}
              batchSaving={batchSaving}
              onCreateBatch={() => void handleCreateBatch()}
              onOpenStation={(id) => {
                setTab("stations");
                setStationId(id);
                scrollAdminTop();
              }}
              scrollTop={scrollAdminTop}
            />
          )}

          {tab === "reconcile" && (
            <AdminReconcileTab
              enriched={enrichedCatalogStations}
              events={events}
              stations={catalog.stations}
              onResolve={(id) => void handleResolveEvent(id)}
            />
          )}

          {tab === "security" && <AdminSecurityTab username={session?.username} />}
        </div>
      </div>
    </div>
  );
}
