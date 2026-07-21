import { useState, useEffect, useMemo, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Polyline, ZoomControl, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { isUrgent, within3, pcNorm } from '../lib/orders.js';
import { geocode, geoCache, routeBetween, DEPOTS } from '../lib/geo.js';
import OrdersPanel from '../components/OrdersPanel.jsx';

// UK-centred default view, used before we have anything to fit bounds to.
const UK_CENTER = [54.3, -2.6];
const UK_ZOOM = 6;

function divIcon(className, size) {
  return L.divIcon({ className: 'pin-icon', html: `<span class="${className}"></span>`, iconSize: [size, size], iconAnchor: [size / 2, size / 2] });
}
const depotIcon = divIcon('pin-depot', 16);
const haulierIcon = divIcon('pin-haulier', 14);
function orderIcon(urgent, selected) {
  return divIcon('pin-order' + (urgent ? ' urgent' : '') + (selected ? ' selected' : ''), selected ? 22 : 16);
}

// Fits the map to whatever pins are currently visible, once, whenever the
// set of points changes size (avoids fighting the user's own pan/zoom).
function FitBounds({ points }) {
  const map = useMap();
  const count = points.length;
  useEffect(() => {
    if (!count) return;
    if (count === 1) { map.setView(points[0], 11); return; }
    map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 12 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count]);
  return null;
}

export default function MapPage({ records, hauliers, onSelect, selectedId }) {
  const [tick, setTick] = useState(0);
  const [layers, setLayers] = useState({ orders: true, depots: true, hauliers: true, routes: true });
  const [routes, setRoutes] = useState({});
  const fetching = useRef(new Set());

  // Geocode every postcode we might pin (deliveries, collections, hauliers).
  const pcSig = records.map((r) => r.postcode).join(',') + '|' + (hauliers || []).map((h) => h.pc).join(',');
  useEffect(() => {
    let live = true;
    const pcs = []
      .concat(records.map((r) => r.postcode), records.map((r) => r.collection_pc))
      .concat((hauliers || []).map((h) => h.pc))
      .filter(Boolean);
    geocode(pcs).then(() => { if (live) setTick((n) => n + 1); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pcSig]);

  const geo = geoCache();

  const depotPts = DEPOTS;
  const haulierPts = useMemo(() => (hauliers || []).map((h) => {
    const g = geo[pcNorm(h.pc || '')];
    return g ? { h, pos: [g.la, g.lo] } : null;
  }).filter(Boolean), [tick, hauliers]); // eslint-disable-line react-hooks/exhaustive-deps

  const orderPts = useMemo(() => records.map((r) => {
    const g = geo[pcNorm(r.postcode || '')];
    return g ? { r, pos: [g.la, g.lo] } : null;
  }).filter(Boolean), [tick, records]); // eslint-disable-line react-hooks/exhaustive-deps

  const legPairs = useMemo(() => records.map((r) => {
    const dg = geo[pcNorm(r.postcode || '')];
    const cg = geo[pcNorm(r.collection_pc || '')];
    if (!dg || !cg) return null;
    return { r, from: { la: cg.la, lo: cg.lo }, to: { la: dg.la, lo: dg.lo } };
  }).filter(Boolean), [tick, records]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch road-based route geometry from OSRM for each collection->delivery
  // leg, one at a time, caching results so re-renders don't refetch.
  useEffect(() => {
    let live = true;
    (async () => {
      for (const { r, from, to } of legPairs) {
        const key = r.id;
        if (routes[key] || fetching.current.has(key)) continue;
        fetching.current.add(key);
        const line = await routeBetween(from, to);
        fetching.current.delete(key);
        if (!live) return;
        if (line) setRoutes((rt) => ({ ...rt, [key]: line }));
      }
    })();
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [legPairs]);

  const pinnedCount = orderPts.length;
  const allPoints = useMemo(() => {
    const pts = orderPts.map((o) => o.pos);
    if (layers.depots) pts.push(...depotPts.map((d) => [d.lat, d.lng]));
    if (layers.hauliers) pts.push(...haulierPts.map((h) => h.pos));
    return pts.length ? pts : depotPts.map((d) => [d.lat, d.lng]);
  }, [orderPts, haulierPts, layers.depots, layers.hauliers]);

  const toggle = (k) => setLayers((l) => ({ ...l, [k]: !l[k] }));

  return (
    <div className="mapwrap page-anim">
      {pinnedCount === 0 && records.length > 0 && (
        <div className="maploading">Geocoding {records.length} orders…</div>
      )}
      <MapContainer center={UK_CENTER} zoom={UK_ZOOM} zoomControl={false} className="leafletmap">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />
        <ZoomControl position="bottomleft" />
        <FitBounds points={allPoints} />

        {layers.routes && legPairs.map(({ r }) => {
          const line = routes[r.id];
          if (!line) return null;
          return (
            <Polyline key={'r' + r.id} positions={line}
              pathOptions={{ color: isUrgent(r) ? '#D40511' : '#75746d', weight: isUrgent(r) ? 3.5 : 2.5, opacity: isUrgent(r) ? 0.85 : 0.55, dashArray: isUrgent(r) ? '6 6' : null }} />
          );
        })}

        {layers.depots && depotPts.map((d) => (
          <Marker key={d.key} position={[d.lat, d.lng]} icon={depotIcon}
            eventHandlers={{}} title={d.name + ' — ' + d.town} />
        ))}

        {layers.hauliers && haulierPts.map(({ h, pos }) => (
          <Marker key={h.name} position={pos} icon={haulierIcon} title={h.name} />
        ))}

        {layers.orders && orderPts.map(({ r, pos }) => (
          <Marker key={r.id} position={pos} icon={orderIcon(isUrgent(r), selectedId === r.id)}
            eventHandlers={{ click: () => onSelect(r) }} title={(r.worksite || r.site || '') + ' — ' + (r.orders || []).join(' / ')} />
        ))}
      </MapContainer>

      <div className="layertoggle">
        <div className="lt">Layers</div>
        {[['orders', 'Delivery stops'], ['depots', 'Collection depots'], ['hauliers', 'Haulier bases'], ['routes', 'Routes']].map(([k, label]) => (
          <label key={k} className="lyrow">
            <input type="checkbox" checked={layers[k]} onChange={() => toggle(k)} />
            {label}
          </label>
        ))}
      </div>

      <div className="legend">
        <div className="lt">Region 2 network</div>
        <div className="legrow"><span className="ld" style={{ background: 'var(--red)' }} />Tracked delivery</div>
        <div className="legrow"><span className="ld" style={{ background: 'var(--red)', boxShadow: '0 0 0 3px var(--red-t)' }} />Urgent · ≤3 days</div>
        <div className="legrow"><span className="ld sq" style={{ background: 'var(--depot)' }} />Collection depot</div>
        <div className="legrow"><span className="ld" style={{ background: 'var(--yellow)', border: '1.5px solid #8a6d00' }} />Haulier base</div>
      </div>

      <OrdersPanel records={records} hauliers={hauliers} onSelect={onSelect} selectedId={selectedId} />
    </div>
  );
}
