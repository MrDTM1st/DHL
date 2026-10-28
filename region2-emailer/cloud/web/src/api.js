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

// "Claude can act" - on for a set number of minutes, or off. Only the
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

export async function downloadCtmsCapture(name) {
  const d = await getJSON('/api/ctms/capture?name=' + encodeURIComponent(name));
  if (!d.data) throw new Error('gone');
  saveB64(name, d.data);
}
