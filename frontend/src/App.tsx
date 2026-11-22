import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { screenFor, sessionCapabilities } from "./access";
import { api, type BatchRecord } from "./api/client";
import { useAuth } from "./auth";
import { useCatalog } from "./catalog";
import AdminPage from "./components/AdminPage";
import CashierPage from "./components/CashierPage";
import Dashboard from "./components/Dashboard";
import Landing from "./components/Landing";
import Topbar, { type NetworkStats } from "./layout/Topbar";
import { isLowFill, usePublicLevels } from "./liveLevels";
import MapScreen, { type MapSelection } from "./pages/MapScreen";
import SupplyPage from "./pages/SupplyPage";
import { emptyRoute, parseRoute, routePath, sameRoute, type AppRoute, type AppScreen } from "./route";
import { useTheme } from "./theme";
import type { MapPoint } from "./types";

export default function App() {
  const { theme, toggle } = useTheme();
  const { session, logout } = useAuth();
  const caps = sessionCapabilities(session);
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
  const screen = screenFor(session, route);
  const setPage = (targetScreen: AppScreen) => go({ screen: targetScreen });
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

  useEffect(() => {
    const canonical = routePath(route);
    if (canonical !== window.location.pathname) {
      window.history.replaceState(null, "", canonical);
    }
  }, [route]);
  const [batches, setBatches] = useState<BatchRecord[]>([]);
  const dashRef = useRef<HTMLElement>(null);

  useEffect(() => {
    dashRef.current?.scrollTo(0, 0);
  }, [dashStationId, screen, adminStationId, adminTruckId]);

  const reloadBatches = useCallback(async () => {
    if (!caps.admin) return;
    try {
      const rows = await api.batches();
      setBatches(rows);
    } catch {
      /* игнорируем при фоновом обновлении */
    }
  }, [caps.admin]);

  useEffect(() => {
    if (!caps.admin || screen !== "supply") return;
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
  }, [caps.admin, screen]);

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

  const stations = useMemo(
    () => (caps.stationSide ? catalog.stations : catalog.stations.filter((row) => row.is_active)),
    [catalog.stations, caps.stationSide]
  );

  useEffect(() => {
    if (!session || !caps.knownRole) return;
    if (screen !== route.screen) {
      go(emptyRoute(screen), "replace");
    }
  }, [caps.knownRole, go, route.screen, screen, session]);

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

  function goHomeDashboard() {
    go(emptyRoute(caps.homeScreen));
  }

  if (screen === "landing" || !session) {
    return (
      <Landing
        onEnter={(nextSession) => {
          const target = sessionCapabilities(nextSession ?? session);
          if (target.knownRole) go(emptyRoute(target.homeScreen));
        }}
      />
    );
  }

  const canOpenMap = screenFor(session, "map") === "map";

  return (
    <div className="app">
      <Topbar
        session={session}
        screen={screen}
        stations={stations}
        allStations={catalog.stations}
        byCode={byCode}
        theme={theme}
        onToggleTheme={toggle}
        onGoHomeDashboard={goHomeDashboard}
        onSelectPage={setPage}
        onOpenStationPage={openStationPage}
        onOpenAdminStation={caps.admin ? openAdminStation : undefined}
        onOpenAdminRoot={() => {
          go({ screen: "admin", adminTab: "stations", adminStationId: null, adminTruckId: null });
        }}
        onLogout={() => {
          logout();
          go(emptyRoute("landing"));
        }}
      />

      {screen === "cashier" ? (
        <CashierPage />
      ) : screen === "map" ? (
        <MapScreen
          admin={caps.admin}
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
          onOpenAdminStation={caps.admin ? openAdminStation : undefined}
          onOpenAdminTruck={caps.admin ? openAdminTruck : undefined}
        />
      ) : screen === "supply" ? (
        <main className="page dash-page" ref={dashRef}>
          <SupplyPage
            stations={stations}
            trucks={catalog.trucks}
            batches={batches}
            byCode={byCode}
            networkStats={networkStats}
            onBatchesChange={setBatches}
            onReloadBatches={reloadBatches}
            onOpenTrucksOnMap={() => {
              setMapHudTab("trucks");
              setPage("map");
            }}
            onCreateNewTruck={() => openAdminTruck("new")}
            onOpenStationPage={openStationPage}
            onOpenAdminStation={openAdminStation}
            onOpenTruckOnMap={openTruckOnMap}
            onOpenAdminTruck={openAdminTruck}
          />
        </main>
      ) : screen === "admin" ? (
        <main className="page dash-page" ref={dashRef}>
          <AdminPage
            tab={route.adminTab}
            stationId={route.adminTab === "stations" ? adminStationId : null}
            truckId={route.adminTab === "trucks" ? adminTruckId : null}
            onSelectTab={(nextTab) =>
              go(
                {
                  screen: "admin",
                  adminTab: nextTab,
                  adminStationId: null,
                  adminTruckId: null,
                },
                "push"
              )
            }
            onSelectStationId={(id) =>
              go(
                {
                  screen: "admin",
                  adminTab: "stations",
                  adminStationId: id,
                  adminTruckId: null,
                },
                "push"
              )
            }
            onSelectTruckId={(id) =>
              go(
                {
                  screen: "admin",
                  adminTab: "trucks",
                  adminStationId: null,
                  adminTruckId: id,
                },
                "push"
              )
            }
            onOpenStationDashboard={caps.admin ? openStationPage : undefined}
            onOpenStationMap={canOpenMap ? openStationOnMap : undefined}
            onOpenTruckMap={canOpenMap ? openTruckOnMap : undefined}
          />
        </main>
      ) : (
        <main className="page dash-page" ref={dashRef}>
          <Dashboard
            stationId={dashStationId}
            onOpenStation={setDashStationId}
            onOpenAdminStation={caps.admin ? openAdminStation : undefined}
            onOpenMapStation={canOpenMap ? openStationOnMap : undefined}
            onOpenAdminReconcile={
              caps.admin
                ? () =>
                    go(
                      {
                        screen: "admin",
                        adminTab: "reconcile",
                        adminStationId: null,
                        adminTruckId: null,
                      },
                      "push"
                    )
                : undefined
            }
          />
        </main>
      )}
    </div>
  );
}
