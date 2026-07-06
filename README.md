# DHL Region 2 emailer — hosted dashboard

Deployable control plane for the Region 2 transport-planning dashboard.
The home PC runs the engine; this app is the remote control reachable from a
browser. See `region2-emailer/cloud/README.md` for architecture and setup.

## Railway deployment

1. Connect this repo to a new Railway project — the root `Dockerfile` is
   auto-detected, no configuration needed.
2. Set two environment variables (long random strings):
   - `DASH_KEY`  — typed into the dashboard in the browser
   - `AGENT_KEY` — used by the home PC's agent
3. Deploy, note the public URL, then on the home PC create
   `region2-emailer/cloud.json` from `cloud.json.example` with that URL and
   the AGENT_KEY. The supervisor connects within ~20 seconds.

No data is stored on the host: commands and status live in memory only, and
all email/Outlook work happens on the home PC.
