import { useState, useEffect } from 'react';
import { dateShort, stamp, nrOpen } from '../lib/orders.js';

// The Network Rail team email when a site asks for another day than we offered (his rule 09/11, nr_date.py):
// an EARLIER day waits for the team's yes (is it allowed, will the stock be ready) - the order stays put till then;
// a day in a LATER week is moved, and the team is told so nobody chases the old day. The email is written for him:
// he reads it, can change it, and it goes when he presses Send (the site's email is forwarded underneath it).
function headline(r, n) {
  const team = n.team || 'Network Rail';
  const was = dateShort(n.offered), asked = dateShort(n.asked);
  if (n.kind === 'earlier') {
    if (n.state === 'to_send') return `The site asked for ${asked}, earlier than the ${was} we offered. Ask ${team} if it's allowed and the stock will be ready - the order stays on ${was} until they say yes.`;
    if (n.state === 'sent') return `Asked ${team} ${stamp(n.sent_at)} about ${asked} - waiting for their answer. The order stays on ${was}.`;
    if (n.state === 'allowed') return `${team} said yes - moved to ${asked}.`;
    if (n.state === 'not_allowed') return `${team} said no - it stays on ${was}. Let the site know.`;
    if (n.state === 'dismissed') return `No Network Rail email (your call) - moved to ${asked}.`;
  } else {
    if (n.state === 'to_send') return `Moved to ${asked} from ${was} (a later week). Let ${team} know so nobody chases the ${was} delivery.`;
    if (n.state === 'sent') return `Told ${team} ${stamp(n.sent_at)} it now delivers on ${asked}.`;
    if (n.state === 'dismissed') return `No Network Rail email (your call).`;
  }
  return '';
}

export default function NrDateBox({ r, onCommand, compact = false }) {
  const n = r.nr_date || null;
  const [open, setOpen] = useState(false);
  const fresh = () => ({ to: (n && n.to) || '', cc: (n && n.cc) || '', subject: (n && n.subject) || '',
    message: (n && n.message) || '' });
  const [draft, setDraft] = useState(fresh);
  useEffect(() => { setDraft(fresh()); setOpen(false); }, [r.id, n && n.state, n && n.at]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!n || !headline(r, n)) return null;
  if (compact && !nrOpen(r)) return null;
  const say = (data) => onCommand && onCommand({ action: 'nr_date', data: { rid: r.id, ...data } });
  const edit = (k) => (e) => setDraft((d) => ({ ...d, [k]: e.target.value }));
  const send = () => {
    if (!draft.to.trim() || !draft.message.trim()) return;
    say({ do: 'send', ...draft });
    setOpen(false);
  };
  const answer = (yes) => {
    const q = yes ? `Network Rail said YES: move ${(r.orders || []).join(' / ')} to ${n.asked}?`
      : `Network Rail said NO: keep ${(r.orders || []).join(' / ')} on ${n.offered}?`;
    if (window.confirm(q)) say({ do: yes ? 'yes' : 'no' });
  };
  const dismiss = () => {
    const q = n.kind === 'earlier'
      ? `No email to Network Rail? The order moves to ${n.asked} without their OK.`
      : 'No email to Network Rail about this move?';
    if (window.confirm(q)) say({ do: 'dismiss' });
  };
  const waiting = nrOpen(r);
  return (
    <div className={'nrdate' + (waiting ? ' open' : '')}>
      <div className="nrdate-h">
        <span className="nrdate-tag">{n.kind === 'earlier' ? 'Earlier day asked' : 'Later week'}</span>
        <span className="nrdate-said">{headline(r, n)}</span>
      </div>
      {n.state === 'to_send' && (
        <div className="nrdate-acts">
          <button className={'btn mini' + (open ? ' red' : ' go')} onClick={() => setOpen((v) => !v)}>
            {open ? 'Close' : 'Email ' + (n.team || 'Network Rail')}
          </button>
          <button className="btn mini" onClick={dismiss}>No email needed</button>
        </div>
      )}
      {n.state === 'sent' && n.kind === 'earlier' && (
        <div className="nrdate-acts">
          <button className="btn mini go" onClick={() => answer(true)}>They said yes - move to {dateShort(n.asked)}</button>
          <button className="btn mini" onClick={() => answer(false)}>They said no - keep {dateShort(n.offered)}</button>
        </div>
      )}
      {open && (
        <div className="hcompose">
          {!n.to && (
            <div className="nrdate-who">No Network Rail team is known for this material. Who does it go to? Type their address below.</div>
          )}
          <label>To<input value={draft.to} onChange={edit('to')} placeholder="The Network Rail team's address" /></label>
          <label>Cc<input value={draft.cc} onChange={edit('cc')} /></label>
          <label>Subject<input value={draft.subject} onChange={edit('subject')} /></label>
          <label>Message<textarea rows={10} value={draft.message} onChange={edit('message')} /></label>
          <div className="hcompose-foot">
            <span className="hint-sig">
              {n.reply_eid ? "the site's email (the whole trail) goes underneath; signature & QR are added"
                : 'signature & QR are added automatically'}
            </span>
            <button className="btn mini" onClick={() => setOpen(false)}>Cancel</button>
            <button className="btn mini red" disabled={!draft.to.trim() || !draft.message.trim()} onClick={send}>Send</button>
          </div>
        </div>
      )}
    </div>
  );
}

// The Dashboard's card: every order with a Network Rail date email still to send, or an earlier day still waiting
// on their answer - so he can see what went and what is held.
export function NrDateCard({ records, onCommand }) {
  const rows = (records || []).filter(nrOpen);
  if (!rows.length) return null;
  return (
    <div className="card noaddress nrcard">
      <div className="noaddress-head">
        <h3>Network Rail: {rows.length === 1 ? '1 date change' : rows.length + ' date changes'}</h3>
        <span className="noaddress-why">A site asked for another day than we offered. Earlier days wait for Network Rail&rsquo;s yes; later weeks they are told about.</span>
      </div>
      {rows.map((r) => (
        <div className="noaddress-row" key={r.id}>
          <div className="noaddress-what">
            <div className="noaddress-order">
              {(r.orders || []).join(' / ')}
              <span className="noaddress-when">{[r.worksite || r.site, r.postcode].filter(Boolean).join(' ')}</span>
            </div>
            <NrDateBox r={r} onCommand={onCommand} compact />
          </div>
        </div>
      ))}
    </div>
  );
}
