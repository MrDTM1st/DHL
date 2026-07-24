import { useState, useEffect, useRef, useCallback } from 'react';
import TopNav from './components/TopNav.jsx';
import Toasts from './components/Toasts.jsx';
import Drawer from './components/Drawer.jsx';
import NotifPop from './components/NotifPop.jsx';
import Login from './components/Login.jsx';
import Dashboard from './pages/Dashboard.jsx';
import MapPage from './pages/MapPage.jsx';
import TrackerPage from './pages/TrackerPage.jsx';
import Notifications from './pages/Notifications.jsx';
import { useStatus, useTracker } from './hooks.js';
import { isUrgent, within3, ordLabel, dueText } from './lib/orders.js';
import * as api from './api.js';

function ago(ms) {
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 60) return 'just now';
  if (s < 3600) return Math.floor(s / 60) + ' min ago';
  if (s < 86400) return Math.floor(s / 3600) + ' h ago';
  return Math.floor(s / 86400) + ' d ago';
}

let _tid = 0;

export default function App() {
  const [authed, setAuthed] = useState(!!api.getKey());
  const onAuthFail = useCallback(() => { api.clearKey(); setAuthed(false); }, []);

  const [page, setPage] = useState('dash');
  const [bellOpen, setBellOpen] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const [pickedHaulier, setPickedHaulier] = useState(null);
  const [currentOrder, setCurrentOrder] = useState('');
  const [toasts, setToasts] = useState([]);
  const [uploadBusy, setUploadBusy] = useState(false);

  // notifications derived from urgent orders (persisted read/dismiss in state)
  const [notes, setNotes] = useState([]);
  const knownUrgent = useRef(new Set());
  const bootstrapped = useRef(false);
  const lastStatusAt = useRef(null);

  const { status, refreshStatus } = useStatus(authed ? onAuthFail : null);
  const { records, refreshTracker } = useTracker(authed ? onAuthFail : null);

  const panel = (status && status.panel) || {};
  const hauliers = panel.hauliers || [];
  // recently processed ad hoc forms - shown on the map beside the tracked
  // orders, but never in the tracker (they're not emailed orders)
  const adhocs = panel.adhocs || [];
  const mapRecords = records.concat(adhocs);
  const agentOnline = !!(status && status.agent_online);
  const ttlText = status && status.queue_ttl
    ? (status.queue_ttl >= 60 ? Math.floor(status.queue_ttl / 60) + ' minutes' : status.queue_ttl + ' seconds')
    : '10 minutes';
  const agentText = 'Home PC ' + (agentOnline ? 'online' : 'offline');

  // ---- toasts ----
  const pushToast = useCallback((title, msg, kind) => {
    const id = 't' + (++_tid);
    setToasts((ts) => [...ts, { id, title, msg, kind }]);
    setTimeout(() => setToasts((ts) => ts.map((t) => t.id === id ? { ...t, out: true } : t)), 4200);
    setTimeout(() => setToasts((ts) => ts.filter((t) => t.id !== id)), 4600);
  }, []);
  const dismissToast = (id) => setToasts((ts) => ts.filter((t) => t.id !== id));

  // ---- derive notifications when orders enter the <=3-day window ----
  useEffect(() => {
    if (!records) return;
    const urgent = records.filter(isUrgent);
    const fresh = [];
    urgent.forEach((r) => {
      if (knownUrgent.current.has(r.id)) return;
      knownUrgent.current.add(r.id);
      fresh.push(r);
    });
    if (!fresh.length) return;
    const created = Date.now();
    const newNotes = fresh.map((r) => ({
      id: 'u-' + r.id,
      kind: 'urgent',
      title: (r.worksite || r.site || ordLabel(r)) + ': ' + dueText(r),
      msg: ordLabel(r) + ' is inside the 3-day window. Book a haulier.',
      createdAt: created,
      read: false,
      orderId: r.id,
    }));
    setNotes((ns) => {
      const have = new Set(ns.map((n) => n.id));
      return [...newNotes.filter((n) => !have.has(n.id)), ...ns];
    });
    // Don't toast the initial backlog on first load — only genuinely new ones.
    if (bootstrapped.current) {
      fresh.forEach((r) => pushToast('Urgent order', ordLabel(r) + ', ' + (r.worksite || r.site || '') + ' is ' + dueText(r) + '.'));
    }
    bootstrapped.current = true;
  }, [records, pushToast]);

  // ---- a freshly processed ad hoc takes you straight to the map ----
  // The first panel we see is the baseline (old ad hocs shouldn't hijack the
  // screen on page load); anything appearing AFTER that is a form you just
  // uploaded, so jump to the map with the job framed and the brief open.
  const knownAdhocs = useRef(null);
  const adhocSig = adhocs.map((a) => a.id).join(',');
  useEffect(() => {
    if (!status) return;
    const ids = adhocs.map((a) => a.id);
    if (knownAdhocs.current === null) { knownAdhocs.current = new Set(ids); return; }
    const fresh = ids.find((id) => !knownAdhocs.current.has(id));
    ids.forEach((id) => knownAdhocs.current.add(id));
    if (fresh) {
      pushToast('Ad hoc processed', 'CSV is in Files — here\'s the job on the map.', 'go');
      setSelectedId(fresh);
      setPickedHaulier(null);
      setPage('map');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adhocSig, status === null]);

  // ---- toast on command completion / expiry ----
  useEffect(() => {
    if (!status) return;
    if (lastStatusAt.current === null) { lastStatusAt.current = status.at; return; }
    if (status.at && status.at !== lastStatusAt.current) {
      lastStatusAt.current = status.at;
      if (status.state === 'done') pushToast('Done', status.detail || '', 'go');
      else if (status.state === 'error') pushToast('Action failed', status.detail || '', 'warn');
    }
  }, [status, pushToast]);

  const unread = notes.filter((n) => !n.read).length;

  // ---- command / upload plumbing ----
  const onCommand = useCallback(async (body) => {
    try {
      await api.command(body);
      setTimeout(refreshStatus, 250);
    } catch (e) {
      if (e instanceof api.AuthError) onAuthFail();
    }
  }, [refreshStatus, onAuthFail]);

  const onUpload = useCallback(async (file) => {
    if (!file) return;
    setUploadBusy(true);
    try {
      const b64 = await api.fileToB64(file);
      await api.upload(file.name, b64);
    } catch (e) {
      if (e instanceof api.AuthError) onAuthFail();
      else pushToast('Upload failed', String(e && e.message || e), 'warn');
    } finally {
      setUploadBusy(false);
    }
  }, [onAuthFail, pushToast]);

  const onClearDropped = useCallback(async () => {
    try { await api.clearDropped(); refreshStatus(); } catch { /* ignore */ }
  }, [refreshStatus]);

  const onLearn = useCallback((id, field, value) => {
    onCommand({ action: 'learn_detail', id, field, value });
    setTimeout(refreshTracker, 1800);
  }, [onCommand, refreshTracker]);

  const onBookedCall = useCallback((r) => {
    if (!window.confirm('Mark ' + ordLabel(r) + ' as booked over the phone and remove it from the tracker?')) return;
    onCommand({ action: 'booked_call', order: r.id });
    setSelectedId(null);
    setTimeout(refreshTracker, 2500);
  }, [onCommand, refreshTracker]);

  const onCall = useCallback((h) => {
    pushToast('Calling ' + h.name, (h.phone || '') + ' — opening in your dialler…');
  }, [pushToast]);

  // ---- notifications actions ----
  const openNote = (n) => {
    setNotes((ns) => ns.map((x) => x.id === n.id ? { ...x, read: true } : x));
    setBellOpen(false);
    if (n.orderId) { setPage('tracker'); setTimeout(() => setSelectedId(n.orderId), 120); }
  };
  const markAll = () => setNotes((ns) => ns.map((n) => ({ ...n, read: true })));
  const clearAll = () => setNotes([]);
  const dismissNote = (id) => setNotes((ns) => ns.filter((n) => n.id !== id));

  // Opening a brief ALWAYS lands you on the map with that job framed - the
  // brief and the place it's going are the same question, so viewing one
  // without the other is half an answer. Works from the tracker too.
  // The picked haulier lives here because both the brief and the map need it:
  // it re-times the job from that haulier's base and draws their approach leg.
  const selectOrder = (o) => { setSelectedId(o.id); setPickedHaulier(null); setPage('map'); };
  const selectedRecord = mapRecords.find((r) => r.id === selectedId);
  // a selected record can vanish on refresh (booked orders drop off, old ad
  // hocs rotate out) - clear the selection or the map stays focused on nothing
  useEffect(() => {
    if (selectedId && records.length + adhocs.length > 0 && !selectedRecord) {
      setSelectedId(null); setPickedHaulier(null);
    }
  }, [selectedId, selectedRecord, records.length, adhocs.length]);

  // decorate notes with a display time + older flag at render
  const shownNotes = notes.map((n) => ({ ...n, time: ago(n.createdAt), older: (Date.now() - n.createdAt) > 4 * 3600 * 1000 }));

  if (!authed) {
    return <Login onUnlock={(k) => { api.setKey(k); setAuthed(true); bootstrapped.current = false; knownUrgent.current = new Set(); }} />;
  }

  return (
    <div className="app" onClick={() => bellOpen && setBellOpen(false)}>
      <TopNav
        page={page}
        setPage={(p) => { setPage(p); setBellOpen(false); }}
        unread={unread}
        agentOnline={agentOnline}
        agentText={agentText}
        bellOpen={bellOpen}
        onBell={(e) => { e.stopPropagation(); setBellOpen((v) => !v); }}
      />
      {bellOpen && (
        <NotifPop notes={shownNotes} onOpen={openNote} markAll={markAll}
          seeAll={() => { setPage('notifications'); setBellOpen(false); }} />
      )}
      <div className="body">
        {page === 'dash' && (
          <Dashboard
            records={records} status={status} panel={panel} setPage={setPage}
            onCommand={onCommand} onUpload={onUpload} currentOrder={currentOrder} setCurrentOrder={setCurrentOrder}
            agentOnline={agentOnline} ttlText={ttlText} onClearDropped={onClearDropped} uploadBusy={uploadBusy}
          />
        )}
        {page === 'map' && (
          <MapPage records={mapRecords} hauliers={hauliers} onSelect={selectOrder} selectedId={selectedId}
            pickedHaulier={pickedHaulier} />
        )}
        {page === 'tracker' && (
          <TrackerPage records={records} onSelect={selectOrder} onCommand={onCommand} onLearn={onLearn}
            onBookedCall={onBookedCall} autoChase={!!(panel && panel.auto_chase)} />
        )}
        {page === 'notifications' && (
          <Notifications notes={shownNotes} onOpen={openNote} onDismiss={dismissNote} markAll={markAll} clearAll={clearAll} />
        )}
        {selectedRecord && (
          <Drawer record={selectedRecord} hauliers={hauliers}
            onClose={() => { setSelectedId(null); setPickedHaulier(null); }}
            onCall={onCall} onBookedCall={onBookedCall} onCommand={onCommand}
            pickedHaulier={pickedHaulier} onPickHaulier={setPickedHaulier} />
        )}
      </div>
      <Toasts toasts={toasts} dismiss={dismissToast} />
    </div>
  );
}
