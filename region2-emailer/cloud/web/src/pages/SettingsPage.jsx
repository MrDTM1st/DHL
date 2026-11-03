import { useEffect, useState } from 'react';
import * as api from '../api.js';
import { SetupPanel, SetupSteps, CODE_ZIP, BRIDGE_FOLDER } from '../components/WorkPcSetup.jsx';

// Settings (his ask 03/11): kept out of the way behind the gear - updating the two PCs' code, and the work PC's setup
// with its by-hand way. "Update the home PC" pulls main from GitHub on the home PC (home_update.py: fast-forward only,
// refused over hand edits, put back if it won't compile) and the agents start again on it; "Update the work PC" is the
// bridge's own update, tried first and rolled back by itself if it won't start.

const HOME_STEPS = [
  ['In the repo folder on the home PC, check nothing was changed by hand', 'git status'],
  ['Go to main', 'git checkout main'],
  ['Bring it up to date', 'git pull origin main'],
  ['Start the agents again (the supervisor brings them back within 20 seconds)',
    "Get-CimInstance Win32_Process -Filter \"Name like 'python%'\" | Where-Object { $_.CommandLine -match 'agent\\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId }"],
];

function Copy({ text }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* none */ }
  };
  return <button className="btn mini" onClick={copy}>{done ? 'Copied' : 'Copy'}</button>;
}

function CodeLine({ text }) {
  return (
    <div className="settings-code">
      <code className="mono">{text}</code>
      <Copy text={text} />
    </div>
  );
}

function HomePc({ code, status, agentOnline, onCommand }) {
  const st = status || {};
  const busy = st.state === 'running' && /home PC's code/.test(st.detail || '');
  const last = /^Home PC: /.test(st.detail || '') ? st.detail : '';
  const update = () => {
    if (!window.confirm('Update the home PC from GitHub (main)?\n\nIt only moves forward: it stops if a file was changed '
      + 'by hand there, and puts the code back if the new code will not compile. Then both agents start again on it '
      + 'once they are not in the middle of anything (about 20 seconds).')) return;
    onCommand({ action: 'home_update' });
  };
  return (
    <div className="card settings-card">
      <div className="settings-head">
        <h3>Home PC</h3>
        <span className={'settings-dot' + (agentOnline ? ' on' : '')}>{agentOnline ? 'online' : 'offline'}</span>
      </div>
      <div className="settings-row">
        <div className="settings-what">
          <div className="settings-label">Code it runs</div>
          <div className="mono settings-value">
            {code && code.commit ? `${code.branch} @ ${code.commit}` : 'not known yet - it says after its next update'}
          </div>
          {code && code.subject && <div className="settings-muted">{code.subject}{code.when ? ` · ${code.when}` : ''}</div>}
        </div>
        <button className="btn red" disabled={!agentOnline || busy} onClick={update}>
          {busy ? <span className="spin" /> : 'Update the home PC'}
        </button>
      </div>
      {last && <div className={'settings-said' + (st.state === 'error' ? ' bad' : '')}>{last}</div>}
      <details className="settings-manual">
        <summary>Do it by hand</summary>
        <ol className="settings-steps">
          {HOME_STEPS.map(([what, cmd]) => (
            <li key={cmd}>{what}<CodeLine text={cmd} /></li>
          ))}
        </ol>
      </details>
    </div>
  );
}

function WorkPc({ onAuthFail, pushToast }) {
  const [st, setSt] = useState(null);
  const [asked, setAsked] = useState(null);       // the update's command id, while its answer is awaited
  const [showSetup, setShowSetup] = useState(false);

  useEffect(() => {
    let live = true;
    const poll = async () => {
      try {
        const s = await api.ctmsStatus(false);
        if (live) setSt(s);
      } catch (e) {
        if (e instanceof api.AuthError) onAuthFail();
      }
    };
    poll();
    const t = setInterval(poll, 4000);
    return () => { live = false; clearInterval(t); };
  }, [onAuthFail]);

  const answer = asked && st ? (st.results || []).find((r) => r.id === asked) : null;
  useEffect(() => {
    if (answer) {
      pushToast(answer.ok ? 'Work PC updating' : 'Work PC not updated', answer.detail || '', answer.ok ? 'go' : 'warn');
      setAsked(null);
    }
  }, [answer, pushToast]);

  const s = (st && st.state) || {};
  const online = !!(st && st.online);
  const updating = !!asked || ((st && st.queued) || []).some((q) => q.action === 'update')
    || !!(st && st.running && st.running.action === 'update');
  const update = async () => {
    if (!window.confirm('Update the bridge on the work PC from GitHub (main)?\n\nIt tries the new code first, '
      + 'restarts on it, and puts the old code back by itself if it will not start.')) return;
    try {
      const r = await api.ctmsCommand({ action: 'update', branch: 'main' });
      setAsked(r.id);
      if (!r.online) pushToast('Work PC bridge offline', 'Held for a minute: it only runs if the bridge checks in by then.', 'warn');
    } catch (e) {
      if (e instanceof api.AuthError) onAuthFail();
      else pushToast('Not sent', String((e && e.message) || e), 'warn');
    }
  };
  const getSetup = async (allow, auto) => {
    try {
      await api.downloadCtmsSetup(allow, auto);
      pushToast('Setup downloaded', 'Open "CTMS bridge setup.cmd" from your downloads - on the work PC.', 'go');
    } catch (e) {
      if (e instanceof api.AuthError) onAuthFail();
      else pushToast('Not downloaded', String((e && e.message) || e), 'warn');
    }
  };
  return (
    <div className="card settings-card">
      <div className="settings-head">
        <h3>Work PC</h3>
        <span className={'settings-dot' + (online ? ' on' : '')}>{st ? (online ? 'bridge online' : 'bridge offline') : '…'}</span>
      </div>
      <div className="settings-row">
        <div className="settings-what">
          <div className="settings-label">Bridge code</div>
          <div className="mono settings-value">{s.code || (s.version ? 'v' + s.version : 'not known yet')}</div>
          {s.code_at && <div className="settings-muted">since {s.code_at.replace('T', ' ').slice(0, 16)}</div>}
        </div>
        <button className="btn red" disabled={!online || updating} onClick={update}>
          {updating ? <span className="spin" /> : 'Update the work PC'}
        </button>
      </div>
      {s.rolled_back && <div className="settings-said bad">Rolled back: {s.rolled_back}</div>}
      <div className="settings-row">
        <div className="settings-what">
          <div className="settings-label">Setup file</div>
          <div className="settings-muted">To set the work PC up again, start the bridge, or change your choices.</div>
        </div>
        <button className="btn" onClick={() => setShowSetup((v) => !v)}>{showSetup ? 'Hide' : 'Setup file'}</button>
      </div>
      {showSetup && <SetupPanel onDownload={getSetup} />}
      <details className="settings-manual">
        <summary>Do it by hand</summary>
        <div className="settings-label">Where the bridge lives on the work PC</div>
        <CodeLine text={BRIDGE_FOLDER} />
        <ol className="settings-steps">
          <li>On the work PC, download the code: <a href={CODE_ZIP} target="_blank" rel="noreferrer">DHL-main.zip</a>.
            Leave it in Downloads.</li>
          <li>Run the setup file (above). When it can&rsquo;t get the code itself, it takes it from that ZIP.</li>
          <li>Or copy the ZIP&rsquo;s <span className="mono">region2-emailer\work_pc</span> folder over the one above, then
            start the bridge again by running the setup file.</li>
        </ol>
        <details className="settings-manual">
          <summary>Running the bridge from Command Prompt</summary>
          <SetupSteps />
        </details>
      </details>
    </div>
  );
}

export default function SettingsPage({ panel, status, agentOnline, onCommand, onAuthFail, pushToast }) {
  return (
    <div className="scroll"><div className="container page-anim settings">
      <div className="pagehead">
        <div>
          <div className="kicker">Haulage Desk</div>
          <h1 className="h1">Settings</h1>
        </div>
      </div>
      <HomePc code={panel && panel.home_code} status={status} agentOnline={agentOnline} onCommand={onCommand} />
      <WorkPc onAuthFail={onAuthFail} pushToast={pushToast} />
    </div></div>
  );
}
