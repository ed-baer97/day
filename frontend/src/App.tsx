import { useEffect, useMemo, useRef, useState } from "react";
import { isAdmin } from "./access";
import { api, type BatchRecord } from "./api/client";
import { useAuth } from "./auth";
import { useCatalog } from "./catalog";
import AdminPage from "./components/AdminPage";
import Dashboard from "./components/Dashboard";
import Landing from "./components/Landing";
import BreadcrumbBar from "./layout/BreadcrumbBar";
import Topbar, { type AppScreen, type NetworkStats } from "./layout/Topbar";
import { isLowFill, usePublicLevels } from "./liveLevels";
import MapScreen, { type MapSelection } from "./pages/MapScreen";
import SupplyPage from "./pages/SupplyPage";
import { useTheme } from "./theme";
import type { MapPoint } from "./types";

export default function App() {
  const { theme, toggle } = useTheme();
  const { session, logout } = useAuth();
  const admin = isAdmin(session);
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();

  const [page, setPage] = useState<AppScreen>("landing");
  const [selection, setSelection] = useState<MapSelection>(null);
  const [dashStationId, setDashStationId] = useState<string | null>(null);
  const [adminStationId, setAdminStationId] = useState<string | null>(null);
  const [adminTruckId, setAdminTruckId] = useState<string | null>(null);
  const [mapHudTab, setMapHudTab] = useState<"stations" | "trucks">("stations");
  const [batches, setBatches] = useState<BatchRecord[]>([]);
  const dashRef = useRef<HTMLElement>(null);

  useEffect(() => {
    dashRef.current?.scrollTo(0, 0);
  }, [dashStationId, page, adminStationId, adminTruckId]);

  useEffect(() => {
    if (!admin || page !== "supply") return;
    let alive = true;
    api
      .batches()
      .then((rows) => {
        if (alive) setBatches(rows);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [admin, page]);

  function openStationPage(id: string) {
    setDashStationId(id);
    setPage("dashboard");
  }

  function openStationOnMap(id: string) {
    setSelection({ kind: "station", id });
    setMapHudTab("stations");
    setPage("map");
  }

  function openTruckOnMap(id: string) {
    setSelection({ kind: "truck", id });
    setMapHudTab("trucks");
    setPage("map");
  }

  function openAdminStation(id: string) {
    setAdminTruckId(null);
    setAdminStationId(id);
    setPage("admin");
  }

  function openAdminTruck(id: string) {
    setAdminStationId(null);
    setAdminTruckId(id);
    setPage("admin");
  }

  const isOwner = session?.role === "owner" || session?.role === "station";
  const isStationSide = isOwner;
  const stations = useMemo(
    () => catalog.stations.filter((row) => row.is_active),
    [catalog.stations]
  );

  useEffect(() => {
    if (isStationSide && page !== "landing" && page !== "dashboard") setPage("dashboard");
  }, [isStationSide, page]);

  useEffect(() => {
    if (isStationSide && stations.length === 1) setDashStationId(stations[0].id);
  }, [isStationSide, stations]);

  const networkStats = useMemo<NetworkStats>(() => {
    let litersSum = 0;
    let capSum = 0;
    let online = 0;
    let offline = 0;
    let low = 0;
    for (const row of stations) {
      const live = byCode.get(row.code);
      const hasTanks = !!live && live.tanks.length > 0;
      const fill = hasTanks && live?.fill != null ? Math.round(live.fill) : null;
      const isOnline =
        !!live && live.tanks.some((tank) => tank.online === true && tank.remainder_liters != null);
      if (hasTanks && live) {
        capSum += live.capacity;
        if (live.remainder != null) litersSum += live.remainder;
        if (isOnline) online++;
        else offline++;
      } else {
        offline++;
      }
      if (isLowFill(fill)) low++;
    }
    return {
      litersSum,
      capSum,
      freeSum: Math.max(0, capSum - litersSum),
      online,
      offline,
      low,
    };
  }, [stations, byCode]);

  const mapPoints = useMemo<MapPoint[]>(() => {
    const stationPoints = stations.map((row) => ({
      id: row.id,
      kind: "station" as const,
      name: row.name,
      lat: row.lat,
      lon: row.lon,
      status: "active",
    }));
    const truckPoints = catalog.trucks
      .filter((row) => row.lat != null && row.lon != null)
      .map((row) => ({
        id: row.id,
        kind: "truck" as const,
        name: row.plate_number,
        lat: row.lat as number,
        lon: row.lon as number,
        status: row.status,
      }));
    return [...stationPoints, ...truckPoints];
  }, [stations, catalog.trucks]);

  const screen: AppScreen = !admin && (page === "admin" || page === "supply") ? "dashboard" : page;

  const activeContextStation = useMemo(() => {
    const id =
      screen === "dashboard"
        ? dashStationId
        : screen === "admin"
          ? adminStationId
          : screen === "map" && selection?.kind === "station"
            ? selection.id
            : null;
    if (!id) return null;
    return catalog.stations.find((row) => row.id === id) ?? null;
  }, [screen, dashStationId, adminStationId, selection, catalog.stations]);

  function goHomeDashboard() {
    setDashStationId(isStationSide && stations.length === 1 ? stations[0].id : null);
    setAdminStationId(null);
    setAdminTruckId(null);
    setPage("dashboard");
  }

  if (page === "landing" || !session) {
    return <Landing onEnter={() => setPage("dashboard")} />;
  }

  return (
    <div className="app">
      <Topbar
        session={session}
        admin={admin}
        isOwner={isOwner}
        isStationSide={isStationSide}
        screen={screen}
        stations={stations}
        byCode={byCode}
        mapPointsCount={mapPoints.length}
        trucksCount={catalog.trucks.length}
        networkStats={networkStats}
        theme={theme}
        onToggleTheme={toggle}
        onGoHomeDashboard={goHomeDashboard}
        onSelectPage={setPage}
        onOpenStationPage={openStationPage}
        onOpenStationOnMap={openStationOnMap}
        onOpenAdminStation={openAdminStation}
        onOpenAdminRoot={() => {
          setAdminStationId(null);
          setAdminTruckId(null);
          setPage("admin");
        }}
        onLogout={() => {
          logout();
          setPage("landing");
        }}
      />

      <BreadcrumbBar
        screen={screen}
        isStationSide={isStationSide}
        admin={admin}
        activeContextStation={activeContextStation}
        dashStationId={dashStationId}
        adminStationId={adminStationId}
        mapSelectedId={selection?.id}
        onGoHomeDashboard={goHomeDashboard}
        onClearSectionSelection={() => {
          if (screen === "dashboard") setDashStationId(null);
          if (screen === "admin") {
            setAdminStationId(null);
            setAdminTruckId(null);
          }
        }}
        onOpenStationPage={openStationPage}
        onOpenStationOnMap={openStationOnMap}
        onOpenAdminStation={openAdminStation}
      />

      {screen === "map" ? (
        <MapScreen
          admin={admin}
          stations={stations}
          trucks={catalog.trucks}
          byCode={byCode}
          mapPoints={mapPoints}
          networkStats={networkStats}
          selection={selection}
          mapHudTab={mapHudTab}
          onSetMapHudTab={setMapHudTab}
          onSelect={setSelection}
          onOpenStationPage={openStationPage}
          onOpenAdminStation={admin ? openAdminStation : undefined}
          onOpenAdminTruck={admin ? openAdminTruck : undefined}
        />
      ) : screen === "supply" ? (
        <main className="page dash-page" ref={dashRef}>
          <SupplyPage
            stations={stations}
            trucks={catalog.trucks}
            batches={batches}
            byCode={byCode}
            networkStats={networkStats}
            onOpenTrucksOnMap={() => {
              setMapHudTab("trucks");
              setPage("map");
            }}
            onCreateNewTruck={() => {
              setAdminStationId(null);
              setAdminTruckId("new");
              setPage("admin");
            }}
            onOpenStationPage={openStationPage}
            onOpenStationOnMap={openStationOnMap}
            onOpenAdminStation={openAdminStation}
            onOpenTruckOnMap={openTruckOnMap}
            onOpenAdminTruck={openAdminTruck}
          />
        </main>
      ) : screen === "admin" ? (
        <main className="page dash-page" ref={dashRef}>
          <AdminPage
            initialStationId={adminStationId}
            initialTruckId={adminTruckId}
            onOpenStationDashboard={isStationSide ? undefined : openStationPage}
            onOpenStationMap={isStationSide ? undefined : openStationOnMap}
          />
        </main>
      ) : (
        <main className="page dash-page" ref={dashRef}>
          <Dashboard
            stationId={dashStationId}
            onOpenStation={setDashStationId}
            onOpenAdminStation={admin ? openAdminStation : undefined}
            onOpenMapStation={isStationSide ? undefined : openStationOnMap}
            showOverviewCharts={isOwner}
          />
        </main>
      )}
    </div>
  );
}
