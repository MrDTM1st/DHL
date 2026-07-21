// Map geometry + geocoding.
//
// The redesign wants the prototype's animated d3-geo UK map (pins drop in,
// routes draw). The real records carry POSTCODES, not lat/lng, so we geocode
// them the same way the original page did — postcodes.io, cached in
// localStorage, with an outcode-centroid fallback for terminated industrial
// postcodes — then project the resulting lat/lng onto the d3-geo UK outline.

import { geoMercator, geoPath } from 'd3-geo';
import { feature } from 'topojson-client';

export const VW = 720, VH = 900;

// Fixed collection depots — industrial postcodes are sometimes terminated and
// fail geocoding, and these three must always be on the map.
export const DEPOTS = [
  { key: 'scun',  name: 'British Steel',   town: 'Scunthorpe', pc: 'DN16 1BP', lat: 53.579, lng: -0.617 },
  { key: 'ask',   name: 'Inframat / VAS',  town: 'Askern',     pc: 'DN6 0AA',  lat: 53.616, lng: -1.155 },
  { key: 'march', name: 'ArcelorMittal',   town: 'Marchwood',  pc: 'SO40 4UT', lat: 50.895, lng: -1.442 },
];

export function pcNorm(p) {
  return String(p || '').toUpperCase().replace(/\s+/g, ' ').trim();
}
function outcodeOf(p) {
  const m = String(p || '').toUpperCase().replace(/\s+/g, '').match(/^([A-Z]{1,2}\d[A-Z\d]?)/);
  return m ? m[1] : '';
}

// ---- postcode cache (shared with the map + drawer) ----
let GEO = {};
try { GEO = JSON.parse(localStorage.getItem('r2geo') || '{}'); } catch { GEO = {}; }
export function geoCache() { return GEO; }
function persist() { try { localStorage.setItem('r2geo', JSON.stringify(GEO)); } catch { /* quota */ } }

// Geocode a batch of postcodes into GEO. Resolves when everything known is
// cached. Network failures leave entries unresolved (map simply shows fewer
// pins) rather than throwing.
export async function geocode(pcs) {
  const want = [...new Set(pcs.map(pcNorm).filter(Boolean))];
  const need = want.filter((p) => GEO[p] === undefined);
  for (let i = 0; i < need.length; i += 90) {
    try {
      const r = await fetch('https://api.postcodes.io/postcodes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ postcodes: need.slice(i, i + 90) }),
      });
      const d = await r.json();
      (d.result || []).forEach((x) => {
        GEO[pcNorm(x.query)] = x.result ? { la: x.result.latitude, lo: x.result.longitude } : null;
      });
    } catch { /* offline — leave unresolved */ }
  }
  // Outcode-centroid fallback for terminated postcodes (e.g. DN16 1BP).
  for (const p of want) {
    if (GEO[p]) continue;
    const oc = outcodeOf(p); if (!oc) continue;
    const key = 'OC:' + oc;
    if (GEO[key] === undefined) {
      try {
        const r = await fetch('https://api.postcodes.io/outcodes/' + oc);
        const d = await r.json();
        GEO[key] = d.result ? { la: d.result.latitude, lo: d.result.longitude } : null;
      } catch { GEO[key] = null; }
    }
    if (GEO[key]) GEO[p] = GEO[key];
  }
  persist();
  return GEO;
}

// ---- d3-geo UK projection (for the animated SVG map) ----
let _geom = null; // { land(path string), project(lng,lat) -> [x,y] }

function fallbackProjection() {
  return geoMercator().center([-3.0, 54.9]).scale(2650).translate([VW * 0.52, VH * 0.5]);
}

export async function loadGeom() {
  if (_geom) return _geom;
  let projection, land = '';
  try {
    const topo = await (await fetch('https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json')).json();
    const feats = feature(topo, topo.objects.countries).features;
    const uk = feats.find((f) => String(f.id) === '826' || (f.properties && f.properties.name === 'United Kingdom'));
    projection = geoMercator().fitExtent([[46, 40], [VW - 30, VH - 40]], uk);
    land = geoPath(projection)(uk);
  } catch {
    projection = fallbackProjection();
  }
  if (!projection) projection = fallbackProjection();
  _geom = { land, project: (lng, lat) => projection([lng, lat]) };
  return _geom;
}
