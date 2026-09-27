import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useTheme, type Theme } from "../theme";
import type { MapPoint } from "../types";
import type { MapRouteLayer } from "../sim/engine";
import type { Coord } from "../sim/geo";

/** OSM HOT — тот же граф дорог, что у OSRM. */
function mapStyle(_theme: Theme): maplibregl.StyleSpecification {
  return {
    version: 8,
    sources: {
      osm: {
        type: "raster",
        tiles: [
          "https://a.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
          "https://b.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png",
        ],
        tileSize: 256,
        attribution: "© OpenStreetMap, HOT",
        maxzoom: 19,
      },
    },
    layers: [{ id: "osm", type: "raster", source: "osm" }],
  };
}

function ensureRouteLayers(map: maplibregl.Map) {
  if (!map.getSource("sim-routes")) {
    map.addSource("sim-routes", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
      tolerance: 0,
    });
  }
  if (!map.getLayer("sim-route-case")) {
    map.addLayer({
      id: "sim-route-case",
      type: "line",
      source: "sim-routes",
      filter: ["==", ["get", "kind"], "planned"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#1a5c56", "line-width": 5, "line-opacity": 0.35 },
    });
  }
  if (!map.getLayer("sim-route-planned")) {
    map.addLayer({
      id: "sim-route-planned",
      type: "line",
      source: "sim-routes",
      filter: ["==", ["get", "kind"], "planned"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#2ec4b6", "line-width": 2.5, "line-opacity": 0.75 },
    });
  }
  if (!map.getLayer("sim-route-traveled")) {
    map.addLayer({
      id: "sim-route-traveled",
      type: "line",
      source: "sim-routes",
      filter: ["==", ["get", "kind"], "traveled"],
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": "#149e92", "line-width": 3, "line-opacity": 1 },
    });
  }
}

function routesToGeoJSON(routes: MapRouteLayer[]) {
  const features: Array<{
    type: "Feature";
    properties: { kind: string; id: string };
    geometry: { type: "LineString"; coordinates: Coord[] };
  }> = [];
  for (const r of routes) {
    if (r.planned.length > 1) {
      features.push({
        type: "Feature",
        properties: { kind: "planned", id: r.id },
        geometry: { type: "LineString", coordinates: r.planned },
      });
    }
    if (r.traveled.length > 1) {
      features.push({
        type: "Feature",
        properties: { kind: "traveled", id: r.id },
        geometry: { type: "LineString", coordinates: r.traveled },
      });
    }
  }
  return { type: "FeatureCollection" as const, features };
}

function makeTruckEl(plate: string, selected: boolean): HTMLButtonElement {
  // Корень = MapLibre Marker (position:absolute). Внутри — relative-бокс 14×14.
  const wrap = document.createElement("button");
  wrap.type = "button";
  wrap.className = `truck-wrap${selected ? " selected" : ""}`;
  wrap.title = plate;
  wrap.setAttribute("aria-label", plate);

  const inner = document.createElement("span");
  inner.className = "truck-inner";

  const mark = document.createElement("span");
  mark.className = `map-marker truck${selected ? " selected" : ""}`;

  const label = document.createElement("span");
  label.className = "truck-label";
  label.textContent = plate;

  inner.append(mark, label);
  wrap.append(inner);
  return wrap;
}

export default function MapView({
  points,
  routes = [],
  selectedId,
  onSelect,
}: {
  points: MapPoint[];
  routes?: MapRouteLayer[];
  selectedId?: string | null;
  onSelect?: (point: MapPoint) => void;
}) {
  const { theme } = useTheme();
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markers = useRef<Map<string, maplibregl.Marker>>(new Map());
  const fittedRouteKey = useRef("");
  const [ready, setReady] = useState(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const themeRef = useRef(theme);
  themeRef.current = theme;
  const pointsRef = useRef(points);
  pointsRef.current = points;
  const lastCenteredId = useRef<string | null | undefined>(undefined);

  function centerOn(lon: number, lat: number, id: string) {
    const map = mapRef.current;
    if (!map) return;
    lastCenteredId.current = id;
    map.easeTo({ center: [lon, lat], duration: 500, essential: true });
  }

  function centerOnPointId(id: string) {
    const cur = pointsRef.current.find((p) => p.id === id);
    if (cur) centerOn(cur.lon, cur.lat, id);
  }

  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: mapStyle(themeRef.current),
      center: [52.35, 43.55],
      zoom: 9,
      minZoom: 5,
      maxZoom: 17,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      ensureRouteLayers(map);
      setReady(true);
    });
    mapRef.current = map;
    return () => {
      markers.current.forEach((m) => m.remove());
      markers.current.clear();
      map.remove();
      mapRef.current = null;
      setReady(false);
      fittedRouteKey.current = "";
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    setReady(false);
    fittedRouteKey.current = "";
    map.setStyle(mapStyle(theme));
    map.once("load", () => {
      ensureRouteLayers(map);
      setReady(true);
    });
  }, [theme]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    ensureRouteLayers(map);
    const src = map.getSource("sim-routes") as GeoJSONSource | undefined;
    if (src) src.setData(routesToGeoJSON(routes));

    const key = routes.map((r) => `${r.id}:${r.planned.length}`).join("|");
    if (key && key !== fittedRouteKey.current) {
      const bounds = new maplibregl.LngLatBounds();
      for (const r of routes) {
        for (const p of r.planned) bounds.extend(p as [number, number]);
      }
      if (!bounds.isEmpty()) {
        map.fitBounds(bounds, { padding: 60, maxZoom: 11, duration: 700 });
        fittedRouteKey.current = key;
      }
    }
  }, [routes, ready]);

  // Список / смена карточки — центр по selectedId (без слежения за движением)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !selectedId) return;
    if (lastCenteredId.current === undefined) {
      lastCenteredId.current = selectedId;
      return;
    }
    if (selectedId === lastCenteredId.current) return;
    const target = points.find((p) => p.id === selectedId);
    if (!target) return;
    centerOn(target.lon, target.lat, selectedId);
  }, [selectedId, points, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    const liveIds = new Set(points.map((p) => p.id));
    for (const [id, marker] of markers.current) {
      if (!liveIds.has(id)) {
        marker.remove();
        markers.current.delete(id);
      }
    }

    for (const p of points) {
      const isAlert = p.status === "alert" || p.name.startsWith("⚠");
      const selected = selectedId === p.id;
      let marker = markers.current.get(p.id);
      const wantTruckWrap = p.kind === "truck" && !isAlert;

      // После HMR старый button.map-marker без детей ломает якорь — пересоздаём
      if (marker && wantTruckWrap) {
        const el = marker.getElement();
        if (
          !el.classList.contains("maplibregl-marker") ||
          !el.classList.contains("truck-wrap") ||
          !el.querySelector(".truck-inner > .map-marker.truck")
        ) {
          marker.remove();
          markers.current.delete(p.id);
          marker = undefined;
        }
      }

      if (!marker) {
        if (wantTruckWrap) {
          const el = makeTruckEl(p.name, selected);
          el.addEventListener("click", (e) => {
            e.stopPropagation();
            centerOnPointId(p.id);
            onSelectRef.current?.(p);
          });
          // якорь по 14×14 точке; номер absolute — не входит в размер Marker
          marker = new maplibregl.Marker({ element: el, anchor: "center" })
            .setLngLat([p.lon, p.lat])
            .addTo(map);
        } else {
          const el = document.createElement("button");
          el.type = "button";
          el.className = `map-marker ${isAlert ? "alert" : p.kind}${selected ? " selected" : ""}`;
          el.title = p.name;
          el.addEventListener("click", (e) => {
            e.stopPropagation();
            centerOnPointId(p.id);
            onSelectRef.current?.(p);
          });
          marker = new maplibregl.Marker({ element: el, anchor: "center" })
            .setLngLat([p.lon, p.lat])
            .addTo(map);
        }
        markers.current.set(p.id, marker);
      } else {
        marker.setLngLat([p.lon, p.lat]);
        const el = marker.getElement();
        if (wantTruckWrap) {
          el.className = `maplibregl-marker truck-wrap${selected ? " selected" : ""}`;
          const mark = el.querySelector(".map-marker");
          if (mark) mark.className = `map-marker truck${selected ? " selected" : ""}`;
          const lab = el.querySelector(".truck-label");
          if (lab) lab.textContent = p.name;
        } else {
          el.className = `maplibregl-marker map-marker ${isAlert ? "alert" : p.kind}${selected ? " selected" : ""}`;
          el.title = p.name;
        }
      }
    }
  }, [points, selectedId, ready]);

  return <div className="map-wrap" ref={ref} />;
}
