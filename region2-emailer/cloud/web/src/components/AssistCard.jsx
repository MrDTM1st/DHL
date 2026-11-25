import { useState } from 'react';
import { copyText } from '../lib/phone.js';
import PushToggle from './PushToggle.jsx';

// Needs you (inbox_assist.py, 23/11 - his "something like you to sit in my inbox and to notify me when things need to
// be actioned right at that moment"): every email in the Inbox is either filed (it needs nothing from him), left for
// the desk (the toolkit takes it in), or put here with who wants what, by when, and the suggested action with the
// text ready. Claude reads each one once on the home PC; until it can, the word rules decide. "Now" rings at once.
// Shadow mode lists what it would file and moves nothing; live files it, logged, and Put back undoes one.
// Each email has his two buttons (24/11): Dealt with, and Deal with it - which opens the email (AssistFocus, as a
// phone alert does) saying what it will do, and then shows Claude's job as it goes.

const URG = { now: ['Now', 'urgent'], today: ['Today', 'high'], week: ['This week', 'normal'] };
const ACT = { reply: 'Reply', forward: 'Forward', ctms: 'In CTMS', call: 'Call', upload: 'Upload', file: 'File',
  other: 'To do' };
const MODE = { off: 'Off', shadow: 'Shadow', live: 'Live' };

// a job he gave Claude (Deal with it, 24/11), in a line
const JOB = { queued: 'Claude will start in a moment', working: 'Claude is on it', needs_you: 'Needs your yes',
  done: 'Claude dealt with it', failed: "Claude couldn't finish", dropped: 'Dropped' };

function jobLine(j) {
  if (!j) return '';
  const open = (j.asks || []).filter((a) => a.state === 'open');
  if (j.state === 'working') return JOB.working + (j.now ? ': ' + j.now : '');
  if (j.state === 'needs_you') return JOB.needs_you + (open.length ? ': ' + open[0].what : '');
  if (j.state === 'failed') return JOB.failed + (j.summary || j.said ? ': ' + (j.summary || j.said) : '');
  return (JOB[j.state] || j.state) + (j.summary ? ': ' + j.summary : '');
}

function Item({ i, onDealt, onOpen }) {
  const [show, setShow] = useState(false);
  const [copied, setCopied] = useState(false);
  const a = i.action || {};
  const j = i.job;
  const [label, cls] = URG[i.urgency] || URG.week;
  const copy = () => copyText(a.text || '').then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); });
  return (
    <div className="noaddress-row">
      <div className="noaddress-what">
        <div className="noaddress-order">
          <span className={'inbox-pri ' + cls}>{label}</span>
          {i.from}
          <span className={'noaddress-when' + (i.alarm ? ' soon' : '')}>waiting {i.waited}</span>
        </div>
        <div className="noaddress-site"><b>{i.ask}</b></div>
        <div className="noaddress-said">
          {[i.by_when ? 'by ' + i.by_when : '', i.subject, 'came ' + i.received,
            i.by === 'words' ? 'not read by Claude yet' : ''].filter(Boolean).join(' · ')}
        </div>
        {(a.type && a.type !== 'other') || a.note ? (
          <div className="noaddress-said">
            <b>{ACT[a.type] || 'To do'}{a.to ? ' to ' + a.to : ''}</b>{a.note ? ': ' + a.note : ''}
          </div>
        ) : null}
        {j && <div className={'assist-job ' + j.state}>{jobLine(j)}</div>}
        {show && a.text && <div className="assist-reply">{a.text}</div>}
      </div>
      <div className="noaddress-fix">
        {a.text && (
          <button className="btn mini" onClick={() => setShow((s) => !s)}>
            {show ? 'Hide' : a.type === 'forward' ? 'Suggested note' : 'Suggested reply'}</button>
        )}
        {a.text && show && <button className="btn mini" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>}
        <button className="btn mini" onClick={() => onDealt(i)}
          title="Answered or done another way - it stays off unless they write again">Dealt with</button>
        {/* his 24/11: "one button that just says either dealt with or deal with it" - it opens the email with what it
            will do said first, and the job as it goes */}
        <button className={'btn mini ' + (j && j.state === 'needs_you' ? 'red' : 'go')} onClick={() => onOpen(i.id)}>
          {j && j.state === 'needs_you' ? 'Your yes' : j && (j.state === 'working' || j.state === 'queued')
            ? 'Watch' : 'Deal with it'}</button>
      </div>
    </div>
  );
}

// full: on the Emails page (25/11) - every email that needs him, grouped Now / Today / This week, nothing folded away
export default function AssistCard({ data, onCommand, push, onOpen, full }) {
  const [gone, setGone] = useState({});
  const [allNeeds, setAllNeeds] = useState(false);
  const [openFile, setOpenFile] = useState(false);
  const [openJobs, setOpenJobs] = useState(false);
  if (!data || !data.mode) return null;
  const mode = data.mode;
  const send = (action, d) => onCommand({ action, data: d || {} });
  const hide = (id) => setGone((g) => ({ ...g, [id]: true }));
  const setMode = (m) => {
    if (m === mode) return;
    if (m === 'live' && !window.confirm('Live: the assistant files the emails it is sure need nothing from you. '
      + 'Every move is logged, and Put back undoes one. Go live?')) return;
    send('assist_mode', { mode: m });
  };
  const modes = (
    <span className="assist-modes">
      {Object.keys(MODE).map((m) => (
        <button key={m} className={'btn mini' + (m === mode ? ' go' : '')} onClick={() => setMode(m)}>{MODE[m]}</button>
      ))}
    </span>
  );
  if (mode === 'off') {
    return (
      <div className="card inbox-card quiet">
        <div className="noaddress-head">
          <h3>Inbox assistant is off</h3>
          <span className="noaddress-why">Turn it on to sort the Inbox and put what needs you here. {modes}</span>
        </div>
      </div>
    );
  }
  const needs = (data.needs || []).filter((i) => !gone[i.id]);
  const pressing = needs.filter((i) => i.urgency !== 'week' || i.alarm);
  const shown = full || allNeeds ? needs : pressing.length ? pressing : needs.slice(0, 3);
  const claude = data.claude || {};
  const filing = mode === 'live' ? (data.filed || []) : (data.would_file || []);
  const files = filing.filter((i) => !gone[i.id]);
  const dealt = (i) => { send('assist_dealt', { id: i.id }); hide(i.id); };
  const open = (id) => onOpen && onOpen(id);
  const jobs = data.jobs || [];
  const fileAll = () => {
    if (window.confirm(`File ${files.length} email${files.length === 1 ? '' : 's'} where they belong? `
      + 'Every move is logged, and Put back undoes one.')) {
      send('assist_fileall');
      files.forEach((i) => hide(i.id));
    }
  };
  return (
    <div className={'card noaddress inbox-card' + (needs.some((i) => i.alarm) ? '' : ' calm')}>
      <div className="noaddress-head">
        <h3>{needs.length ? `${needs.length} email${needs.length === 1 ? '' : 's'} need${needs.length === 1 ? 's' : ''} you`
          + (data.now ? ` · ${data.now} now` : '') : 'Nothing in the Inbox needs you'}</h3>
        <span className="noaddress-why">
          Read {data.at || 'not yet'}{data.pending ? ` · Claude still to read ${data.pending}` : ''}. {modes}
          <span className="assist-modes"><PushToggle compact push={push} onCommand={onCommand} /></span>
        </span>
      </div>
      {claude.ok === false && (
        <div className="noaddress-row">
          <div className="noaddress-what">
            <div className="noaddress-said">
              <b>Claude can't read your mail yet:</b> {claude.said || 'no answer'}. If it says to log in: on the
              home PC open PowerShell, run <code>{'& "$env:USERPROFILE\\.local\\bin\\claude.exe" auth login --claudeai'}</code>
              {' '}and press Authorize in the browser it opens. Until then the word rules decide, and nothing is
              filed on their say-so.
            </div>
          </div>
        </div>
      )}
      {full ? Object.keys(URG).map((u) => {
        const group = needs.filter((i) => (URG[i.urgency] ? i.urgency : 'week') === u);
        return group.length ? [
          <div className="noaddress-row assist-group" key={'g' + u}>
            <div className="noaddress-what"><div className="noaddress-order">{URG[u][0]} · {group.length}</div></div>
          </div>,
          ...group.map((i) => <Item key={i.id} i={i} onDealt={dealt} onOpen={open} />),
        ] : null;
      }) : shown.map((i) => <Item key={i.id} i={i} onDealt={dealt} onOpen={open} />)}
      {!full && needs.length > shown.length && (
        <div className="noaddress-row">
          <button className="btn mini" onClick={() => setAllNeeds(true)}>Show all {needs.length}</button>
        </div>
      )}
      {!full && allNeeds && needs.length > 3 && (
        <div className="noaddress-row">
          <button className="btn mini" onClick={() => setAllNeeds(false)}>Show fewer</button>
        </div>
      )}
      {jobs.length > 0 && (
        <div className="noaddress-row">
          <div className="noaddress-what">
            <div className="noaddress-order">Claude dealt with today: {jobs.length}</div>
          </div>
          <div className="noaddress-fix">
            <button className="btn mini" onClick={() => setOpenJobs((o) => !o)}>{openJobs ? 'Hide' : 'Show'}</button>
          </div>
        </div>
      )}
      {openJobs && jobs.map((x) => (
        <div className="noaddress-row assist-file" key={'j' + x.id}>
          <div className="noaddress-what">
            <div className="noaddress-said"><b>{x.from}</b> · {x.ask}</div>
            <div className={'assist-job ' + ((x.job && x.job.state) || '')}>{jobLine(x.job)}</div>
          </div>
          <div className="noaddress-fix">
            <button className="btn mini" onClick={() => open(x.id)}>Open</button>
          </div>
        </div>
      ))}
      {files.length > 0 && (
        <div className="noaddress-row">
          <div className="noaddress-what">
            <div className="noaddress-order">
              {mode === 'live' ? `Filed for you today: ${files.length}`
                : `I'd file ${files.length} (shadow mode: nothing moved)`}
            </div>
          </div>
          <div className="noaddress-fix">
            <button className="btn mini" onClick={() => setOpenFile((o) => !o)}>{openFile ? 'Hide' : 'Show'}</button>
            {mode === 'shadow' && <button className="btn mini go" onClick={fileAll}>File all</button>}
          </div>
        </div>
      )}
      {openFile && files.map((i) => (
        <div className="noaddress-row assist-file" key={'f' + i.id}>
          <div className="noaddress-what">
            <div className="noaddress-said">
              <b>{i.from}</b> · {i.subject} → {i.filed_to || i.dest} · {i.why}
            </div>
          </div>
          <div className="noaddress-fix">
            {mode === 'live' ? (
              <button className="btn mini" onClick={() => { send('assist_putback', { id: i.id }); hide(i.id); }}
                title="Back into the Inbox - the assistant never files it again">Put back</button>
            ) : (
              <>
                <button className="btn mini" onClick={() => { send('assist_file', { id: i.id }); hide(i.id); }}>File</button>
                <button className="btn mini" onClick={() => { send('assist_keep', { id: i.id }); hide(i.id); }}
                  title="Not noise - it stays in the Inbox and is never filed by the assistant">Keep</button>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
