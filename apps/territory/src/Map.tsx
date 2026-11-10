import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
export function TerritoryMap({
  points = [],
  selected,
  onSelect,
  geometry,
}: {
  points?: any[];
  selected?: { lat: number; lng: number };
  onSelect?: (p: { lat: number; lng: number }) => void;
  geometry?: any;
}) {
  const host = useRef<HTMLDivElement>(null),
    map = useRef<L.Map>(null),
    layer = useRef<L.LayerGroup>(null),
    callback = useRef(onSelect);
  callback.current = onSelect;
  useEffect(() => {
    if (!host.current) return;
    const m = L.map(host.current, { zoomControl: false }).setView(
      [4.67, -74.08],
      12,
    );
    map.current = m;
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      referrerPolicy: "strict-origin-when-cross-origin",
      updateWhenIdle: true,
      keepBuffer: 1,
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(m);
    L.control.zoom({ position: "bottomright" }).addTo(m);
    layer.current = L.layerGroup().addTo(m);
    m.on("click", (e) =>
      callback.current?.({ lat: e.latlng.lat, lng: e.latlng.lng }),
    );
    const observer = new ResizeObserver(() => m.invalidateSize());
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      m.remove();
    };
  }, []);
  useEffect(() => {
    const m = map.current,
      l = layer.current;
    if (!m || !l) return;
    l.clearLayers();
    const bounds: L.LatLngExpression[] = [];
    points
      .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lng))
      .forEach((p, i) => {
        const popup = document.createElement("div");
        popup.textContent = p.label || p.name || "Sede";
        L.marker([p.lat, p.lng], {
          icon: L.divIcon({
            className: "map-pin" + (p.kind === "pharmacy" ? " pharmacy" : ""),
            html: `<span>${p.position || i + 1}</span>`,
            iconSize: [30, 30],
            iconAnchor: [15, 30],
          }),
        })
          .bindPopup(popup)
          .addTo(l);
        bounds.push([p.lat, p.lng]);
      });
    if (geometry)
      L.geoJSON(geometry, {
        style: { color: "#17746b", weight: 5, opacity: 0.85 },
      }).addTo(l);
    if (selected) {
      L.circleMarker([selected.lat, selected.lng], {
        radius: 10,
        fillColor: "#c56b26",
        color: "white",
        weight: 3,
        fillOpacity: 1,
      }).addTo(l);
      m.setView([selected.lat, selected.lng], 16);
    } else if (bounds.length)
      m.fitBounds(L.latLngBounds(bounds), { padding: [35, 35], maxZoom: 15 });
  }, [points, selected, geometry]);
  return (
    <div
      className="territory-map"
      ref={host}
      aria-label={
        onSelect
          ? "Mapa: toca para seleccionar una ubicación"
          : "Mapa del territorio y las rutas"
      }
    />
  );
}
