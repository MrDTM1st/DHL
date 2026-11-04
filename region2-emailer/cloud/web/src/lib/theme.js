// Light or dark (his ask 04/11: "Can I have a dashboard dark mode"), or whatever this device is set to. The choice is this
// browser's own, so the work PC and a phone can differ. index.html puts it on <html> before the first paint, so a dark
// dashboard never flashes white while it loads; this keeps it there afterwards. theme.css holds the colours.
const KEY = 'r2theme';
export const CHOICES = [['light', 'Light'], ['dark', 'Dark'], ['system', 'Match this device']];
const BAR = { light: '#ffcc00', dark: '#1d1c18' };          // the phone's status bar, the top bar's own colour

const darkDevice = () => (window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null);

export function choice() {
  try {
    const c = localStorage.getItem(KEY);
    return CHOICES.some(([k]) => k === c) ? c : 'light';
  } catch { return 'light'; }
}

export function resolved(c = choice()) {
  if (c !== 'system') return c;
  const m = darkDevice();
  return m && m.matches ? 'dark' : 'light';
}

export function apply(c = choice()) {
  const t = resolved(c);
  document.documentElement.dataset.theme = t;
  const bar = document.querySelector('meta[name="theme-color"]');
  if (bar) bar.setAttribute('content', BAR[t]);
  return t;
}

export function setChoice(c) {
  try { localStorage.setItem(KEY, c); } catch { /* a private window: this visit only */ }
  apply(c);
}

let following = false;
// "Match this device" follows the device when it switches over at night, without a reload
export function follow() {
  const m = darkDevice();
  if (following || !m) return;
  following = true;
  const on = () => { if (choice() === 'system') apply('system'); };
  if (m.addEventListener) m.addEventListener('change', on); else if (m.addListener) m.addListener(on);
}
