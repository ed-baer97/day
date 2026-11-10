import type { AppScreen } from "./layout/Topbar";

export type AdminRouteTab = "stations" | "trucks" | "supplies" | "reconcile" | "security";

export type AppRoute = {
  screen: AppScreen;
  dashStationId: string | null;
  adminTab: AdminRouteTab;
  adminStationId: string | null;
  adminTruckId: string | null;
  mapKind: "station" | "truck" | null;
  mapId: string | null;
};

const ADMIN_TABS = new Set<AdminRouteTab>(["stations", "trucks", "supplies", "reconcile", "security"]);

export function emptyRoute(screen: AppScreen = "landing"): AppRoute {
  return {
    screen,
    dashStationId: null,
    adminTab: "stations",
    adminStationId: null,
    adminTruckId: null,
    mapKind: null,
    mapId: null,
  };
}

export function parseRoute(pathname: string): AppRoute {
  const parts = pathname.split("/").filter(Boolean);
  const route = emptyRoute("dashboard");
  const head = parts[0] ?? "";
  if (head === "" || head === "landing") return emptyRoute("landing");
  if (head === "dashboard") {
    route.screen = "dashboard";
    route.dashStationId = parts[1] ?? null;
    return route;
  }
  if (head === "map") {
    route.screen = "map";
    if (parts[1] === "station" || parts[1] === "truck") {
      route.mapKind = parts[1];
      route.mapId = parts[2] ?? null;
      if (!route.mapId) route.mapKind = null;
    }
    return route;
  }
  if (head === "supply") {
    route.screen = "supply";
    return route;
  }
  if (head === "admin") {
    route.screen = "admin";
    const tab = parts[1];
    if (tab && ADMIN_TABS.has(tab as AdminRouteTab)) route.adminTab = tab as AdminRouteTab;
    if (route.adminTab === "stations") route.adminStationId = parts[2] ?? null;
    if (route.adminTab === "trucks") route.adminTruckId = parts[2] ?? null;
    return route;
  }
  return emptyRoute("landing");
}

export function routePath(route: AppRoute): string {
  if (route.screen === "landing") return "/";
  if (route.screen === "dashboard") {
    return route.dashStationId ? `/dashboard/${route.dashStationId}` : "/dashboard";
  }
  if (route.screen === "map") {
    if (route.mapKind && route.mapId) return `/map/${route.mapKind}/${route.mapId}`;
    return "/map";
  }
  if (route.screen === "supply") return "/supply";
  if (route.screen === "admin") {
    if (route.adminTab === "stations" && route.adminStationId) {
      return `/admin/stations/${route.adminStationId}`;
    }
    if (route.adminTab === "trucks" && route.adminTruckId) {
      return `/admin/trucks/${route.adminTruckId}`;
    }
    return `/admin/${route.adminTab}`;
  }
  return "/";
}

export function sameRoute(a: AppRoute, b: AppRoute): boolean {
  return routePath(a) === routePath(b);
}
