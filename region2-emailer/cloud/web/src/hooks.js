import { useState, useEffect, useRef, useCallback } from 'react';
import { getStatus, getTracker, getWaitlist, AuthError } from './api.js';

// Poll a fetcher on an interval, surfacing 401s to onAuthFail so the app can
// show the login screen. Returns { data, refresh }.
function usePoll(fetcher, ms, onAuthFail, deps = []) {
  const [data, setData] = useState(null);
  const alive = useRef(true);
  const run = useCallback(async () => {
    try {
      const d = await fetcher();
      if (alive.current) setData(d);
    } catch (e) {
      if (e instanceof AuthError) onAuthFail && onAuthFail();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    alive.current = true;
    run();
    const iv = setInterval(run, ms);
    return () => { alive.current = false; clearInterval(iv); };
  }, [run, ms]);
  return { data, refresh: run };
}

// /api/status — state machine, agent liveness, queued count, dropped notices,
// and the agent-pushed `panel` (hauliers, decisions, handover, team).
export function useStatus(onAuthFail, ms = 1500) {
  const { data, refresh } = usePoll(getStatus, ms, onAuthFail, [onAuthFail]);
  return { status: data, refreshStatus: refresh };
}

// /api/tracker — open order groups the desk has emailed.
export function useTracker(onAuthFail, ms = 6000) {
  const { data, refresh } = usePoll(getTracker, ms, onAuthFail, [onAuthFail]);
  return { records: (data && data.records) || [], refreshTracker: refresh };
}

// /api/waitlist — far-ahead orders held until ~14 days out.
export function useWaitlist(onAuthFail, ms = 6000) {
  const { data, refresh } = usePoll(getWaitlist, ms, onAuthFail, [onAuthFail]);
  return { entries: (data && data.entries) || [], refreshWaitlist: refresh };
}

// Live wall clock (HH:MM:SS).
export function useClock() {
  const [t, setT] = useState('');
  useEffect(() => {
    const f = () => setT(new Date().toTimeString().slice(0, 8));
    f();
    const iv = setInterval(f, 1000);
    return () => clearInterval(iv);
  }, []);
  return t;
}
