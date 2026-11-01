// Thin client over the cloud control plane's REST API (region2-emailer/cloud/
// server.py). Auth is the DASH_KEY typed once at login, sent as the X-Auth
// header on every request and stored in this browser only — exactly the model
// the original inline page used, so the same deployment keeps working.

const KEY_STORE = 'r2key';

export const getKey = () => localStorage.getItem(KEY_STORE) || '';
export const setKey = (k) => localStorage.setItem(KEY_STORE, (k || '').trim());
export const clearKey = () => localStorage.removeItem(KEY_STORE);

// Thrown on 401 so callers can trigger the login screen.
export class AuthError extends Error {
  constructor() { super('auth'); this.name = 'AuthError'; }
}

async function req(path, opts = {}) {
  opts.headers = Object.assign({}, opts.headers || {}, { 'X-Auth': getKey() });
  const r = await fetch(path, opts);
  if (r.status === 401) throw new AuthError();
  return r;
}

async function getJSON(path) {
  const r = await req(path);
  return r.json();
}

// ---- reads ----
export const getStatus   = () => getJSON('/api/status');
export const getTracker  = () => getJSON('/api/tracker');
export const getWaitlist = () => getJSON('/api/waitlist');
export const getFiles    = () => getJSON('/api/files');
export const getFile     = (name) => getJSON('/api/file?name=' + encodeURIComponent(name));

// ---- writes ----
// Enqueue a command for the home PC agent. Body carries whichever of
// {action, order, email, sel, mode, week, sites, data} the action needs.
export async function command(body) {
  await req('/api/command', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// Upload a file (rail-plan CSV / Synergy .xlsx) for the agent to pull and run.
export async function upload(name, dataB64) {
  await req('/api/upload', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, data: dataB64 }),
  });
}

export async function clearDropped() {
  await req('/api/dropped_clear', { method: 'POST' });
}

// Read a File object as base64 (strips the data: prefix), for /api/upload.
export function fileToB64(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(',')[1]);
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}

function saveB64(name, b64) {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([arr]));
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}

// Trigger a browser download of an agent-produced file (from /api/file).
export async function downloadFile(name) {
  const d = await getFile(name);
  saveB64(d.name || name, d.data);
}

// ---- CTMS bridge (the work PC's own channel - see server.py _ctms) ----
// watch=true while the CTMS page is on screen: that is what keeps the work PC
// sending pictures, and it stops by itself ~10s after the page closes.
export const ctmsStatus = (watch) => getJSON('/api/ctms/status' + (watch ? '?watch=1' : ''));
export const ctmsShot = () => getJSON('/api/ctms/shot');

// Unlike command(), this one says when the server turned it down - a refused
// CTMS action has to read as refused, not as a button that did nothing.
export async function ctmsCommand(body) {
  const r = await req('/api/ctms/command', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
  return d;
}

// The map's Upload: an ad hoc's upload CSV into CTMS in one click. The server
// switches Look mum, no hands on for this import only (when it is off) and
// refuses a CSV that went in already - so a second click makes no duplicate.
export async function ctmsImport(name) {
  const r = await req('/api/ctms/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
  return d;
}

// The map's "Check CTMS now": every order on the map looked up in CTMS - booked ones come off, dates follow CTMS,
// a Veh Type filled after a call shows ready. Searches and reads only; the server switches Look mum, no hands on
// for this look-up alone when it is off.
export async function ctmsCheck() {
  const r = await req('/api/ctms/check', { method: 'POST' });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
  return d;
}

// The CTMS to-do's Run (his ask 01/11: "turn execute CTMS into a button"): the ready items typed into CTMS by the
// home PC one at a time, each read back. Look mum, no hands is switched on for the run, back as it was after.
export async function ctmsTodoRun(ids) {
  const r = await req('/api/ctms/todo/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
  return d;
}

// The Rail plan card's Export from CTMS (his "where is the execute rail plan button on the dashboard", 01/11): the
// week's Short Rail Report exported by the home PC driving CTMS, and the plan previewed from it into Files - nothing
// is sent. Look mum, no hands is switched on for the run, back as it was after.
export async function ctmsRail(week) {
  const r = await req('/api/ctms/rail', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ week }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
  return d;
}

// The brief's Send in Teams for DHL NOC (his ask 01/11): the message sent in the work PC's Teams, to someone on the
// home PC's NOC list only. Look mum, no hands is switched on for this one message when it is off.
export async function ctmsTeams(email, text, dry = false) {
  const r = await req('/api/ctms/teams', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, text, dry }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
  return d;
}

// His pick for one of a held item's doubts, from its drop-down - the home PC keeps it on the item.
export async function ctmsTodoAnswer(id, field, value) {
  const r = await req('/api/ctms/todo/answer', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, field, value }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
  return d;
}

export async function ctmsStop() {
  await req('/api/ctms/stop', { method: 'POST' });
}

// "Set up this PC": the work PC's whole setup as one file to double-click,
// made for THIS dashboard (the bridge's own key is inside it), so nothing is
// typed on the work PC. Fetched with the login key, then handed to the browser.
export async function downloadCtmsSetup(allow, autostart) {
  const q = new URLSearchParams({ allow: allow ? '1' : '0', autostart: autostart ? '1' : '0',
    desk: window.location.origin });
  const r = await req('/api/ctms/setup?' + q.toString());
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d.error || 'HTTP ' + r.status);
  }
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement('a');
  a.href = url; a.download = 'CTMS bridge setup.cmd';
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// "Look mum, no hands" - on for a set number of minutes, or off. Only the
// dashboard's own key can do this; the home PC's cannot.
export async function ctmsControl(on, minutes) {
  const r = await req('/api/ctms/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ on, minutes }),
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.error || 'HTTP ' + r.status);
  return d;
}
