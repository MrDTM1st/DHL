# Haulage Desk — React dashboard

The redesigned front end for the Region 2 cloud control plane. Replaces the big
inline HTML page that used to live inside `server.py` with a modern React app —
red/yellow DHL theme, a top nav, a live Leaflet/OpenStreetMap map with layer
toggles and road-based routes, a dedicated tracker, and a notification system —
**wired to the exact same REST API**, so the home-PC agent and the deployment
model are unchanged.

## What it talks to

Everything goes through the control plane in `../server.py`, authenticated with
the `DASH_KEY` typed at login (sent as `X-Auth`, stored in the browser only):

| UI area | Endpoint(s) |
|---|---|
| Command cards (extract, weeks, send, DTS, form, rail plan, order upload, handover) | `POST /api/command`, `POST /api/upload` |
| Status card, review/batch/sites panels, dropped notices, agent-online pill | `GET /api/status` (state machine + `panel`) |
| Tracker (pipeline, chips, chasers, booked-via-call, learn-detail) | `GET /api/tracker`, `POST /api/command` |
| Map + Orders/hauliers panel + order drawer | `GET /api/tracker`, `panel.hauliers`, postcodes.io geocoding, OSRM (router.project-osrm.org) road routing |
| Notifications | derived client-side from orders inside the ≤3-day window |

No new backend endpoints were added. The haulier ranking (own fleet → tier 1 →
tier 2, distance only breaking ties) and the job-needs / capability match are
ported verbatim from the logic the original page ran in the browser.

## Develop

```bash
npm install
npm run dev            # Vite dev server; proxy /api to a running server.py, or
                       # run server.py and hit it directly with VITE proxying.
```

For a quick full-stack check, run the Python server and point a browser at it —
it serves the built app (see below).

## Build

```bash
npm run build          # -> dist/index.html  (one self-contained file)
```

`vite-plugin-singlefile` inlines all JS/CSS into a single `index.html`, matching
the control plane's single-file ethos. `server.py` serves it at `/` and falls
back to its own inline page if the build is absent.

## Deploy

The root `Dockerfile` (and `../Dockerfile`) is now multi-stage: a Node stage runs
`npm ci && npm run build`, then the Python image copies `dist/index.html` to
`web_index.html` next to `server.py`. Nothing else about the Railway/Render
deployment changes — same env vars (`DASH_KEY`, `AGENT_KEY`), same port.

## Source map

```
src/
  main.jsx            entry
  App.jsx             auth gate, polling, nav, notifications, toasts, wiring
  api.js              X-Auth fetch client for every endpoint
  hooks.js            polling hooks (status / tracker) + clock
  theme.css           DHL red/yellow design system
  icons.jsx           icon set
  lib/orders.js       urgency, pipeline, due text, needs + haulier ranking
  lib/geo.js          postcodes.io geocoding + OSRM road routing (cached in localStorage)
  components/         TopNav, Toasts, Drawer, NotifPop, OrdersPanel, FlowPanels, Login
  pages/              Dashboard, MapPage, TrackerPage, Notifications
```
