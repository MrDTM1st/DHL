import { useState, useEffect, useMemo, useRef } from 'react';
import { MapContainer, TileLayer, Marker, Polyline, ZoomControl, AttributionControl, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { isUrgent, within3, pcNorm, recommendFor } from '../lib/orders.js';
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
const collectIcon = divIcon('pin-collect', 18);
const recIcon = divIcon('pin-haulier rec', 18);
function orderIcon(urgent, selected) {
  return divIcon('pin-order' + (urgent ? ' urgent' : '') + (selected ? ' selected' : ''), selected ? 22 : 16);
}

// Frames the map on the pins ONCE, when they first appear - and then never
// again on its own.
//
// This used to re-fit whenever the NUMBER of plotted points changed, which
// sounds harmless but isn't: the count changes as postcodes geocode in one by
// one, every time the tracker re-polls, and whenever a layer is toggled. So
// the map kept yanking itself back to a fresh bounding box under the user -
// pan somewhere, zoom out, and a moment later it snapped elsewhere, which
// reads exactly like "the pins won't stay put". Re-framing is now only ever
// deliberate: this initial fit, the Fit-all button, or selecting an order.
function FitBounds({ points, fitToken }) {
  const map = useMap();
  const done = useRef(false);
  const count = points.length;
  useEffect(() => {
    if (!count) return;
    if (done.current && !fitToken) return;   // already framed; leave the view alone
    done.current = true;
    if (count === 1) { map.setView(points[0], 11); return; }
    map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 12 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [count > 0, fitToken]);
  return null;
}

// When an order is selected, glide to ITS run so the blue route fills the
// view - the Google-Maps move of flying to the thing you just tapped.
//
// Keyed on the ORDER, not on the route geometry. Keying on the geometry meant
// flying twice for one click: once to the straight-line placeholder, then
// again when the road route arrived from OSRM a second later - a second,
// unasked-for lurch that looked like the map wandering off on its own.
function FlyToRoute({ id, line, from, to }) {
  const map = useMap();
  useEffect(() => {
    const pts = line && line.length ? line : (from && to ? [[from.la, from.lo], [to.la, to.lo]] : null);
    if (!pts) return;
    map.flyToBounds(L.latLngBounds(pts), { padding: [70, 70], maxZoom: 11, duration: 0.9 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);
  return null;
}

export default function MapPage({ records, hauliers, onSelect, selectedId, pickedHaulier }) {
  const [tick, setTick] = useState(0);
  const [layers, setLayers] = useState({ orders: true, depots: true, hauliers: true, routes: true });
  const [routes, setRoutes] = useState({});
  const [fitToken, setFitToken] = useState(0);   // bumped only by the Fit-all button
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
        const info = await routeBetween(from, to);
        fetching.current.delete(key);
        if (!live) return;
        if (info) setRoutes((rt) => ({ ...rt, [key]: info }));
      }
    })();
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [legPairs]);

  // the run for the order you pressed View on, plus the hauliers we'd ring for
  // it - so the map answers "where is this, and who can do it" in one look
  const selectedLeg = useMemo(
    () => legPairs.find((l) => l.r.id === selectedId) || null,
    [legPairs, selectedId]);
  const selectedLine = selectedLeg && routes[selectedLeg.r.id] ? routes[selectedLeg.r.id].line : null;
  const selectedRec = useMemo(() => {
    const rec = records.find((r) => r.id === selectedId);
    if (!rec) return [];
    return recommendFor(rec, hauliers, geo).list.slice(0, 3);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, records, hauliers, tick]);
  const recNames = useMemo(() => new Set(selectedRec.map((h) => h.name)), [selectedRec]);

  // the picked haulier's run to the collection - drawn so the whole journey
  // (base -> collection -> delivery) is visible, not just the delivery leg
  const [repoLine, setRepoLine] = useState(null);
  useEffect(() => {
    let live = true;
    setRepoLine(null);
    const cg = selectedLeg ? selectedLeg.from : null;
    const hg = pickedHaulier ? geo[pcNorm(pickedHaulier.pc || '')] : null;
    if (cg && hg) routeBetween(hg, cg).then((x) => { if (live && x) setRepoLine(x.line); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedHaulier && pickedHaulier.name, selectedLeg && selectedLeg.r.id, tick]);

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
      <MapContainer center={UK_CENTER} zoom={UK_ZOOM} zoomControl={false} attributionControl={false} className="leafletmap">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />
        {/* Both controls in the bottom-left corner, so the required OSM
            attribution never collides with the legend panel (bottom-right). */}
        <AttributionControl position="bottomleft" prefix={false} />
        <ZoomControl position="bottomleft" />
        <FitBounds points={allPoints} fitToken={fitToken} />

        {/* every other run, kept quiet so the selected one reads clearly */}
        {layers.routes && legPairs.filter(({ r }) => r.id !== selectedId).map(({ r }) => {
          const line = routes[r.id] && routes[r.id].line;
          if (!line) return null;
          return (
            <Polyline key={'r' + r.id} positions={line}
              pathOptions={{ color: isUrgent(r) ? '#D40511' : '#9b9a92',
                weight: isUrgent(r) ? 3 : 2, opacity: selectedId ? 0.18 : (isUrgent(r) ? 0.8 : 0.5),
                dashArray: isUrgent(r) ? '6 6' : null }} />
          );
        })}

        {/* the SELECTED run: a soft blue casing, the blue route on top, and a
            dashed overlay whose stroke animates along the line so the
            direction of travel is obvious at a glance */}
        {selectedLeg && selectedLine && (
          <>
            <Polyline positions={selectedLine} interactive={false}
              pathOptions={{ color: '#1a73e8', weight: 11, opacity: 0.18, lineCap: 'round' }} />
            <Polyline positions={selectedLine} interactive={false}
              pathOptions={{ color: '#1a73e8', weight: 5, opacity: 0.95, lineCap: 'round' }} />
            <Polyline positions={selectedLine} interactive={false} className="routeflow"
              pathOptions={{ color: '#ffffff', weight: 3, opacity: 0.9, dashArray: '10 18', lineCap: 'butt' }} />
          </>
        )}

        {/* straight hop while the road geometry is still being fetched, so the
            selection never looks like nothing happened */}
        {selectedLeg && !selectedLine && (
          <Polyline positions={[[selectedLeg.from.la, selectedLeg.from.lo], [selectedLeg.to.la, selectedLeg.to.lo]]}
            interactive={false} className="routeflow"
            pathOptions={{ color: '#1a73e8', weight: 4, opacity: 0.7, dashArray: '8 12' }} />
        )}

        {/* the picked haulier running empty to the collection - dashed green so
            it reads as the approach, not the load-carrying leg */}
        {repoLine && (
          <Polyline positions={repoLine} interactive={false}
            pathOptions={{ color: '#1da35e', weight: 3.5, opacity: 0.85, dashArray: '3 9', lineCap: 'round' }} />
        )}

        {selectedLeg && (
          <>
            <Marker position={[selectedLeg.from.la, selectedLeg.from.lo]} icon={collectIcon}
              title={'Collection — ' + (selectedLeg.r.collection_site || '')} />
            <FlyToRoute id={selectedLeg.r.id} line={selectedLine}
              from={selectedLeg.from} to={selectedLeg.to} />
          </>
        )}

        {layers.depots && depotPts.map((d) => (
          <Marker key={d.key} position={[d.lat, d.lng]} icon={depotIcon}
            eventHandlers={{}} title={d.name + ' — ' + d.town} />
        ))}

        {layers.hauliers && haulierPts.map(({ h, pos }) => (
          <Marker key={h.name} position={pos}
            icon={recNames.has(h.name) ? recIcon : haulierIcon}
            zIndexOffset={recNames.has(h.name) ? 400 : 0}
            title={recNames.has(h.name) ? h.name + ' — recommended for this job' : h.name} />
        ))}

        {layers.orders && orderPts.map(({ r, pos }) => (
          <Marker key={r.id} position={pos} icon={orderIcon(isUrgent(r), selectedId === r.id)}
            eventHandlers={{ click: () => onSelect(r) }} title={(r.worksite || r.site || '') + ' — ' + (r.orders || []).join(' / ')} />
        ))}
      </MapContainer>

      <div className="layertoggle">
        <div className="lt">Layers</div>
        <button className="fitbtn" onClick={() => setFitToken((n) => n + 1)}
          title="Re-frame the map around everything">Fit all</button>
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
        {selectedLeg && (
          <>
            <div className="legrow"><span className="ld" style={{ background: '#1a73e8' }} />Selected run</div>
            <div className="legrow"><span className="ld" style={{ background: 'var(--go, #1da35e)' }} />Recommended haulier</div>
            {repoLine && <div className="legrow"><span className="ld" style={{ background: 'var(--go, #1da35e)', opacity: .55 }} />Haulier → collection</div>}
          </>
        )}
      </div>

      <OrdersPanel records={records} hauliers={hauliers} onSelect={onSelect} selectedId={selectedId} />
    </div>
  );
}
