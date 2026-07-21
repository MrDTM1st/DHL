# Region 2 emailer — hosted dashboard

The work-laptop-accessible version of the dashboard. Deploy this folder to any
container host (Railway / Render / Fly). The control plane itself is Python
stdlib only; its UI is a React app (see below).

## The UI

The dashboard front end is a React app in [`web/`](web/) — DHL red/yellow theme,
top nav, a live Leaflet/OpenStreetMap map, dedicated tracker, and a notification
system. It is
built into one self-contained `index.html` and served by `server.py` at `/`
(with the original inline page kept as a fallback). It talks to the **same REST
API** documented below, so the home agent and this deployment are unchanged. The
Dockerfile builds it automatically (Node build stage → Python serve stage); no
extra setup. See [`web/README.md`](web/README.md) for the endpoint map and dev
instructions.

## How it fits together

```
work laptop (browser only)          cloud                       home PC
┌──────────────────────┐   HTTPS  ┌──────────────┐   outbound  ┌─────────────────┐
│ dashboard in browser ├─────────►│  server.py   │◄────────────┤ agent.py (poll) │
│ (DASH_KEY to log in) │          │ (this folder)│  (AGENT_KEY)│ does the work   │
└──────────────────────┘          └──────────────┘             │ via Outlook     │
                                                               └─────────────────┘
```

- The home PC only ever connects OUT. Nothing connects in to it.
- The cloud holds command/status data in memory only — nothing on disk.
- Email preview text passes through the cloud while you're editing it; it is
  never stored. Sending always happens from the home PC's Outlook.

## Deploy (Railway or Render, ~5 minutes)

1. Create a NEW project on the host (keep it separate from any other project).
2. Deploy this `cloud/` folder (it has its own Dockerfile). Options:
   - push it to a fresh private GitHub repo and connect that, or
   - `railway up` / drag-and-drop, depending on host.
3. Set two environment variables (generate fresh values — long random strings):
   - `DASH_KEY`  — the key YOU type into the dashboard at work
   - `AGENT_KEY` — the key the HOME PC uses (never typed anywhere public)
4. Ensure HTTPS is on (default on Railway/Render) and note the public URL.

## Connect the home PC

Create `cloud.json` next to `supervisor.py` on the home PC:

```json
{ "url": "https://YOUR-APP-URL", "agent_key": "THE AGENT_KEY VALUE" }
```

The supervisor picks it up within ~20 seconds and keeps a cloud agent running
alongside the local one. The dashboard header shows "home PC: online" once the
agent is polling.

## Use from work

Open the public URL in the browser, enter `DASH_KEY` once (stored in that
browser only). All five cards work exactly like the home dashboard.

## Notes

- Rotate keys by changing the env vars and redeploying (update cloud.json too).
- `/healthz` is an unauthenticated health check for the host's monitoring.
- If the dashboard shows "home PC: offline", the home PC is asleep, offline,
  or the supervisor isn't running. The header shows when it was last seen.
- Commands queued while the home PC is offline are NOT sent silently later:
  once a command is older than 10 minutes (`QUEUE_TTL` env var, seconds) AND
  the home PC has been away at least that long, it is dropped — including at
  the moment a long-offline PC reconnects, before it can run stale commands.
  The status card shows a red "NOT sent/run" notice that stays until you
  dismiss it (an online-but-busy PC keeps its backlog; nothing is dropped
  while the agent is checking in).
- The send panel has a Cc field; it is passed to the agent as `email.cc`
  (agent-side support: see `../HOMEPC_CHANGES.md`).
- `POST /api/panel` (agent key) holds persistent panel state — delivery-site
  decisions, holiday-handover status, team list — returned to the dashboard
  inside `GET /api/status` as `panel`. Dashboard commands from those cards
  carry a `data` dict through the queue (see `../INTEGRATE_ON_HOMEPC.md`).
