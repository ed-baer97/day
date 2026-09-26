import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useTheme, type Theme } from "../theme";
import type { MapPoint } from "../types";
import type { RoutePoint } from "../sim/seed";

function styleUrl(theme: Theme): string {
  return theme === "light"
    ? "https://tiles.openfreemap.org/styles/liberty"
    : "https://tiles.openfreemap.org/styles/dark";
}

function ensureRouteLayer(map: maplibregl.Map) {
  if (!map.getSource("sim-route")) {
    map.addSource("sim-route", {
      type: "geojson",
      data: { type: "FeatureCollection", features: [] },
    });
  }
  if (!map.getLayer("sim-route-line")) {
    map.addLayer({
      id: "sim-route-line",
      type: "line",
      source: "sim-route",
      paint: {
        "line-color": "#2ec4b6",
        "line-width": 3,
        "line-opacity": 0.85,
      },
    });
  }
}

export default function MapView({
  points,
  route = [],
  selectedId,
  onSelect,
}: {
  points: MapPoint[];
  route?: RoutePoint[];
  selectedId?: string | null;
  onSelect?: (point: MapPoint) => void;
}) {
  const { theme } = useTheme();
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markers = useRef<Map<string, maplibregl.Marker>>(new Map());
  const labels = useRef<Map<string, maplibregl.Marker>>(new Map());
  const fitted = useRef(false);
  const [ready, setReady] = useState(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const themeRef = useRef(theme);
  themeRef.current = theme;

  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: styleUrl(themeRef.current),
      center: [42.5, 54.8],
      zoom: 5,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      ensureRouteLayer(map);
      setReady(true);
    });
    mapRef.current = map;
    return () => {
      markers.current.forEach((m) => m.remove());
      labels.current.forEach((m) => m.remove());
      markers.current.clear();
      labels.current.clear();
      map.remove();
      mapRef.current = null;
      setReady(false);
      fitted.current = false;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    setReady(false);
    fitted.current = false;
    map.setStyle(styleUrl(theme));
    map.once("load", () => {
      ensureRouteLayer(map);
      setReady(true);
    });
  }, [theme]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    ensureRouteLayer(map);
    const src = map.getSource("sim-route") as GeoJSONSource | undefined;
    if (src) {
      src.setData({
        type: "FeatureCollection",
        features:
          route.length > 1
            ? [
                {
                  type: "Feature",
                  properties: {},
                  geometry: {
                    type: "LineString",
                    coordinates: route.map((p) => [p.lon, p.lat]),
                  },
                },
              ]
            : [],
      });
    }
  }, [route, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    const liveIds = new Set(points.map((p) => p.id));

    for (const [id, marker] of markers.current) {
      if (!liveIds.has(id)) {
        marker.remove();
        markers.current.delete(id);
        labels.current.get(id)?.remove();
        labels.current.delete(id);
      }
    }

    for (const p of points) {
      const isAlert = p.status === "alert" || p.name.startsWith("⚠");
      const cls = `map-marker ${isAlert ? "alert" : p.kind}${selectedId === p.id ? " selected" : ""}`;
      let marker = markers.current.get(p.id);
      if (!marker) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = cls;
        el.title = p.name;
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          onSelectRef.current?.(p);
        });
        marker = new maplibregl.Marker({ element: el }).setLngLat([p.lon, p.lat]).addTo(map);
        markers.current.set(p.id, marker);
        if (p.kind === "truck" && !isAlert) {
          const label = document.createElement("div");
          label.className = "truck-label";
          label.textContent = p.name;
          labels.current.set(
            p.id,
            new maplibregl.Marker({ element: label, offset: [0, 18] })
              .setLngLat([p.lon, p.lat])
              .addTo(map)
          );
        }
      } else {
        marker.setLngLat([p.lon, p.lat]);
        const el = marker.getElement();
        el.className = cls;
        el.title = p.name;
        labels.current.get(p.id)?.setLngLat([p.lon, p.lat]);
      }
    }

    if (!fitted.current && points.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      points.forEach((p) => bounds.extend([p.lon, p.lat]));
      if (!bounds.isEmpty()) {
        map.fitBounds(bounds, { padding: 70, maxZoom: 7.2, duration: 700 });
        fitted.current = true;
      }
    }
  }, [points, selectedId, ready]);

  return <div className="map-wrap" ref={ref} />;
}
