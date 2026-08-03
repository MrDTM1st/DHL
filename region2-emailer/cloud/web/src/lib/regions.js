// Which Network Rail region a postcode belongs to - R1 to R4.
//
// Generated from the "Postcode Areas Search" workbook (the authoritative list),
// mirroring region2-emailer/nr_regions.json. Keep the two in step; the Python
// side is the source of truth and this is the browser copy, for the same reason
// the postcode helpers exist in both - the UI has no backend endpoint to ask.
//
// Keyed on the AREA (the letters), which the workbook shows is safe: it lists
// per-district rows for the big single-letter areas (B1..B99, S1..S99, and the
// same for E, G, L, M, N, W) and every district agrees with its own area. No
// area is split across two NR regions.
import { areaOf } from './geo';

// The region this desk actually runs. Anything else showing up on the tracker
// is worth seeing rather than hiding - it means an order got in that is not
// ours, or that the region scope needs widening (SS was missing until 2026-08).
export const HOME_REGION = 'R2';

export const AREA_REGION = {
  AB: 'R1', AL: 'R4', B: 'R2', BA: 'R3', BB: 'R1', BD: 'R1', BH: 'R3', BL: 'R1', BN: 'R4', BR:
  'R4', BS: 'R3', CA: 'R1', CB: 'R2', CF: 'R3', CH: 'R1', CM: 'R4', CO: 'R2', CR: 'R4', CT:
  'R4', CV: 'R2', CW: 'R1', DA: 'R4', DD: 'R1', DE: 'R2', DG: 'R1', DH: 'R1', DL: 'R1', DN:
  'R2', DT: 'R3', DY: 'R2', E: 'R4', EC: 'R4', EH: 'R1', EN: 'R4', EX: 'R3', FK: 'R1', FY:
  'R1', G: 'R1', GL: 'R3', GU: 'R4', HA: 'R4', HD: 'R1', HG: 'R1', HP: 'R4', HR: 'R2', HU:
  'R1', HX: 'R1', IG: 'R4', IP: 'R2', IV: 'R1', KA: 'R1', KT: 'R4', KW: 'R1', KY: 'R1', L:
  'R1', LA: 'R1', LD: 'R3', LE: 'R2', LL: 'R2', LN: 'R2', LS: 'R1', LU: 'R4', M: 'R1', ME:
  'R4', MK: 'R4', ML: 'R1', N: 'R4', NE: 'R1', NG: 'R2', NN: 'R2', NP: 'R3', NR: 'R2', NW:
  'R4', OL: 'R1', OX: 'R4', PA: 'R1', PE: 'R2', PH: 'R1', PL: 'R3', PO: 'R4', PR: 'R1', RG:
  'R4', RH: 'R4', RM: 'R4', S: 'R2', SA: 'R3', SE: 'R4', SG: 'R4', SK: 'R1', SL: 'R4', SM:
  'R4', SN: 'R3', SO: 'R4', SP: 'R3', SR: 'R1', SS: 'R2', ST: 'R2', SW: 'R4', SY: 'R2', TA:
  'R3', TD: 'R1', TF: 'R2', TN: 'R4', TQ: 'R3', TR: 'R3', TS: 'R1', TW: 'R4', UB: 'R4', W:
  'R4', WA: 'R1', WC: 'R4', WD: 'R4', WF: 'R1', WN: 'R1', WR: 'R2', WS: 'R2', WV: 'R2', YO:
  'R1', ZE: 'R1'
};

export function nrRegion(pc) {
  return AREA_REGION[areaOf(pc)] || '';
}

export function isHomeRegion(pc) {
  const r = nrRegion(pc);
  return r === '' || r === HOME_REGION;   // unknown is not an anomaly, just unknown
}
