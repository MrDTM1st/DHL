// Domain helpers, ported from the logic the original inline dashboard ran in
// the browser (region2-emailer/cloud/server.py) and kept faithful to the real
// tracker-record shape the home agent pushes:
//   { id, orders[], materials, product_codes[], to, delivery_date (dd/mm/yyyy),
//     emailed_at, chases, reply_at, ooo_at, sendoff_ready, site, worksite,
//     postcode, collection_site, collection_pc, details{}, missing[], loose_ballast }

// ONE postcode normaliser lives in geo.js (it owns the geocode cache these keys
// index). Re-exported here so existing importers don't have to change - two
// copies is exactly how cache keys drift apart and pins go missing.
import { pcNorm } from './geo.js';
import { namedPhones, phonesIn } from './phone.js';
export { pcNorm };

// Every collection point on the record, one shape regardless of age: newer
// records carry a `collections` list (a job can load at SEVERAL sites - e.g.
// 6055263 collects at Trackwork Moll AND Cemex Somercotes), older ones only
// the single collection_site/pc pair.
export function collectionsOf(r) {
  const list = (r.collections || []).filter((c) => c && (c.site || c.pc));
  if (list.length) return list;
  if (r.collection_site || r.collection_pc) {
    return [{ site: r.collection_site || '', pc: r.collection_pc || '' }];
  }
  return [];
}

// Days from today to a dd/mm/yyyy string. null if unparseable.
export function wlDays(dd) {
  const m = String(dd || '').match(/(\d{2})\/(\d{2})\/(\d{4})/);
  if (!m) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const dt = new Date(+m[3], +m[2] - 1, +m[1]);
  return Math.round((dt - today) / 86400000);
}

export function within3(dd) {
  const n = wlDays(dd);
  return n !== null && n >= 0 && n <= 3;
}

// The redesign's chosen urgency trigger: a delivery inside 3 days, or a loose
// ballast job (which always needs booking attention).
export function isUrgent(r) {
  return within3(r.delivery_date || r.date) || !!r.loose_ballast;
}

export function urgScore(r) {
  return (within3(r.delivery_date || r.date) ? 2 : 0) + (r.loose_ballast ? 1 : 0);
}

export function ordLabel(r) {
  return (r.orders || []).join(' / ');
}

// Pipeline stage 0..3 (Drafted -> Emailed -> Reply -> Sent off) from the real
// timestamp fields.
export function stageOf(r) {
  if (r.sendoff_ready) return 3;
  if (r.reply_at) return 2;
  if (r.emailed_at) return 1;
  return 0;
}

export const STAGES = ['Drafted', 'Emailed', 'Reply in', 'Sent off'];

export function statusLabel(r) {
  if (r.kind === 'adhoc') return 'Ad hoc — CSV ready';
  if (r.kind === 'dts') return 'DTS — CSV ready';
  // pinned by hand: there is no tracker record behind it, so none of the
  // stage fields below mean anything for one of these
  if (r.kind === 'pinned') return r.booked ? 'By hand — booked in'
    : (r.tracked ? 'By hand — tracked' : 'By hand — map only');
  if (r.sendoff_ready) return 'Sent off';
  if (r.ooo_at) return 'Out of office';
  if ((r.chases || 0) > 0) return 'Chased ×' + r.chases;
  if (r.reply_at) return 'Replied';
  if (r.emailed_at) return 'Awaiting reply';
  return 'Drafted';
}

export function isAmberStatus(r) {
  return !!r.ooo_at || (r.chases || 0) > 0;
}

// Human due text from delivery_date.
export function dueText(r) {
  const n = wlDays(r.delivery_date || r.date);
  if (n === null) return r.delivery_date ? 'due ' + r.delivery_date : '';
  if (n < 0) return Math.abs(n) + 'd overdue';
  if (n === 0) return 'due today';
  if (n === 1) return 'due tomorrow';
  return 'due in ' + n + 'd';
}

// dd/mm short form for compact display.
export function dateShort(dd) {
  const m = String(dd || '').match(/(\d{2})\/(\d{2})\/(\d{4})/);
  return m ? m[1] + '/' + m[2] : String(dd || '');
}

// Detail-field helpers for the tracker's parsed delivery-detail chips.
export const DFIELDS = [
  ['date', 'Date'], ['time', 'Time'], ['offloading', 'Offload'], ['artic_access', 'Artic'],
  ['rear_steer', 'Rear steer'], ['vehicle', 'Vehicle'], ['pts', 'PTS'],
  ['what3words', 'W3W'], ['contact', 'Contact'],
];

export function detVal(k, v) {
  if (!v) return '';
  if (k === 'time') return v.earliest ? (v.latest ? v.earliest + '-' + v.latest : v.earliest) : '';
  if (k === 'contact') return [v.name, v.phone].filter(Boolean).join(' ');
  return v.value || '';
}

// Who to ring at the site, and on which numbers: { name, calls: [{number, name}], from }.
// The site's REPLY wins - that is the person who answered, often with a better
// number or a second contact. Before a reply, the contact on the order itself
// (site_phone / site_contact, which the home PC adds from the extract). Ad hocs
// carry the request form's contact in details.contact, the same as a reply.
export function siteContactOf(r) {
  const c = (r && r.details && r.details.contact) || {};
  let calls = namedPhones([c.raw, c.phone].filter(Boolean).join(' / '));
  let from = 'reply';
  if (calls.length && c.name) calls[0] = { ...calls[0], name: c.name };
  if (!calls.length) {
    calls = phonesIn(r && r.site_phone).map((number) => ({ number, name: (r && r.site_contact) || '' }));
    from = calls.length ? 'order' : '';
  }
  return { name: c.name || (r && r.site_contact) || '', calls, from };
}

// What a job can need from a haulier, in the contact sheet's OWN capability
// names, matched EXACTLY. A need is met by ANY one of its `any` list. Matching
// on bits of words is how "artic" found Artic Tipper and "rigid" found Rigid
// Tipper, so firms that run nothing but tippers were offered
// bagged ballast and pallets they cannot carry (Delali, 30/10: "some of the
// hauliers that are listed for certain orders are not even supposed to be on
// there").
const needOf = (label, ...any) => ({ label, any });
const TIPPER = needOf('tipper', 'Rigid Tipper', 'Artic Tipper');
const RIGID_TIPPER = needOf('rigid tipper', 'Rigid Tipper');
const HIAB = needOf('rigid or artic hiab', 'Rigid Hiab', 'Artic Hiab');
const RIGID_HIAB = needOf('rigid hiab', 'Rigid Hiab');
const ARTIC_HIAB = needOf('artic hiab', 'Artic Hiab');
const HIAB_OR_MOFFETT = needOf('hiab or moffett', 'Rigid Hiab', 'Artic Hiab', 'Moffett');
const MOFFETT = needOf('moffett', 'Moffett');
// a hiab wagon is a flatbed with a crane, so it carries flat work too
const RIGID_FLAT = needOf('rigid flat', 'Short Flat', 'Rigid Hiab');
const ARTIC_FLAT = needOf('artic flat', 'Artic Flat', 'Artic Hiab', '60ft Flat', 'Trombone (80ft +)');
const FLAT_60 = needOf('60ft flat', '60ft Flat', 'Trombone (80ft +)');
const TROMBONE = needOf('trombone (80ft+)', 'Trombone (80ft +)');
const ANY_FLAT = needOf('flatbed', 'Artic Flat', 'Short Flat', '60ft Flat', 'Rigid Hiab', 'Artic Hiab', 'Wagon & Drag');
// no stated material or vehicle: still a load on a flatbed, a curtain or a
// van - never a tipper-only or log-grab-only firm
const GENERAL = needOf('flatbed, curtain or van', ...ANY_FLAT.any, 'Artic Curtain', 'Vans', '7.5T', 'Trombone (80ft +)');
// a luton or a tail-lift wagon: a van or a 7.5-tonner
const SMALL = needOf('van or 7.5t', 'Vans', '7.5T');
const RAIL = needOf('rail / S&C', 'Rail / S&C');
const WHEELSETS = needOf('wheelsets', 'Wheelsets');
const REAR_STEER = needOf('rear steer', 'Rear Steer', 'Remote Rear Steer');
const PTS = needOf('PTS', 'PTS');

// CTMS vehicle codes, decoded. Delali (24/07): "NR_ART_40_CT means artic
// curtain". The codes compose: ART(IC)=artic, CT=curtain, FL=flat,
// TAIL=tail-lift, TIP=tipper, TROM=trombone, RIG=rigid, a bare number =
// trailer length in ft, <n>T = tonnage. Known examples: NR_ART_40_CT (artic
// curtain 40ft), NR_ARTIC_FL / NR_40ft Artic Flatbed (artic flat),
// NR_60_ART_FL (artic flat 60ft), NR_TROM_80ft (trombone), NR_FLAT_RIG (rigid
// flat), NR_7.5T_TAIL (7.5t tail-lift), NR_R_TIP26_8 (26t rigid tipper - the
// stoneblower wagon), NR_TRANSIT. A reply's own word ("rigid", "18t") lands
// here too. `need` is only set when the code says exactly which vehicle,
// because needsFor treats it as a HARD filter.
export function vehicleInfo(code) {
  const c = String(code || '').toUpperCase().trim();
  if (!c) return { label: '', need: null, weight: null, rigid: false, artic: false };
  const artic = /ART/.test(c);
  const curtain = /(^|_)CT(_|$)|CURT/.test(c);
  const flat = /(^|_)FL(_|$)|FLAT/.test(c);
  const tail = /TAIL|_TL(_|$)/.test(c);
  const trombone = /TROM/.test(c);
  const tipper = /TIP/.test(c);
  const van = /TRANSIT|(^|_)VAN/.test(c);
  const weight = (c.match(/(\d+(?:\.\d+)?)\s?T(_|$|\s)/) || [])[1] || null;
  const len = (c.match(/(^|_)(\d{2})(_|$|FT)/) || [])[2] || null;
  // a tonnage is a rigid's (7.5t, 18t, 26t) - artics are never coded by weight
  const rigid = !artic && !van && (/RIG|R_TIP/.test(c) || !!weight);
  const bits = [];
  if (weight) bits.push(weight + 't');
  if (artic) bits.push('artic');
  else if (rigid && !weight) bits.push('rigid');
  if (trombone) bits.push('trombone');
  else if (tipper) bits.push('tipper');
  else if (curtain) bits.push('curtain');
  else if (flat) bits.push('flat');
  if (van) bits.push('van');
  if (len && !weight) bits.push(len + 'ft');
  if (tail) bits.push('tail-lift');
  let vneed = null;
  if (trombone || (len && +len >= 80)) vneed = TROMBONE;
  else if (tipper) vneed = rigid ? RIGID_TIPPER : TIPPER;
  else if (artic && curtain) vneed = needOf('artic curtain', 'Artic Curtain');
  else if (artic && flat) vneed = len === '60' ? FLAT_60 : ARTIC_FLAT;
  else if (van) vneed = needOf('van', 'Vans');
  else if (weight === '7.5') vneed = needOf('7.5t', '7.5T');
  else if (rigid && !weight) vneed = RIGID_FLAT;      // NR_FLAT_RIG, NR_Rigid, "rigid"
  return { label: bits.join(' '), need: vneed, weight, rigid, artic };
}

// "72x ballast", "15x ballast, 7x aggregate", "10x 1t bags of ballast" ->
// how many 1t bags. 0 when the summary gives no count.
function bagsIn(mats) {
  let n = 0;
  for (const m of mats.matchAll(/(\d+)\s*x\s*[^,;]*?(ballast|aggregate|bag)/g)) n += +m[1];
  return n;
}

// The longest length named in the materials, in metres ("18.288m", "36 m",
// "60ft"), or null.
function longestMetres(mats) {
  const ms = [...mats.matchAll(/(\d+(?:\.\d+)?)\s*m\b/g)].map((m) => +m[1]);
  const fs = [...mats.matchAll(/(\d+(?:\.\d+)?)\s*(?:ft|feet)\b/g)].map((m) => +m[1] * 0.3048);
  const all = ms.concat(fs).filter((x) => x > 0 && x < 200);
  return all.length ? Math.max(...all) : null;
}

// Which vehicle a job needs, from its materials and the site's answers - the
// way Delali books them:
//   * bagged ballast/aggregate: a HIAB wagon (the site offloads it with ours),
//     and over 20 bags it is artics - "an artic HIAB only takes 20 bags; the
//     booking splits it later" (30/10). Bags never needed the 'Bags' flag
//     (only 27 firms carry it - two dozen able firms were being left out).
//   * loose ballast and stoneblower stone: TIPPED, so a tipper. Stoneblowers
//     book on NR_R_TIP26_8, the 26t rigid tipper (29/10).
//   * sleepers, bearers and troughing: "sleepers go on rigids and artics,
//     rigid hiabs and artic hiabs" (15/09) - a hiab of either size, or any
//     flatbed when the site offloads them itself.
//   * rails and S&C: the Rail / S&C fleet. Over 60ft (18.3m) only a trombone
//     takes them.
//   * wheelsets: the firms flagged for wheelsets.
//   * PTS never for ballast (his rule, 30/10); rear steer never on a rigid
//     (his rule, 30/10) - it is an artic thing.
// Returns the needs ({label, any[]}) plus what the job is, for the ranking.
export function jobOf(r) {
  const d = r.details || {};
  const mats = ((r.materials || '') + ' ' + (r.product_codes || []).join(' ')).toLowerCase();
  const vi = vehicleInfo((d.vehicle || {}).value || '');
  const off = (d.offloading || {}).value || '';
  const noArtics = (d.artic_access || {}).value === 'no';
  const rigid = vi.rigid || noArtics;
  // Mirrors is_loose_ballast() in build_drafts.py: ballast AND loose. The stock
  // code is the last resort and the only one that works on records written
  // before the summary kept the word: the tracker keeps product_codes even when
  // materials has collapsed to "80x ballast". Verified against
  // Synergy_DHL_Haulier_Extract_260826a:
  //     0057/100500/001 = Track ballast (50mm) - Loose
  //     0057/100500/002 = Track ballast (50mm) - 1 tonne bags
  const looseCode = (r.product_codes || []).some((c) => String(c).trim().endsWith('100500/001'));
  const stoneblower = /stone\s*-?\s*blower/.test(mats);
  const loose = !!r.loose_ballast || (/ballast/.test(mats) && /loose/.test(mats)) || looseCode;
  const ballast = /ballast|aggregate/.test(mats) || stoneblower;
  const bagged = !loose && !stoneblower && /ballast|aggregate|\bbags?\b/.test(mats);
  const bags = bagged ? bagsIn(mats) : 0;
  // each line on its own: a sleeper's stock line can name the rail it is for
  // ("... BASEPLATE FOR INCLINED CEN56 RAIL", "GUARD RAIL SLEEPER", "SWITCH
  // BEARER") and is still a sleeper
  const items = String(r.materials || '').split(/[,;]/).concat(r.product_codes || [])
    .map((x) => String(x).toLowerCase());
  const isSleeper = (x) => /sleeper|bearer|trough/.test(x);
  const sleepers = items.some(isSleeper);
  const railItems = items.filter((x) => !isSleeper(x) && /\brails?\b|s&c|switch|crossing|half set/.test(x));
  const rails = railItems.length > 0;
  const metres = rails ? longestMetres(railItems.join(' ')) : null;
  const wheelsets = /wheelset/.test(mats);
  const out = [];
  if (loose || stoneblower) out.push(vi.need === RIGID_TIPPER ? RIGID_TIPPER : TIPPER);
  if (rails) {
    out.push(RAIL);
    if (metres !== null && metres > 18.3) out.push(TROMBONE);
    else if (metres !== null && metres > 13.6) out.push(FLAT_60);    // longer than a normal trailer
  }
  if (wheelsets) out.push(WHEELSETS);
  // offloading - what lifts it off at the site
  if (!loose && !stoneblower) {
    // more than an artic hiab's 20 bags, or an artic named outright
    const big = (bags > 20 && !noArtics) || vi.artic;
    const hiab = big ? ARTIC_HIAB : (rigid ? RIGID_HIAB : (rails && !noArtics ? ARTIC_HIAB : HIAB));
    if (off === 'MOFFETT') out.push(MOFFETT);
    else if (off === 'BOTH') out.push(HIAB_OR_MOFFETT);
    else if (off === 'HIAB') out.push(hiab);
    else if (off === 'SITE/NONE') {
      if (bagged || sleepers) out.push(big ? ARTIC_FLAT : (rigid ? RIGID_FLAT : ANY_FLAT));
    } else if (bagged || sleepers) out.push(hiab);   // not said: they need our lifting gear
  }
  if (((d.rear_steer || {}).value) === 'yes' && !rigid) out.push(REAR_STEER);
  if (((d.pts || {}).value) === 'yes' && !ballast) out.push(PTS);
  // a stated vehicle is a requirement too - unless a need already there is
  // stricter (an artic hiab is an artic flat with a crane)
  if (vi.need && !out.some((n) => n.any.every((c) => vi.need.any.includes(c)))) out.push(vi.need);
  // an ad hoc form often names its vehicle in the free text instead
  // ("3.5 - 7.5 tonne luton with tail lift required")
  const said = (mats + ' ' + String(r.weight || '') + ' ' + String(r.product || '')).toLowerCase();
  if (!vi.need && /luton|tail\s*-?\s*lift/.test(said)) out.push(SMALL);
  if (!out.length) out.push(GENERAL);
  return { need: out, rails, metres, rearSteer: out.includes(REAR_STEER) };
}

// What a job needs from a haulier - [{label, any[]}], each met by ANY of its
// capabilities. Drives the haulier capability match.
export function needsFor(r) {
  return jobOf(r).need;
}

// Which NR materials team owns this order's product - the escalation route
// when the site contact can't be reached ("ask the steel materials people for
// an alternative contact"). Mirrors build_drafts.product_type's keywords.
// Returns 'rails' | 'ballast' | 'sleepers' | null.
export function materialsTypeFor(r) {
  const d = ((r.materials || '') + ' ' + (r.product_codes || []).join(' ')).toUpperCase();
  // troughing belongs to the sleepers team (it's literally in their name);
  // S&C call-offs come FROM Steel Materials, so switches/crossings go there
  if (d.includes('SLEEPER') || d.includes('TROUGH')) return 'sleepers';
  if (d.includes('BALLAST')) return 'ballast';
  if (d.includes('RAIL') || d.includes('SWITCH') || d.includes('CROSSING') || d.includes('S&C')) return 'rails';
  return null;
}

// Is any leg of this job at night (window starting 20:00-05:59) or on a
// weekend? Some carriers avoid that work - DHL NOC in particular - so the
// ranking needs to know. Returns e.g. ['night', 'weekend'] or [].
export function nightWeekendFor(r) {
  const d = r.details || {};
  const rl = r.return_leg || null;
  const dates = [r.delivery_date, r.collection_date,
    rl && rl.collection_date, rl && rl.delivery_date].filter(Boolean);
  const weekend = dates.some((dd) => {
    const m = String(dd).match(/(\d{2})\/(\d{2})\/(\d{4})/);
    if (!m) return false;
    const day = new Date(+m[3], +m[2] - 1, +m[1]).getDay();
    return day === 0 || day === 6;
  });
  const wins = [d.time, d.collection_time, rl && rl.time, rl && rl.collection_time].filter(Boolean);
  const night = wins.some((t) => {
    const h = parseInt(String(t.earliest || '').split(':')[0], 10);
    return !Number.isNaN(h) && (h >= 20 || h < 6);
  });
  const out = [];
  if (night) out.push('night');
  if (weekend) out.push('weekend');
  return out;
}

// Ad hoc routing rule: Parcel Pass is the default carrier for small ad hoc
// loads (boxes, parcels, pallets) moving on a transit van, 7.5t or 18t with
// no lifting kit. Anything needing a HIAB/Moffett, PTS, a rear steer or a
// bigger/special vehicle goes to the normal haulier ring-round instead.
// Returns null for non-adhoc records; {ok, reasons, vehicle} otherwise.
export function parcelPassFor(r) {
  // Parcel Pass is judged on the load, and a DTS is the same shape of job as an
  // ad hoc - both arrive as a one-off with a CSV, neither is a tracked order.
  if (r.kind !== 'adhoc' && r.kind !== 'dts') return null;
  const d = r.details || {};
  const off = (d.offloading || {}).value || '';
  const veh = ((d.vehicle || {}).value || '').trim();
  const vi = vehicleInfo(veh);
  const reasons = [];
  if (off === 'HIAB') reasons.push('needs a HIAB');
  if (off === 'MOFFETT') reasons.push('needs a Moffett');
  if ((d.pts || {}).value === 'yes') reasons.push('needs PTS');
  if ((d.rear_steer || {}).value === 'yes') reasons.push('needs a rear steer');
  // Parcel Pass runs transits, 7.5-tonners and 18-tonners - anything bigger
  // or more specialist is a no (named readably, not as the raw CTMS code)
  const smallVehicle = !veh || /transit|van|sprinter/i.test(veh)
    || vi.weight === '7.5' || vi.weight === '18';
  if (!smallVehicle) reasons.push('needs a ' + (vi.label || veh));
  return { ok: reasons.length === 0, reasons, vehicle: vi.label || veh };
}

export function milesBetween(a, b) {
  if (!a || !b) return null;
  const R = 3958.8, t = Math.PI / 180;
  const dla = (b.la - a.la) * t, dlo = (b.lo - a.lo) * t;
  const h = Math.sin(dla / 2) ** 2 + Math.cos(a.la * t) * Math.cos(b.la * t) * Math.sin(dlo / 2) ** 2;
  return Math.round(2 * R * Math.asin(Math.sqrt(h)) * 10) / 10;
}

// Rank hauliers for a job. Order of approach is DHL's OWN fleet -> tier 1 ->
// tier 2; distance only breaks ties inside a band. `geo` is the postcode->
// {la,lo} cache; hauliers come from the agent-pushed panel.
//
// Distance is measured from WHICHEVER END IS NEARER - collection or delivery.
// A haulier based near the drop is just as workable as one near the pick-up
// (they can run empty to collect, or be coming back that way), so ranking only
// off the collection end hides good local options. `nearEnd` says which one it
// is, so the reason a haulier is near is never a mystery.
//
// DHL NOC (our fleet) is left off - not just ranked lower - where it cannot take
// the job (Delali, 02/10): rails over 18.3m, rear steer, night or weekend work.
// `leftOff` says who was left off and why, so the drawer can say so.
export function recommendFor(r, hauliers, geo) {
  const job = jobOf(r);
  const need = job.need;
  const nw = nightWeekendFor(r);
  const fleetCant = (h) => {
    if (!h.fleet && !h.avoid_nw) return '';
    if (h.avoid_nw && nw.length) return nw.join(' & ') + ' work';
    if (!h.fleet) return '';
    if (job.rearSteer) return 'rear steer';
    if (job.metres !== null && job.metres > 18.3) return 'rails over 18.3m';
    return '';
  };
  const leftOff = [];
  const colls = collectionsOf(r);
  const cgs = colls.map((c) => geo[pcNorm(c.pc || '')]).filter(Boolean);
  const dg = geo[pcNorm(r.postcode || '')];
  // coverage is a hard filter like capability. no_go_scope says WHICH end the
  // no-go areas apply to: HHL happily COLLECTS from the north (loads originate
  // at the steelworks and flow south) but won't DELIVER there, so their scope
  // is 'delivery'; the default is 'both'. A multi-collection job needs the
  // haulier at EVERY pick-up, so one no-go collection rules them out.
  const areaOf = (p) => { const m = pcNorm(p).match(/^[A-Z]+/); return m ? m[0] : ''; };
  const cAreas = colls.map((c) => areaOf(c.pc || '')).filter(Boolean);
  const dArea = areaOf(r.postcode || '');
  const outsideCoverage = (h) => {
    const areas = h.no_go || [];
    if (!areas.length) return false;
    const scope = h.no_go_scope || 'both';
    if ((scope === 'both' || scope === 'collection') && cAreas.some((a) => areas.includes(a))) return true;
    if ((scope === 'both' || scope === 'delivery') && dArea && areas.includes(dArea)) return true;
    return false;
  };
  const out = (hauliers || []).filter((h) => {
    if (h.parcel) return false;   // Parcel Pass is a booking service, never ranked
    if (outsideCoverage(h)) return false;
    // every need met by one of its capabilities, named exactly as the sheet does
    const caps = new Set((h.caps || []).map((c) => String(c).trim().toLowerCase()));
    if (!need.every((n) => n.any.some((c) => caps.has(c.toLowerCase())))) return false;
    const why = fleetCant(h);
    if (why) leftOff.push({ name: h.name, why });
    return !why;
  }).map((h) => {
    const g = geo[pcNorm(h.pc || '')];
    // nearest of the collection points - the run starts wherever suits them
    const mcs = g ? cgs.map((c) => milesBetween(c, g)).filter((x) => x !== null) : [];
    const mc = mcs.length ? Math.min(...mcs) : null;
    const md = g && dg ? milesBetween(dg, g) : null;
    const both = [['collection', mc], ['delivery', md]].filter((x) => x[1] !== null);
    both.sort((a, b) => a[1] - b[1]);
    return Object.assign({}, h, {
      miles: both.length ? both[0][1] : null,
      nearEnd: both.length ? both[0][0] : null,
      milesCollection: mc, milesDelivery: md,
    });
  });
  out.forEach((h) => { h.rank = h.fleet ? 0 : (h.tier === 'tier1' ? 1 : 2); });
  // Band order is the order of APPROACH, but a haulier that is much closer than
  // everyone ahead of it is worth surfacing rather than burying - a tier 2 at
  // 18mi against tier 1s at 115mi+ is usually the cheaper run, and you'd want
  // to know before ringing round in band order.
  // "Closer" is measured against the band IMMEDIATELY above (the nearest band
  // that actually has anyone in it) - not against the overall best.
  //
  // Comparing against the overall best is wrong because our own fleet is always
  // approached first regardless of distance: a DHL depot next door to the job
  // would set a bar no external haulier could beat, and a tier 2 sitting 18mi
  // away against tier 1s at 115mi+ would never light up. The real question a
  // tier 2 answers is "am I better than the tier 1s you'd otherwise ring?", so
  // that is what it is compared with. (Once quote history is deep enough,
  // cheapest supersedes distance here.)
  const bandBest = (rank) => {
    const m = out.filter((h) => h.rank === rank && h.miles !== null).map((h) => h.miles);
    return m.length ? Math.min(...m) : null;
  };
  const best = [bandBest(0), bandBest(1), bandBest(2)];
  out.forEach((h) => {
    if (h.miles === null || h.rank === 0) return;   // the fleet leads by policy, never "closer"
    let above = null;
    for (let b = h.rank - 1; b >= 0 && above === null; b -= 1) above = best[b];
    if (above !== null && h.miles < above) h.closerThanAbove = true;
  });
  out.sort((a, b) => a.rank - b.rank
    || (a.miles === null) - (b.miles === null)
    || (a.miles || 9e9) - (b.miles || 9e9)
    || a.name.localeCompare(b.name));
  return { need, list: out, nw, leftOff };
}

// The map's order list: soonest delivery first (so the urgent ones lead), then
// orders with no date, then those already past their delivery date - most
// recent first - which still sit on the map until someone presses Booked.
// Delali (30/10): shown to his manager, "it looks pretty embarrassing because
// things weren't in order".
export function byDeliveryDate(records) {
  const key = (r) => {
    const n = wlDays(r.delivery_date || r.date);
    if (n === null) return [1, 0];
    return n >= 0 ? [0, n] : [2, -n];
  };
  return [...records].sort((a, b) => {
    const ka = key(a), kb = key(b);
    return ka[0] - kb[0] || ka[1] - kb[1] || ordLabel(a).localeCompare(ordLabel(b));
  });
}

export const RANK_TAG = ['fleet', 't1', 't2'];
export const RANK_LABEL = ['OUR FLEET', 'TIER 1', 'TIER 2'];

// ---- drive time / ETA formatting ----
export function fmtDur(seconds) {
  if (seconds == null) return null;
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h ${String(m % 60).padStart(2, '0')}m`;
}

export function metersToMiles(m) {
  return m == null ? null : Math.round((m / 1609.344) * 10) / 10;
}

// Clock time `seconds` from now, e.g. an arrival if you left this minute.
export function clockIn(seconds, from = new Date()) {
  if (seconds == null) return null;
  const t = new Date(from.getTime() + seconds * 1000);
  const same = t.toDateString() === from.toDateString();
  const hhmm = `${String(t.getHours()).padStart(2, '0')}:${String(t.getMinutes()).padStart(2, '0')}`;
  return same ? hhmm : `${hhmm} +${Math.round((t - from) / 86400000) || 1}d`;
}

// The whole job as a haulier actually drives it: their base -> the collection
// (repositioning, running empty) -> the delivery. `repo` and `leg` are
// routeBetween results. Returns nulls rather than guessing when a leg is
// missing, so the UI can say "—" instead of inventing a time.
export function journeyFor(repo, leg) {
  const s = (x) => (x && x.seconds != null ? x.seconds : null);
  const m = (x) => (x && x.meters != null ? x.meters : null);
  const repoS = s(repo), legS = s(leg);
  return {
    repoSeconds: repoS, repoMiles: metersToMiles(m(repo)),
    legSeconds: legS, legMiles: metersToMiles(m(leg)),
    totalSeconds: repoS != null && legS != null ? repoS + legS : null,
    totalMiles: m(repo) != null && m(leg) != null ? metersToMiles(m(repo) + m(leg)) : null,
    estimated: !!((repo && repo.road === false) || (leg && leg.road === false)),
  };
}

