// Geocoding + road routing for the Leaflet map.
//
// Real records carry POSTCODES, not lat/lng, so we geocode them via
// postcodes.io (cached in localStorage), with an outcode-centroid fallback
// for terminated industrial postcodes. Road-based route geometry between two
// points comes from the public OSRM demo server, cached the same way.

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

// ---- OSRM road routing (public demo server) ----
let ROUTES = {};
try { ROUTES = JSON.parse(localStorage.getItem('r2routes') || '{}'); } catch { ROUTES = {}; }
function persistRoutes() { try { localStorage.setItem('r2routes', JSON.stringify(ROUTES)); } catch { /* quota */ } }

function routeKey(a, b) {
  const r = (n) => Math.round(n * 10000) / 10000;
  return `${r(a.la)},${r(a.lo)};${r(b.la)},${r(b.lo)}`;
}

// Road-based route geometry from a -> b ({la,lo} each), via the OSRM public
// demo server. Returns an array of [lat,lng] pairs to draw as a polyline.
// Falls back to a straight line (and caches that fallback) if OSRM is
// unreachable or finds no route — the demo server is unauthenticated and
// rate-limited, so failures are expected occasionally.
export async function routeBetween(a, b) {
  if (!a || !b) return null;
  const key = routeKey(a, b);
  if (ROUTES[key]) return ROUTES[key];
  const straight = [[a.la, a.lo], [b.la, b.lo]];
  try {
    const url = `https://router.project-osrm.org/route/v1/driving/${a.lo},${a.la};${b.lo},${b.la}?overview=full&geometries=geojson`;
    const r = await fetch(url);
    const d = await r.json();
    const coords = d && d.routes && d.routes[0] && d.routes[0].geometry && d.routes[0].geometry.coordinates;
    const line = coords ? coords.map(([lng, lat]) => [lat, lng]) : straight;
    ROUTES[key] = line;
  } catch {
    ROUTES[key] = straight;
  }
  persistRoutes();
  return ROUTES[key];
}
