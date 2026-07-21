// Geocoding + road routing for the Leaflet map.
//
// Real records carry POSTCODES, not lat/lng, so we geocode them via
// postcodes.io (cached in localStorage), with an outcode-centroid fallback
// for terminated industrial postcodes. Road-based route geometry between two
// points comes from the public OSRM demo server, cached the same way.

// Fixed collection depots — industrial postcodes are sometimes terminated and
// fail geocoding, and these three must always be on the map. Coordinates are
// each postcode's real centroid from postcodes.io (DN16 1BP is terminated —
// postcodes.io still returns its last-known centroid in the 404 body), not
// hand-estimated, so the pins land on the actual site rather than nearby.
export const DEPOTS = [
  { key: 'scun',  name: 'British Steel',   town: 'Scunthorpe', pc: 'DN16 1BP', lat: 53.5860, lng: -0.6543 },
  { key: 'ask',   name: 'Inframat / VAS',  town: 'Askern',     pc: 'DN6 0AA',  lat: 53.6127, lng: -1.1514 },
  { key: 'march', name: 'ArcelorMittal',   town: 'Marchwood',  pc: 'SO40 4UT', lat: 50.8926, lng: -1.4433 },
];

// A UK inward code is ALWAYS exactly three characters, so the outward code is
// everything except the last three. Pattern-matching the outward code and
// stripping the space (what this used to do) swallowed the inward code's first
// character: "DN3 1ED" read as DN31 (Grimsby) rather than DN3 (Doncaster) —
// ~40 miles out — and the same for PE3/CV3/B9. Mirrors postcodes.py.
function compactPc(p) {
  return String(p || '').replace(/[^A-Za-z0-9]/g, '').toUpperCase();
}
// Canonical 'OUTWARD INWARD'. Extracts arrive spaced ("LE10 1BJ  "), unspaced
// ("BS119DE") and occasionally with a stray middle space ("LE12 9 BS"); without
// canonicalising, the same place lands in the cache under several keys and a
// lookup from one spelling misses a pin geocoded under another.
export function pcNorm(p) {
  const s = compactPc(p);
  return s.length > 3 ? `${s.slice(0, -3)} ${s.slice(-3)}` : s;
}
export function outcodeOf(p) {
  const s = compactPc(p);
  return s.length > 3 ? s.slice(0, -3) : '';
}

// ---- postcode cache (shared with the map + drawer) ----
let GEO = {};
try { GEO = JSON.parse(localStorage.getItem('r2geo') || '{}'); } catch { GEO = {}; }
// Seed the shared cache with the depots' own precise coordinates (after
// loading any persisted cache, so this always wins over a stale/coarser
// cached value). Without this, a route leg or distance calc that looks up
// one of these postcodes falls through to the outcode-centroid fallback
// below — which can be ~2km off — while the depot pin itself renders at the
// precise DEPOTS coordinate, so the route wouldn't visually touch the pin.
DEPOTS.forEach((d) => { GEO[pcNorm(d.pc)] = { la: d.lat, lo: d.lng }; });
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
// v2: entries used to be a bare [[lat,lng],...] array; they now carry drive
// distance and time too. The key is versioned so a browser holding the old
// shape starts clean rather than reading `.line` off an array.
let ROUTES = {};
try { ROUTES = JSON.parse(localStorage.getItem('r2routes2') || '{}'); } catch { ROUTES = {}; }
function persistRoutes() { try { localStorage.setItem('r2routes2', JSON.stringify(ROUTES)); } catch { /* quota */ } }

function routeKey(a, b) {
  const r = (n) => Math.round(n * 10000) / 10000;
  return `${r(a.la)},${r(a.lo)};${r(b.la)},${r(b.lo)}`;
}

// Road route from a -> b ({la,lo} each) via the OSRM public demo server.
// Returns { line, meters, seconds, road } — the geometry to draw plus the
// drive distance and time, which is what an ETA is actually made of. OSRM
// hands us duration and distance in the same response, so asking for a route
// and asking for an ETA is one request, not two.
//
// Falls back to a straight line (and caches it) if OSRM is unreachable or
// finds no route — the demo server is unauthenticated and rate-limited, so
// failures are expected. A fallback is marked road:false so the UI can be
// honest that the time is estimated rather than routed.
export async function routeBetween(a, b) {
  if (!a || !b) return null;
  const key = routeKey(a, b);
  if (ROUTES[key]) return ROUTES[key];
  const straight = [[a.la, a.lo], [b.la, b.lo]];
  try {
    const url = `https://router.project-osrm.org/route/v1/driving/${a.lo},${a.la};${b.lo},${b.la}?overview=full&geometries=geojson`;
    const r = await fetch(url);
    const d = await r.json();
    const rt = d && d.routes && d.routes[0];
    const coords = rt && rt.geometry && rt.geometry.coordinates;
    ROUTES[key] = coords
      ? { line: coords.map(([lng, lat]) => [lat, lng]),
          meters: rt.distance, seconds: rt.duration, road: true }
      : { line: straight, meters: null, seconds: null, road: false };
  } catch {
    ROUTES[key] = { line: straight, meters: null, seconds: null, road: false };
  }
  persistRoutes();
  return ROUTES[key];
}
