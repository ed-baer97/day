import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { useTheme, type Theme } from "../theme";
import type { MapPoint } from "../types";

/** Free MapLibre styles (no API key) — dark/light ops look */
function styleUrl(theme: Theme): string {
  return theme === "light"
    ? "https://tiles.openfreemap.org/styles/liberty"
    : "https://tiles.openfreemap.org/styles/dark";
}

export default function MapView({
  points,
  selectedId,
  onSelect,
}: {
  points: MapPoint[];
  selectedId?: string | null;
  onSelect?: (point: MapPoint) => void;
}) {
  const { theme } = useTheme();
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const markers = useRef<maplibregl.Marker[]>([]);
  const ready = useRef(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const themeRef = useRef(theme);
  themeRef.current = theme;

  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: styleUrl(themeRef.current),
      center: [37.6, 55.75],
      zoom: 5.2,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.on("load", () => {
      ready.current = true;
    });
    mapRef.current = map;
    return () => {
      markers.current.forEach((m) => m.remove());
      markers.current = [];
      map.remove();
      mapRef.current = null;
      ready.current = false;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      ready.current = false;
      map.setStyle(styleUrl(theme));
      map.once("load", () => {
        ready.current = true;
      });
    };
    if (map.isStyleLoaded()) apply();
    else map.once("load", apply);
  }, [theme]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const placeMarkers = () => {
      markers.current.forEach((m) => m.remove());
      markers.current = [];

      for (const p of points) {
        const el = document.createElement("button");
        el.type = "button";
        el.className = `map-marker ${p.kind}${selectedId === p.id ? " selected" : ""}`;
        el.title = p.name;
        el.addEventListener("click", (e) => {
          e.stopPropagation();
          onSelectRef.current?.(p);
        });

        markers.current.push(
          new maplibregl.Marker({ element: el }).setLngLat([p.lon, p.lat]).addTo(map)
        );

        if (p.kind === "truck") {
          const label = document.createElement("div");
          label.className = "truck-label";
          label.textContent = p.name;
          markers.current.push(
            new maplibregl.Marker({ element: label, offset: [0, 18] })
              .setLngLat([p.lon, p.lat])
              .addTo(map)
          );
        }
      }

      if (points.length > 0) {
        const bounds = new maplibregl.LngLatBounds();
        points.forEach((p) => bounds.extend([p.lon, p.lat]));
        if (!bounds.isEmpty()) {
          map.fitBounds(bounds, { padding: 80, maxZoom: 10, duration: 600 });
        }
      }
    };

    if (map.isStyleLoaded()) placeMarkers();
    else map.once("load", placeMarkers);
  }, [points, selectedId]);

  return <div className="map-wrap" ref={ref} />;
}
