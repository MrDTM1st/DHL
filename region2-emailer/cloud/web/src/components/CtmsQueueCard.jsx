import { useState } from 'react';

// The CTMS job queue (ctms_queue.py on the home PC, his 26/11 "Yes, build it" - the faster CTMS): CTMS jobs wait their
// turn and run one after another by themselves while CTMS is ready ("Claude can act" on, CTMS open, nothing else
// running), each checked by its own route, while email carries on. A stop ends its job there and is never tried again
// by itself: Again (after a look) runs it from the step that stopped. A job still waiting can be taken off.

const STATE = { running: 'Running', queued: 'Waiting', done: 'Done', stopped: 'Stopped', dropped: 'Taken off' };

function when(stamp) {
  const s = String(stamp || '');
  return s ? s.slice(8, 10) + '/' + s.slice(5, 7) + ' ' + s.slice(11, 16) : '';
}

export default function CtmsQueueCard({ data, onCommand }) {
  const [gone, setGone] = useState({});
  const [all, setAll] = useState(false);
  if (!data || !data.jobs || !data.jobs.length) return null;
  const jobs = data.jobs.filter((j) => !gone[j.id + j.state]);
  const live = jobs.filter((j) => ['running', 'queued', 'stopped'].includes(j.state));
  const shown = all ? jobs : live.length ? live : jobs.slice(0, 3);
  const send = (j, todo) => {
    onCommand({ action: 'ctms_queue', data: { do: todo, id: j.id } });
    setGone((g) => ({ ...g, [j.id + j.state]: true }));
  };
  return (
    <div className={'card noaddress ctms-queue' + (jobs.some((j) => j.state === 'stopped') ? '' : ' calm')}>
      <div className="noaddress-head">
        <h3>CTMS jobs{data.waiting ? ` · ${data.waiting} waiting` : ''}</h3>
        <span className="noaddress-why">
          {data.paused && data.waiting ? `Waiting: ${data.paused}. Tried ${when(data.checked_at)}.`
            : 'One after another while CTMS is ready - your email carries on meanwhile.'}
        </span>
      </div>
      {shown.map((j) => (
        <div className="noaddress-row" key={j.id}>
          <div className="noaddress-what">
            <div className="noaddress-order">
              <span className={'ctmsq-state ' + j.state}>{STATE[j.state] || j.state}</span>
              {j.what}
            </div>
            <div className="noaddress-said">
              {[j.said, j.steps > 1 ? `step ${Math.min(j.step + (j.state === 'done' ? 0 : 1), j.steps)} of ${j.steps}` : '',
                j.seconds ? `${Math.round(j.seconds)}s in CTMS` : '', j.by ? 'from ' + j.by : '',
                when(j.ended_at || j.started_at || j.queued_at)].filter(Boolean).join(' · ')}
            </div>
            {(j.notices || []).length > 0 && (
              <div className="noaddress-said">CTMS said (OK'd): {j.notices.join('; ')}</div>
            )}
          </div>
          <div className="noaddress-fix">
            {j.state === 'queued' && (
              <button className="btn mini" onClick={() => send(j, 'drop')}>Take off</button>
            )}
            {j.state === 'stopped' && (
              <button className="btn mini go" title="After a look in CTMS: run it again from the step that stopped"
                onClick={() => { if (window.confirm('Looked at CTMS? Run it again from the step that stopped?')) send(j, 'again'); }}>
                Again</button>
            )}
          </div>
        </div>
      ))}
      {jobs.length > shown.length && (
        <div className="noaddress-row">
          <button className="btn mini" onClick={() => setAll(true)}>Show all {jobs.length}</button>
        </div>
      )}
    </div>
  );
}
