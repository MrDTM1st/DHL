import { useState, useEffect, useMemo } from 'react';
import { isUrgent, within3, pcNorm } from '../lib/orders.js';
import { loadGeom, geocode, geoCache, DEPOTS, VW, VH } from '../lib/geo.js';
import OrdersPanel from '../components/OrdersPanel.jsx';

// A single delivery pin: an outer <g> positions it (SVG transform attribute),
// an inner <g> animates the drop-in (CSS transform) — nesting them avoids the
// CSS/SVG transform conflict that would otherwise collapse every pin to origin.
function MapPin({ x, y, urgent, revealed, delay, selected, label, onClick }) {
  return (
    <g transform={`translate(${x},${y})`} style={{ cursor: 'pointer' }} onClick={onClick}>
      <g className={'pin ' + (revealed ? 'in' : 'pre')} style={{ transitionDelay: delay + 'ms' }}>
        {urgent && <circle className="pulsering" r="11" fill="var(--red)" />}
        <circle r={selected ? 11 : 8} fill="var(--red)" stroke="#fff" strokeWidth="2.6" />
        <circle className="pinhit" r="12" fill="transparent" />
        {selected && <text className="pinlabel" y="-16" textAnchor="middle">{label}</text>}
      </g>
    </g>
  );
}

export default function MapPage({ records, hauliers, onSelect, selectedId }) {
  const [geom, setGeom] = useState(null);
  const [revealed, setRevealed] = useState(false);
  const [tick, setTick] = useState(0);

  // Load the UK outline once.
  useEffect(() => { let live = true; loadGeom().then((g) => { if (live) setGeom(g); }); return () => { live = false; }; }, []);

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

  // Staggered reveal whenever the map (re)loads.
  useEffect(() => {
    if (!geom) return;
    setRevealed(false);
    const t = setTimeout(() => setRevealed(true), 90);
    return () => clearTimeout(t);
  }, [geom]);

  const geo = geoCache();
  const proj = (lng, lat) => geom.project(lng, lat);

  const depotPts = useMemo(() => geom ? DEPOTS.map((d) => ({ d, p: proj(d.lng, d.lat) })) : [], [geom]);
  const haulierPts = useMemo(() => {
    if (!geom) return [];
    return (hauliers || []).map((h) => {
      const g = geo[pcNorm(h.pc || '')];
      return g ? { h, p: proj(g.lo, g.la) } : null;
    }).filter(Boolean);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geom, tick, hauliers]);

  const orderPts = useMemo(() => {
    if (!geom) return [];
    return records.map((r) => {
      const g = geo[pcNorm(r.postcode || '')];
      if (!g) return null;
      return { r, p: proj(g.lo, g.la) };
    }).filter(Boolean);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geom, tick, records]);

  // Routes collection -> delivery, drawn with a slight curve.
  const routes = useMemo(() => {
    if (!geom) return [];
    return records.map((r) => {
      const dg = geo[pcNorm(r.postcode || '')];
      const cg = geo[pcNorm(r.collection_pc || '')];
      if (!dg || !cg) return null;
      const a = proj(cg.lo, cg.la), b = proj(dg.lo, dg.la);
      const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
      const dx = b[0] - a[0], dy = b[1] - a[1];
      const cx = mx - dy * 0.16, cy = my + dx * 0.16;
      return { r, d: `M${a[0]},${a[1]} Q${cx},${cy} ${b[0]},${b[1]}` };
    }).filter(Boolean);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geom, tick, records]);

  const pinnedCount = orderPts.length;

  return (
    <div className="mapwrap page-anim">
      {!geom && <div className="maploading">Loading UK map…</div>}
      {geom && pinnedCount === 0 && records.length > 0 && (
        <div className="maploading">Geocoding {records.length} orders…</div>
      )}
      <svg className="mapsvg" viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="xMidYMid meet">
        {geom && geom.land && <path className="land" d={geom.land} />}
        {routes.map(({ r, d }, i) => (
          <path key={'r' + r.id} d={d}
            className={'route route-draw' + (isUrgent(r) ? ' urgent' : '') + (revealed ? ' on' : '') + (isUrgent(r) && revealed ? ' flow' : '')}
            pathLength="1" style={{ transitionDelay: (300 + i * 70) + 'ms' }} />
        ))}
        {depotPts.map(({ d, p }) => (
          <g key={d.key} transform={`translate(${p[0]},${p[1]})`}>
            <g className={'pin ' + (revealed ? 'in' : 'pre')}>
              <rect x="-7" y="-7" width="14" height="14" rx="3" transform="rotate(45)" fill="var(--depot)" stroke="#fff" strokeWidth="2.2" />
            </g>
          </g>
        ))}
        {haulierPts.map(({ h, p }) => (
          <g key={h.name} transform={`translate(${p[0]},${p[1]})`}>
            <g className={'pin ' + (revealed ? 'in' : 'pre')} style={{ transitionDelay: '120ms' }}>
              <circle r="6.5" fill="var(--yellow)" stroke="#8a6d00" strokeWidth="1.8" />
            </g>
          </g>
        ))}
        {orderPts.map(({ r, p }, i) => (
          <MapPin key={r.id} x={p[0]} y={p[1]} urgent={isUrgent(r)} revealed={revealed}
            delay={350 + i * 70} selected={selectedId === r.id}
            label={r.worksite || r.site || ''} onClick={() => onSelect(r)} />
        ))}
      </svg>

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
