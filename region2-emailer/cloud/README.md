# Region 2 emailer — hosted dashboard

The work-laptop-accessible version of the dashboard. Deploy this folder to any
container host (Railway / Render / Fly). No dependencies — Python stdlib only.

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
  or the supervisor isn't running.
