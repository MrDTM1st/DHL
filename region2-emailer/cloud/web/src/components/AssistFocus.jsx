import { useEffect, useState } from 'react';
import { autoLine } from '../lib/emails.js';

// Deal with it (his 24/11: "if anything needs my attention, like immediately, you will tell me what it is because
// you've read it, and then there will be one button that just says either dealt with or deal with it. The deal with
// it button lets you deal with it."). A tap on a phone alert opens the desk here, on that one email: what Claude read
// in it and the two buttons. What Deal with it will do is said before he taps - send the reply (his to change), file
// it, or hand it to the background Claude, with a line for Claude if he wants one - and then the job shows as it goes:
// what Claude is doing, what it did, and anything it held for his yes (money, cancelling, anyone new), each with
// Yes / No.

const URG = { now: ['Now', 'urgent'], today: ['Today', 'high'], week: ['This week', 'normal'] };
const STATE = {
  queued: 'Waiting for Claude', working: 'Claude is on it', needs_you: 'Needs your yes', done: 'Done',
  failed: "Claude couldn't finish", dropped: 'Dropped',
};

function Job({ job, onYes, onNo, busy }) {
  const open = (job.asks || []).filter((a) => a.state === 'open' || a.state === 'running');
  const queued = (job.asks || []).filter((a) => a.state === 'queued');       // his yes, in the CTMS queue (26/11)
  const closed = (job.asks || []).filter((a) => !['open', 'running', 'queued'].includes(a.state));
  const lines = job.state === 'working' || job.state === 'queued' ? job.log || [] : job.did || [];
  return (
    <div className="af-job">
      <div className={'af-state ' + job.state}><span className="dot" />{STATE[job.state] || job.state}
        {job.state === 'working' && job.now ? <span className="af-now">{job.now}</span> : null}</div>
      {job.summary && <div className="af-summary">{job.summary}</div>}
      {job.state === 'failed' && job.said && <div className="af-said">{job.said}</div>}
      {job.note && <div className="af-said">Your note: {job.note}</div>}
      {lines.length > 0 && (
        <ul className="af-lines">{lines.slice(-6).map((l, k) => <li key={k}>{l}</li>)}</ul>
      )}
      {open.map((a) => (
        <div className="af-ask-row" key={a.n}>
          <div className="what">{a.what}</div>
          {a.kind === 'send' && a.text && <div className="assist-reply">{a.text}</div>}
          {a.kind === 'route' && a.route && <div className="af-said">CTMS: {a.route}</div>}
          {a.said && a.state === 'open' && <div className="af-said">Last try: {a.said}</div>}
          <div className="btns">
            {a.state === 'running' || busy === 'yes' + a.n ? (
              <button className="btn go" disabled>Doing it…</button>
            ) : (
              <>
                <button className="btn go" disabled={!!busy} onClick={() => onYes(a)}>
                  {a.kind === 'send' ? 'Yes, send it' : a.kind === 'route' ? 'Yes, do it' : 'Done it'}</button>
                <button className="btn" disabled={!!busy} onClick={() => onNo(a)}>No</button>
              </>
            )}
          </div>
        </div>
      ))}
      {queued.map((a) => (
        <div className="af-said" key={'q' + a.n}>In the CTMS queue: {a.what} - it runs when CTMS is ready</div>
      ))}
      {closed.map((a) => (
        <div className="af-said" key={'c' + a.n}>
          {a.state === 'done' ? 'Done' : a.state === 'declined' ? 'Left' : "Didn't go"}: {a.what}
          {a.said ? ' - ' + a.said : ''}
        </div>
      ))}
    </div>
  );
}

export default function AssistFocus({ id, assist, loaded, onCommand, onClose }) {
  const needs = (assist && assist.needs) || [];
  const item = needs.find((x) => x.id === id) || null;
  const gone = !item && ((assist && assist.jobs) || []).find((x) => x.id === id);
  const a = (item && item.action) || {};
  // a card of several emails about one order (26/11): Claude takes the lot, each answered on its own thread
  const others = (item && item.lead && item.others) || [];
  const plan = others.length ? {
    kind: 'claude',
    says: `Claude takes on all ${others.length + 1} emails about ${item.about || 'this order'} with your toolkit - `
      + 'each answered on its own thread. Money, cancelling and anyone new to email come back to you as a Yes.',
  } : (item && item.deal) || { kind: 'claude', says: '' };
  const job = (item && item.job) || (gone && gone.job) || null;
  const auto = autoLine(item && item.auto, assist && assist.auto && assist.auto.mode);
  const [text, setText] = useState(a.text || '');
  const [note, setNote] = useState('');
  const [noting, setNoting] = useState(false);
  const [busy, setBusy] = useState('');
  const [went, setWent] = useState('');            // what he pressed, until the home PC's answer shows

  // the panel can arrive after the sheet opened (an alert tapped with the desk closed): the reply text comes with it
  useEffect(() => { if (a.text && !text) setText(a.text); }, [item && item.id]); // eslint-disable-line
  useEffect(() => {
    const k = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [onClose]);
  // a job's state moved on (or the email left the list): the press has been answered
  const jobState = job ? job.state + (job.asks || []).map((x) => x.state).join() : '';
  useEffect(() => { setBusy(''); }, [jobState, !!item]);

  const send = async (action, data, mark) => {
    setBusy(mark);
    const ok = await onCommand({ action, data: { id, ...data } });
    if (!ok) setBusy('');
    else setWent(mark);
  };
  const deal = () => {
    const n = note.trim();
    const edited = plan.kind === 'send' && text.trim() && text !== a.text;
    send('assist_deal', {
      ...(edited ? { text } : {}),
      ...(n ? { note: n } : {}),
      ...(others.length ? { group: true } : {}),
      ctms: plan.kind === 'claude' || !!n,          // the background Claude may need CTMS: Look mum on for it
    }, 'deal');
  };
  const dealt = () => {
    if (others.length && !window.confirm(`Take all ${others.length + 1} emails about ${item.about || 'this order'} `
      + 'off - dealt with?')) return;
    send('assist_dealt', others.length ? { group: true } : {}, 'dealt');
    setTimeout(onClose, 600);
  };
  const yes = (x) => send('assist_yes', { n: x.n, ctms: x.kind === 'route' }, 'yes' + x.n);
  const no = (x) => send('assist_no', { n: x.n }, 'no' + x.n);

  let body;
  if (!loaded) {
    body = <div className="af-meta">Opening the email…</div>;
  } else if (!assist || !assist.mode) {
    body = <div className="af-meta">Waiting for the home PC to send its list…</div>;
  } else if (!item && !gone) {
    body = (
      <>
        <div className="af-ask">{went === 'deal' ? 'Done - it’s off your list.' : 'That one’s off your list.'}</div>
        <div className="af-meta">
          {went === 'deal' ? 'Sent or filed as it said.' : 'Dealt with already - by you, or answered on the thread.'}
        </div>
        <div className="af-btns one"><button className="btn primary" onClick={onClose}>Close</button></div>
      </>
    );
  } else if (gone) {
    body = (
      <>
        <div className="af-from">{gone.from}</div>
        <div className="af-ask">{gone.ask}</div>
        <Job job={gone.job} onYes={yes} onNo={no} busy={busy} />
        <div className="af-btns one"><button className="btn primary" onClick={onClose}>Close</button></div>
      </>
    );
  } else {
    const [label, cls] = URG[item.urgency] || URG.week;
    const live = job && (job.state === 'queued' || job.state === 'working');
    const waiting = job && job.state === 'needs_you';
    const again = job && (job.state === 'failed' || job.state === 'done' || job.state === 'dropped');
    body = (
      <>
        <div className="af-from">
          <span className={'inbox-pri ' + cls}>{label}</span>{item.from}
          <span className="af-when"> · came {item.received} · waiting {item.waited}</span>
        </div>
        <div className="af-ask">{item.ask}</div>
        <div className="af-meta">
          {[item.by_when ? 'by ' + item.by_when : '', item.subject, (item.orders || []).join(', '),
            item.by === 'words' ? 'not read by Claude yet' : ''].filter(Boolean).join(' · ')}
        </div>
        {item.why && <div className="af-why">{item.why}</div>}
        {others.length > 0 && (
          <div className="af-others">
            <b>Also about {item.about || 'this order'} ({others.length})</b>
            {others.map((o) => (
              <div className="af-other" key={o.id}>{o.from} · came {o.received}<span>{o.ask}</span></div>
            ))}
          </div>
        )}
        {auto && <div className={'assist-auto ' + auto.cls}>{auto.text}</div>}
        {a.note && !(auto && auto.cls !== 'held') && <div className="af-why"><b>To do:</b> {a.note}</div>}
        {job && <Job job={job} onYes={yes} onNo={no} busy={busy} />}
        {!live && !waiting && (
          <>
            <div className="af-plan">
              <b>Deal with it</b>
              {noting && note.trim() ? 'Claude takes it on, with your note.' : plan.says}
            </div>
            {plan.kind === 'send' && !(noting && note.trim()) && (
              <textarea className="assist-reply-edit" value={text} onChange={(e) => setText(e.target.value)}
                rows={Math.min(9, Math.max(4, text.split('\n').length + 1))} aria-label="The reply" />
            )}
            {plan.kind === 'send' && !(noting && note.trim()) && item.cc && (
              <div className="af-said">Also to: {item.cc}</div>
            )}
            {noting ? (
              <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} autoFocus
                placeholder="Tell Claude anything it should know or do, e.g. say Thursday works" aria-label="Note for Claude" />
            ) : (
              <button className="af-link" onClick={() => setNoting(true)}>Add a note for Claude</button>
            )}
          </>
        )}
        <div className="af-btns">
          <button className="btn" disabled={!!busy} onClick={dealt}
            title="Done another way (a call, Teams) - it stays off unless they write again">
            {busy === 'dealt' ? 'Taking it off…' : others.length ? `Dealt with all ${others.length + 1}` : 'Dealt with'}</button>
          {live ? (
            <button className="btn red" disabled>{STATE[job.state]}…</button>
          ) : waiting ? (
            <button className="btn" onClick={onClose}>Later</button>
          ) : (
            <button className="btn red" disabled={!!busy || (plan.kind === 'send' && !text.trim() && !note.trim())}
              onClick={deal}>
              {busy === 'deal' ? 'On it…' : again ? 'Deal with it again'
                : others.length ? `Deal with all ${others.length + 1}` : 'Deal with it'}</button>
          )}
        </div>
      </>
    );
  }
  return (
    <div className="af-back" onClick={onClose}>
      <div className="af" role="dialog" aria-modal="true" aria-label="An email that needs you"
        onClick={(e) => e.stopPropagation()}>
        <div className="af-top">
          <div className="kicker">Needs you</div>
          <button className="x" onClick={onClose} aria-label="Close">×</button>
        </div>
        {body}
      </div>
    </div>
  );
}
