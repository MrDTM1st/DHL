import { useState, useEffect } from 'react';
import { isUrgent, within3, ordLabel } from '../lib/orders.js';

// The transient review steps the home agent drives through /api/status state:
//   preview_ready -> single-order Review & send editor
//   batch_ready   -> today's batch, tick which to send
//   sites_needed  -> unknown collection sites, add details then re-process
// plus the persistent panel bits (site-match decisions, holiday handover)
// returned inside status.panel. These are the real workflow — not simulated —
// so they carry the exact command payloads the agent expects.

function priBadges(e) {
  return (
    <>
      {e.loose_ballast && <span className="lbadge">LOOSE BALLAST</span>}
      {within3(e.date || e.delivery_date) && <span className="ubadge">≤3 DAYS</span>}
    </>
  );
}

// ---- single-order Review & send ----
function ReviewSend({ status, currentOrder, onCommand, agentOnline, ttlText }) {
  // Staged emails are a QUEUE, not one email. This showed status.email[0] and
  // the agent sent the whole file, so a seasonal cover request staged behind an
  // ad hoc query and a synergy notice was invisible at index 2, and one click
  // on "Send this email" would have sent all three. Show every one, send the
  // one being looked at, and let the rest be worked through.
  const list = (status.email && status.email.length) ? status.email : [];
  const [pick, setPick] = useState(0);
  const [form, setForm] = useState({ to: '', cc: '', subject: '', message: '' });
  // A fresh run appends, so the newest is last - that is the one just produced.
  useEffect(() => { setPick(Math.max(0, list.length - 1)); /* eslint-disable-next-line */ }, [status.at]);
  useEffect(() => {
    const e = list[pick] || {};
    setForm({ to: e.to || '', cc: e.cc || '', subject: e.subject || '', message: e.message || '' });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status.at, pick]);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const send = () => {
    const others = list.length - 1;
    const q = agentOnline
      ? 'Send this one email to ' + (form.to || '?') + '?'
        + (others > 0 ? '\n\n' + others + ' other staged email(s) stay put.' : '')
      : 'The home PC is OFFLINE so nothing can send right now.\n\nQueue it anyway? It sends if the home PC reconnects within ' + ttlText + ', otherwise it is discarded.';
    if (!window.confirm(q)) return;
    onCommand({ action: 'order_send_edited', order: currentOrder, index: pick, email: form });
  };
  // Take one off the queue without sending it. The only ways out used to be to
  // send it or edit the json by hand, so unwanted drafts stayed for days.
  const discard = () => {
    const e = list[pick] || {};
    if (!window.confirm('Discard this email without sending?'
      + String.fromCharCode(10, 10) + (e.subject || '(no subject)')
      + String.fromCharCode(10) + 'to ' + (e.to || '?')
      + String.fromCharCode(10, 10) + 'It is kept in case you want it back.')) return;
    onCommand({ action: 'discard_pending', index: pick });
  };
  return (
    <div className="card panelcard">
      <div className="ph">Review &amp; send <span className="hint">· edit anything; signature &amp; QR are added automatically</span></div>
      {list.length > 1 && (
        <div style={{ margin: '2px 0 8px' }}>
          <div className="hint" style={{ marginBottom: 4 }}>
            {list.length} emails are staged. Only the one shown is sent.
          </div>
          <select value={pick} onChange={(e) => setPick(Number(e.target.value))}
            style={{ width: '100%', padding: '6px 8px', fontSize: 12.5 }}>
            {list.map((e, i) => (
              <option key={i} value={i}>
                {(i + 1) + '/' + list.length + '  ' + (e.subject || '(no subject)') + '  ->  ' + (e.to || '?')}
              </option>
            ))}
          </select>
        </div>
      )}
      <div className="formcol">
        <input placeholder="To" value={form.to} onChange={set('to')} />
        <input placeholder="Cc (optional)" value={form.cc} onChange={set('cc')} />
        <input placeholder="Subject" value={form.subject} onChange={set('subject')} />
        <textarea rows={13} spellCheck={false} style={{ lineHeight: 1.55, resize: 'vertical' }} value={form.message} onChange={set('message')} />
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button className="btn go" onClick={send}>Send this email</button>
          <button className="btn" title="Discard this one without sending"
            onClick={discard}>&#10005; Discard</button>
          <span className="hint">Discarded emails are kept, not destroyed.</span>
        </div>
      </div>
    </div>
  );
}

// ---- today's batch ----
function BatchPanel({ status, onCommand, agentOnline, ttlText }) {
  const list = status.email || [];
  const [sel, setSel] = useState(() => new Set(list.map((_, i) => i)));
  const [open, setOpen] = useState(new Set());
  useEffect(() => { setSel(new Set(list.map((_, i) => i))); setOpen(new Set()); /* eslint-disable-next-line */ }, [status.at]);
  const rows = list.map((e, i) => ({ e, i })).sort((a, b) => (isUrgent(b.e) - isUrgent(a.e)));
  const toggle = (i) => setSel((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });
  const toggleOpen = (i) => setOpen((s) => { const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n; });
  const send = () => {
    if (!sel.size) { window.alert('Nothing ticked — select at least one email.'); return; }
    const q = agentOnline
      ? 'Send ' + sel.size + ' email' + (sel.size > 1 ? 's' : '') + ' now from your DHL account?'
      : 'The home PC is OFFLINE — nothing can send right now.\n\nQueue it anyway? It sends if the home PC reconnects within ' + ttlText + ', otherwise it is discarded.';
    if (!window.confirm(q)) return;
    onCommand({ action: 'extract_send', sel: [...sel].join(',') });
  };
  return (
    <div className="card panelcard">
      <div className="ph" style={{ justifyContent: 'space-between' }}>
        <span>Today&rsquo;s batch — {list.length === 1 ? '1 email' : list.length + ' emails'} <span className="hint">· tick the ones to send</span></span>
        <span style={{ display: 'flex', gap: 6 }}>
          <button className="btn mini" onClick={() => setSel(new Set(list.map((_, i) => i)))}>All</button>
          <button className="btn mini" onClick={() => setSel(new Set())}>None</button>
          <button className="btn go mini" onClick={send}>Send selected</button>
        </span>
      </div>
      <div>
        {rows.map(({ e, i }) => (
          <div className={'batchrow' + (isUrgent(e) ? ' urgent' : '')} key={i}>
            <input type="checkbox" checked={sel.has(i)} onChange={() => toggle(i)} style={{ width: 16, height: 16 }} />
            <span className="ord">{(e.orders || []).join(' / ')}</span>
            {priBadges(e)}
            <span className="who">{e.to || '(no recipient)'}{e.date ? ' · ' + e.date : ''}{e.materials ? ' · ' + e.materials : ''}</span>
            <button className="btn mini" onClick={() => toggleOpen(i)}>view</button>
            {open.has(i) && <pre className="batchbody">{'Subject: ' + (e.subject || '') + '\n\n' + (e.message || '')}</pre>}
          </div>
        ))}
      </div>
    </div>
  );
}

// ---- unknown collection sites ----
const SITE_FIELDS = [
  ['contact', 'Contact name'], ['postcode', 'Postcode'], ['telephone', 'Telephone'],
  ['email', 'Email'], ['start_hours', 'Start hrs 07:00:00'], ['close_hours', 'Close hrs 17:00:00'],
];
// Unknown collection site. Nearly always a name the extract spells differently
// for a site ALREADY on the template's Supplier Details tab, so the dropdown is
// the whole interaction: pick the real site, done. The six-field form is for a
// genuinely new site and stays hidden until asked for - shown alongside the
// dropdown it read as "fill in this form", which is exactly what it should not
// be. Typing details that are already in the sheet only ever produced a second
// near-duplicate of a site that was there all along.
function SitesPanel({ status, panel, onCommand }) {
  const list = status.email || [];
  const known = (panel || {}).synergy_sites || (status.panel || {}).synergy_sites || [];
  const [vals, setVals] = useState({});
  const [pairs, setPairs] = useState({});
  const [newFor, setNewFor] = useState({});      // which rows opted into the form
  useEffect(() => { setVals({}); setPairs({}); setNewFor({}); }, [status.at]);
  const set = (site, k) => (e) => setVals((v) => ({ ...v, [site]: { ...(v[site] || {}), [k]: e.target.value } }));
  const pair = (site) => (e) => setPairs((p) => ({ ...p, [site]: e.target.value }));
  const label = (k) => {
    const code = typeof k === 'string' ? k : k.code;
    const bits = typeof k === 'string' ? [] : [k.pc, k.town].filter(Boolean);
    return bits.length ? code + ' — ' + bits.join(', ') : code;
  };
  const codeOf = (k) => (typeof k === 'string' ? k : k.code);
  const save = () => {
    const sites = {};
    Object.entries(pairs).forEach(([s, code]) => { if (code) sites[s] = { pair_with: code }; });
    Object.entries(vals).forEach(([s, o]) => {
      if (sites[s]) return;
      const clean = {};
      Object.entries(o).forEach(([k, val]) => { if (val && val.trim()) clean[k] = val.trim(); });
      if (Object.keys(clean).length) sites[s] = clean;
    });
    if (!Object.keys(sites).length) {
      window.alert('Pick the matching site from the dropdown first.');
      return;
    }
    onCommand({ action: 'add_sites', sites });
  };
  return (
    <div className="card panelcard">
      <div className="ph">Unknown collection site{list.length > 1 ? 's' : ''} <span className="hint">· which site is this? pick it and the upload carries on</span></div>
      {!known.length && (
        <div className="hint" style={{ color: 'var(--red)', marginBottom: 8 }}>
          The site list has not loaded from the home PC — reload the page. Without it there is nothing to pick from.
        </div>
      )}
      {list.map((u, i) => {
        const s = (u && u.site) || u; const n = (u && u.count) || 0;
        const picked = pairs[s] || '';
        const showForm = !!newFor[s];
        const me = known.find((k) => codeOf(k) === picked);
        const pc = me && typeof me !== 'string' ? me.pc : '';
        const sibs = pc ? known.filter((k) => typeof k !== 'string' && k.pc === pc && k.code !== picked) : [];
        return (
          <div className="siterow" key={i}>
            <div className="ord" style={{ fontWeight: 700 }}>
              {s}{n ? <span className="hint"> ({n} order{n > 1 ? 's' : ''})</span> : ''}
            </div>
            <select value={picked} onChange={pair(s)}
              style={{ width: '100%', marginTop: 6, padding: '7px 8px', fontSize: 13 }}>
              <option value="">— pick the matching site —</option>
              {known.map((k) => <option key={codeOf(k)} value={codeOf(k)}>{label(k)}</option>)}
            </select>
            {picked && (
              <div className="hint" style={{ marginTop: 6 }}>
                Remembered as <b>{picked}</b> — contact, postcode, phone and loading hours come from the sheet.
                {sibs.length > 0 && (
                  <div style={{ marginTop: 4 }}>
                    Note: {sibs.length + 1} sites share {pc} — {sibs.map((x) => x.code).join(', ')}. Make sure this is the right one.
                  </div>
                )}
              </div>
            )}
            {!picked && !showForm && (
              <div style={{ marginTop: 6 }}>
                <button className="btn" style={{ padding: '3px 9px', fontSize: 12 }}
                  onClick={() => setNewFor((f) => ({ ...f, [s]: true }))}>
                  Not in the list — add it as a new site
                </button>
              </div>
            )}
            {!picked && showForm && (
              <>
                <div className="hint" style={{ margin: '8px 0 4px' }}>
                  New site — these get saved to the store.
                  <button className="btn" style={{ padding: '2px 8px', fontSize: 11, marginLeft: 8 }}
                    onClick={() => setNewFor((f) => ({ ...f, [s]: false }))}>cancel</button>
                </div>
                <div className="sitegrid">
                  {SITE_FIELDS.map(([k, ph]) => (
                    <input key={k} placeholder={ph} onChange={set(s, k)} />
                  ))}
                </div>
                <div style={{ marginTop: 8 }}><input placeholder="Notes (optional)" onChange={set(s, 'notes')} /></div>
              </>
            )}
          </div>
        );
      })}
      <div><button className="btn go" onClick={save}>Save &amp; re-process</button></div>
    </div>
  );
}

// ---- site-match decisions (from panel.decisions) ----
function MatchPanel({ decisions, sites, onCommand }) {
  const [picks, setPicks] = useState({});
  const save = (i) => {
    const d = decisions[i];
    const site = picks[i] || (d.options && d.options[0]) || (sites && sites[0]);
    if (!site) return;
    onCommand({ action: 'site_decision', data: { raw: d.raw, site } });
  };
  return (
    <div className="card panelcard">
      <div className="ph">Delivery site decisions <span className="hint">· no exact Synergy match — pick where each goes</span></div>
      <div className="formcol">
        {decisions.map((d, i) => {
          const opts = (d.options || []).concat((sites || []).filter((s) => !(d.options || []).includes(s)));
          return (
            <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ minWidth: 210 }}>
                <b>{d.raw}</b>{d.context && <span className="hint"> {d.context}</span>}
              </span>
              <select style={{ flex: 1, minWidth: 210 }} value={picks[i] ?? opts[0] ?? ''} onChange={(e) => setPicks((p) => ({ ...p, [i]: e.target.value }))}>
                {opts.map((o) => <option key={o}>{o}</option>)}
              </select>
              <button className="btn go mini" onClick={() => save(i)}>Save</button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---- teams_ready: an internal allocation, so nothing to send ----
// The seasonal route allocates some sites to DHL's own teams (NOC), who are
// spoken to on Teams. There is no email and no Send button on purpose - the
// deliverable is the text, so the panel's whole job is to hand it over
// cleanly. It sits with the other flow panels because it is the same kind of
// moment: the run finished and it wants something from you.
function TeamsPanel({ status }) {
  const blocks = status.email || [];
  const [copied, setCopied] = useState(-1);
  return (
    <div className="card panelcard">
      <div className="ph">Paste into Teams <span className="hint">· internal allocation — no email is sent</span></div>
      {blocks.map((b, i) => (
        <div className="formcol" key={i}>
          <textarea rows={12} spellCheck={false} readOnly
            style={{ lineHeight: 1.55, resize: 'vertical' }}
            value={b.message || ''} />
          <div>
            <button className="btn go" onClick={async () => {
              try { await navigator.clipboard.writeText(b.message || ''); setCopied(i); }
              catch { setCopied(-1); }
            }}>{copied === i ? 'Copied' : 'Copy message'}</button>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function FlowPanels({ status, panel, currentOrder, onCommand, agentOnline, ttlText }) {
  const decisions = (panel && panel.decisions) || [];
  return (
    <>
      {decisions.length > 0 && <MatchPanel decisions={decisions} sites={(panel && panel.sites) || []} onCommand={onCommand} />}
      {status.state === 'teams_ready' && (status.email || []).length > 0 && <TeamsPanel status={status} />}
      {status.state === 'sites_needed' && (status.email || []).length > 0 && <SitesPanel status={status} panel={panel} onCommand={onCommand} />}
      {status.state === 'batch_ready' && (status.email || []).length > 0 && <BatchPanel status={status} onCommand={onCommand} agentOnline={agentOnline} ttlText={ttlText} />}
      {status.state === 'preview_ready' && (status.email || []).length > 0 && <ReviewSend status={status} currentOrder={currentOrder} onCommand={onCommand} agentOnline={agentOnline} ttlText={ttlText} />}
    </>
  );
}
