import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
import { parseRoute, routePath, sameRoute, type AppRoute } from "./route";
import { useTheme } from "./theme";
import type { MapPoint } from "./types";

export default function App() {
  const { theme, toggle } = useTheme();
  const { session, logout } = useAuth();
  const admin = isAdmin(session);
  const catalog = useCatalog();
  const { byCode } = usePublicLevels();

  const [route, setRoute] = useState<AppRoute>(() => parseRoute(window.location.pathname));
  const routeRef = useRef(route);
  routeRef.current = route;
  const go = useCallback((patch: Partial<AppRoute>, mode: "push" | "replace" = "push") => {
    const next = { ...routeRef.current, ...patch };
    const path = routePath(next);
    if (sameRoute(next, routeRef.current) && path === window.location.pathname) return;
    if (path !== window.location.pathname) {
      const write = mode === "replace" ? window.history.replaceState : window.history.pushState;
      write.call(window.history, null, "", path);
    }
    routeRef.current = next;
    setRoute(next);
  }, []);
  const page = route.screen;
  const setPage = (screen: AppScreen) => go({ screen });
  const dashStationId = route.dashStationId;
  const setDashStationId = (id: string | null) => go({ dashStationId: id, screen: "dashboard" });
  const adminStationId = route.adminStationId;
  const adminTruckId = route.adminTruckId;
  const selection: MapSelection =
    route.mapKind && route.mapId ? { kind: route.mapKind, id: route.mapId } : null;
  const setSelection = (next: MapSelection) =>
    go({
      screen: "map",
      mapKind: next?.kind ?? null,
      mapId: next?.id ?? null,
    });
  const [mapHudTab, setMapHudTab] = useState<"stations" | "trucks">(
    route.mapKind === "truck" ? "trucks" : "stations"
  );

  useEffect(() => {
    const onPop = () => {
      const next = parseRoute(window.location.pathname);
      routeRef.current = next;
      setRoute(next);
      if (next.mapKind === "truck") setMapHudTab("trucks");
      if (next.mapKind === "station") setMapHudTab("stations");
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
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
    go({ screen: "dashboard", dashStationId: id });
  }

  function openStationOnMap(id: string) {
    setMapHudTab("stations");
    go({ screen: "map", mapKind: "station", mapId: id });
  }

  function openTruckOnMap(id: string) {
    setMapHudTab("trucks");
    go({ screen: "map", mapKind: "truck", mapId: id });
  }

  function openAdminStation(id: string) {
    go({ screen: "admin", adminTab: "stations", adminStationId: id, adminTruckId: null });
  }

  function openAdminTruck(id: string) {
    go({ screen: "admin", adminTab: "trucks", adminTruckId: id, adminStationId: null });
  }

  const isOwner = session?.role === "owner" || session?.role === "station";
  const isStationSide = isOwner;
  const stations = useMemo(
    () => catalog.stations.filter((row) => row.is_active),
    [catalog.stations]
  );

  useEffect(() => {
    if (!session) return;
    if (isStationSide && page !== "landing" && page !== "dashboard") {
      go({ screen: "dashboard" }, "replace");
    } else if (!admin && (page === "admin" || page === "supply")) {
      go({ screen: "dashboard" }, "replace");
    }
  }, [admin, go, isStationSide, page, session]);

  useEffect(() => {
    if (isStationSide && stations.length === 1 && dashStationId !== stations[0].id) {
      go({ dashStationId: stations[0].id }, "replace");
    }
  }, [dashStationId, go, isStationSide, stations]);

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
    go({
      screen: "dashboard",
      dashStationId: isStationSide && stations.length === 1 ? stations[0].id : null,
    });
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
          go({ screen: "admin", adminTab: "stations", adminStationId: null, adminTruckId: null });
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
          if (screen === "dashboard") go({ screen: "dashboard", dashStationId: null });
          if (screen === "admin") {
            go({
              screen: "admin",
              adminTab: route.adminTab,
              adminStationId: null,
              adminTruckId: null,
            });
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
            onCreateNewTruck={() => openAdminTruck("new")}
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
            initialTab={route.adminTab}
            initialStationId={route.adminTab === "stations" ? adminStationId : null}
            initialTruckId={route.adminTab === "trucks" ? adminTruckId : null}
            onOpenStationDashboard={isStationSide ? undefined : openStationPage}
            onOpenStationMap={isStationSide ? undefined : openStationOnMap}
            onTrailChange={(trail) => {
              go(
                {
                  screen: "admin",
                  adminTab: trail.tab,
                  adminStationId: trail.tab === "stations" ? trail.stationId : adminStationId,
                  adminTruckId: trail.tab === "trucks" ? trail.truckId : adminTruckId,
                },
                "replace"
              );
            }}
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
