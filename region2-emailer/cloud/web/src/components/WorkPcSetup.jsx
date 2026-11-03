import { useState } from 'react';

// The work PC's setup and its by-hand way, shared by the CTMS page (a work PC never set up) and Settings > Work PC.
const MODE = 'Look mum, no hands';
export const CODE_ZIP = 'https://github.com/MrDTM1st/DHL/archive/refs/heads/main.zip';
export const BRIDGE_FOLDER = '%USERPROFILE%\\CTMS-bridge\\region2-emailer\\work_pc';

// One file sets the work PC up. A web page cannot start programs on the PC
// by itself, so this is the one double-click; after it, the bridge starts at
// log-in (if ticked) and the Update button keeps it current.
export function SetupPanel({ onDownload }) {
  const [allow, setAllow] = useState(true);
  const [auto, setAuto] = useState(true);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    try { await onDownload(allow, auto); } finally { setBusy(false); }
  };
  return (
    <div className="ctms-setup">
      <div className="ctms-sub">
        One file sets the work PC up: it gets the code, connects it to this dashboard and starts the bridge.
        Nothing to type. Do this on the work PC.
      </div>
      <label className="ctms-check">
        <input type="checkbox" checked={allow} onChange={(e) => setAllow(e.target.checked)} />
        Let the haulage desk run CTMS when I turn on {MODE} mode
      </label>
      <label className="ctms-check">
        <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} />
        Start the bridge by itself when I log in
      </label>
      <button className="btn primary ctms-setupbtn" disabled={busy} onClick={go}>
        {busy ? <span className="spin" /> : 'Download the setup'}
      </button>
      <ol className="ctms-steps">
        <li>Open <b>CTMS bridge setup.cmd</b> from your downloads. If Windows says it protected your PC,
          choose <b>More info</b>, then <b>Run anyway</b>.</li>
        <li>It does the rest. Then open CTMS in your normal Edge as always - this page lights up by itself.</li>
      </ol>
      <div className="ctms-muted">
        If it says it can&rsquo;t get the code, <a href={CODE_ZIP} target="_blank" rel="noreferrer">download the
        code here</a> (it saves to Downloads) and run the setup again.
      </div>
      <details className="ctms-manual">
        <summary>Or set it up by hand</summary>
        <SetupSteps />
      </details>
    </div>
  );
}

export function SetupSteps() {
  return (
    <ol className="ctms-steps">
      <li>On the work PC, open Command Prompt in the <span className="mono">region2-emailer\work_pc</span> folder.</li>
      <li>Run <span className="mono">python ctms_bridge.py</span> and leave that window open.</li>
      <li>The first time, it asks for the key you log into this dashboard with. It keeps only a key made
        from it, which opens the bridge&rsquo;s channel and nothing else. It also asks whether the haulage
        desk may run CTMS when you turn on {MODE} mode here.</li>
      <li>Log into CTMS in the browser window it opens. This page lights up on its own.</li>
    </ol>
  );
}
