import { useState } from 'react';

// Access-key gate. The DASH_KEY is stored in this browser only and sent as
// X-Auth on every request — identical to the original dashboard's login.
export default function Login({ onUnlock }) {
  const [val, setVal] = useState('');
  const submit = () => { if (val.trim()) onUnlock(val.trim()); };
  return (
    <div className="loginwrap">
      <div className="lcard">
        <div className="lmark">
          <div className="brandmark">DHL</div>
          <div className="brandtext"><b style={{ color: 'var(--ink)' }}>Haulage Desk</b><span style={{ color: 'var(--muted)' }}>Region 2 · Transport planning</span></div>
        </div>
        <h2>Access key</h2>
        <div className="lrow">
          <input type="password" placeholder="Enter your access key" autoFocus value={val}
            onChange={(e) => setVal(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') submit(); }} />
          <button className="btn primary" style={{ flex: 'none' }} onClick={submit}>Unlock</button>
        </div>
        <div className="hint" style={{ marginTop: 12, color: 'var(--muted)', fontSize: 12 }}>
          This dashboard is private. The key was set when it was deployed.
        </div>
      </div>
    </div>
  );
}
