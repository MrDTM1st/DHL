// Phone numbers for the one-tap Call buttons.
//
// A tel: link is the whole trick: tapped on a phone it opens the dialler with
// the number already in, and the phone asks you to press call - no web page
// can place a call on its own. A computer has no dialler to open, so there the
// button copies the number instead (see CallButton).

// A UK number: +44 / 0044 / 0, then 9-10 more digits with spaces, dots, dashes
// or brackets between. The same pattern as site_contacts.PHONE_RE on the home PC.
const UK_RE = /(?:\+44\s?\(?0?\)?|0044\s?|0)(?:[\s.\-()]*\d){9,10}/g;

// words that sit in front of a number without being anybody's name
const NOT_NAMES = new Set(['mobile', 'mob', 'tel', 'telephone', 'phone', 'contact', 'contacts', 'site', 'number',
  'no', 'on', 'or', 'and', 'call', 'office', 'landline', 'alt', 'alternative', 'is', 'the', 'manager', 'supervisor']);

// "+44 (0)1632 960 123" / "0044 1632 960123" / "01632-960123" -> "01632960123"
function national(raw) {
  let d = String(raw || '').replace(/\D/g, '');
  if (d.startsWith('0044')) d = d.slice(4);
  else if (/^\s*\+/.test(raw)) d = d.slice(2);
  if (!d.startsWith('0')) d = '0' + d;
  return /^0[1-9]\d{8,9}$/.test(d) ? d : '';
}

// Every distinct UK number in a piece of text, as plain national digits.
export function phonesIn(text) {
  const out = [];
  for (const m of String(text || '').matchAll(UK_RE)) {
    const n = national(m[0]);
    if (n && !out.includes(n)) out.push(n);
  }
  return out;
}

// Who's who in "Sam Example 07700 900123 / Jo Sample 07700 900124": each
// number with the capitalised words just before it. Good enough to label a
// second button "Call Jo"; a number with no name in front gets none.
export function namedPhones(text) {
  const s = String(text || '');
  const out = [];
  let from = 0;
  for (const m of s.matchAll(UK_RE)) {
    const before = s.slice(from, m.index);
    from = m.index + m[0].length;
    const n = national(m[0]);
    if (!n || out.some((x) => x.number === n)) continue;
    const words = (before.match(/[A-Z][A-Za-z'’-]+/g) || []).filter((w) => !NOT_NAMES.has(w.toLowerCase()));
    out.push({ number: n, name: words.slice(-2).join(' ') });
  }
  return out;
}

export const isMobile = (n) => /^07/.test(n);

// +44 rather than 0 so it still dials from a phone that's roaming
export function telHref(n) {
  const d = String(n || '').replace(/\D/g, '');
  return 'tel:' + (d.startsWith('0') ? '+44' + d.slice(1) : d);
}

// 07700 900123 · 020 7946 0123 · 0113 496 0123 · 01632 960123
export function fmtPhone(n) {
  const d = String(n || '').replace(/\D/g, '');
  if (d.length === 10) return d.slice(0, 5) + ' ' + d.slice(5);
  if (d.length !== 11) return String(n || '');
  if (/^02/.test(d)) return `${d.slice(0, 3)} ${d.slice(3, 7)} ${d.slice(7)}`;
  if (/^(011|01\d1|03|08|09)/.test(d)) return `${d.slice(0, 4)} ${d.slice(4, 7)} ${d.slice(7)}`;
  return `${d.slice(0, 5)} ${d.slice(5)}`;
}

// Button words for one or more numbers: "Call" for one; for two, the people's
// first names when they differ, else Mobile / Landline, else Call 1 / Call 2.
export function callLabels(calls) {
  if (calls.length < 2) return calls.map(() => 'Call');
  const firsts = calls.map((c) => (c.name || '').split(' ')[0]);
  if (firsts.every(Boolean) && new Set(firsts).size === firsts.length) return firsts.map((f) => 'Call ' + f);
  const kinds = calls.map((c) => (isMobile(c.number) ? 'Mobile' : 'Landline'));
  if (new Set(kinds).size === kinds.length) return kinds;
  return calls.map((_, i) => 'Call ' + (i + 1));
}

// A touch screen as the main pointer = a phone or tablet, which can dial.
export function canDial() {
  try { return window.matchMedia('(pointer: coarse)').matches; } catch { return false; }
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {   // older browsers, or the clipboard API refused outside a secure page
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  }
}
