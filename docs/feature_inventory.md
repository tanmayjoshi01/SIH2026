# Feature Inventory — Air-Gapped AI Predictive NOC Copilot

Every page and every interactive element currently in the frontend, verified against the
actual code and a live click-through/API exercise of the running app (not from memory or
prior planning docs).

**Branch confirmation:** `origin/main` (`bb860c4`) does **not** yet contain the Day-4
WebSocket-leak fix, the stress-test scripts, or the previously-written system documentation.
The most current integrated state is `paras-dev` (`origin/paras-dev`, currently checked out),
which is a strict superset of `main` plus that later work. This inventory reflects `paras-dev`
at the time of writing.

**Verification method:** the app was already running (Docker/Postgres, `uvicorn`, `npm run
dev`); every backend claim below was exercised live — inject → 3-tick open gate → ask the
Copilot (got a real `mode:"llm"` answer with citations) → acknowledge → reset → confirm
resolution — hitting the exact same endpoints with the exact same payload shapes the frontend
code calls. No browser-automation tool was available in this environment, so frontend
rendering claims are verified by reading the component source directly (not guessed from
names) and cross-checked against the live JSON payloads those components consume.

---

## Live Monitoring (`/`, `frontend/src/pages/LiveMonitoring.jsx`)

### Live Monitoring > Chart node selector
**What it looks like:** A small dropdown at the top-right of the page, next to the metric
dropdown, defaulting to `router-7` (or the first node returned by the API).
**What happens when you use it:** Purely client-side — changing it updates `chartNode` state,
which changes the `node_id` parameter on the next `GET /api/telemetry` poll (every 2.5s) and
re-renders `TelemetryChart` with that node's series. No backend call fires immediately; it
waits for the next poll tick.
**What data is real vs. simulated:** The list of nodes is real (from `GET /api/nodes`, backed
by the `nodes` table); the node itself is a simulated device, not a physical one.
**Judge-facing one-liner:** "This lets me pick which simulated node's live telemetry the chart
is tracking."

### Live Monitoring > Chart metric selector
**What it looks like:** Dropdown next to the node selector, options: cpu, memory,
packet_loss, latency_ms, interface_errors, bgp_flap_count.
**What happens when you use it:** Same as above — client-side only, filters the next poll's
`telemetry_logs` rows to the chosen `metric_name`.
**What data is real vs. simulated:** The metric values are simulated telemetry, but the anomaly
scoring and charting pipeline that consumes them is real code, not mocked.
**Judge-facing one-liner:** "And this switches which metric — CPU, packet loss, latency — is
plotted for that node."

### Live Monitoring > System Health Card
**What it looks like:** Top card on the left column: three stat tiles (Overall %, Active
alerts, Nodes), plus a list of any currently non-healthy nodes with their cpu/packet_loss and
a status badge.
**What happens when you use it:** Display-only, no controls. Refreshes every 2.5s from
`GET /api/health-score` (`{overall_pct, active_alerts}`, a rollup of the `nodes` table's
`status` column) and `GET /api/nodes`.
**What data is real vs. simulated:** Real, live-computed rollup over simulated node state — the
computation (`routers/monitoring.get_health_score()`) is real code doing real math on
simulated inputs.
**Judge-facing one-liner:** "This is a live rollup of fleet health — real math, run every
2.5 seconds, over our simulated network."

### Live Monitoring > Telemetry Chart
**What it looks like:** A Recharts line chart, labeled with the selected node/metric, height
~256px, in the left column below System Health.
**What happens when you use it:** Display-only. Renders the last up-to-40 points for the
selected node/metric from the 2.5s poll of `GET /api/telemetry`. Three states: red error panel
if the poll fails, "Waiting for telemetry..." if empty, or the line chart.
**What data is real vs. simulated:** The values plotted are simulated telemetry (from
`simulation/telemetry_generator.py`'s tick loop), but they are genuinely written to and read
back from Postgres each tick — not hardcoded or pre-recorded.
**Judge-facing one-liner:** "You're watching real database writes happen every two seconds, of
simulated but physically-realistic network telemetry."

### Live Monitoring > Live Telemetry Feed (log lines)
**What it looks like:** A scrollable panel in the right column titled "Live Telemetry Feed",
with a pulsing radio icon, a compact strip of colored anomaly badges above the log, and a
monospace scrolling list of `time / node_id / metric_name / value` rows below.
**What happens when you use it:** Display-only. The scrolling rows come from the page's shared
2.5s `GET /api/telemetry` poll; the badge strip above it is this component's own independent
3s poll of `GET /api/anomalies`. Rows for a currently-degraded node are tinted amber.
**What data is real vs. simulated:** Same telemetry pipeline as the chart — simulated inputs,
real storage/query path.
**Judge-facing one-liner:** "This is the raw telemetry stream a NOC operator would actually be
staring at, with anomalous nodes visually flagged."

### Live Monitoring > Active Incidents panel (Incident Feed)
**What it looks like:** Top of the right column, titled "Active Incidents" with a siren icon
(red if any are active), a "live"/"reconnecting..." status label, and a card per active
incident showing node id, severity badge, status badge, opened time, live duration, peak score,
and root cause signal.
**What happens when you use it:** Display-only. On mount, fetches `GET /api/incidents` once and
filters to `open`/`acknowledged`. Then opens a **live WebSocket** to `/ws/incidents`; `OPEN`/
`UPDATE` events upsert a card, `RESOLVE` removes it. On every socket reconnect it also re-runs
the REST fetch to resync anything that changed in the gap. If the socket closes, it retries
every 4 seconds.
**What data is real vs. simulated:** Fully real — this is the one genuinely push-driven feature
in the app, backed by `services/incident_manager.py`'s real 3-consecutive-tick lifecycle over
simulated telemetry.
**Judge-facing one-liner:** "This card appears the instant an incident opens — pushed live over
a WebSocket, not polled — because it required three straight anomalous readings, so a single
noisy blip can never trigger it."
**Known limitation (confirmed, not smoothed over):** this component's own code comment claims
it "falls back to polling if the socket cannot connect," but that fallback is **not actually
implemented** — while disconnected it only retries the WebSocket every 4s with no interim REST
polling. In practice this is a brief gap (a few seconds) since the retry is fast, but if asked
directly: the claimed polling fallback doesn't exist in the current code.

### Live Monitoring > AI Status Summary
**What it looks like:** Bottom card in the right column, "AI Status" with a brain icon, two
lists: "Detected anomalies" (node id, anomaly score, severity badge) and "Failure forecast"
(node id, failure probability %, ETA in minutes or "not currently rising").
**What happens when you use it:** Display-only. Own 3s poll of `GET /api/anomalies` and
`GET /api/predictions` together.
**What data is real vs. simulated:** Real anomaly-scoring output (isolation forest or heuristic
fallback, see the scoring entry below) computed on simulated telemetry.
**Judge-facing one-liner:** "This is our failure forecast — a real ETA-to-critical estimate,
computed from the trend in the last five readings, not a canned number."

### Live Monitoring > HITL Control Panel — target node select
**What it looks like:** Dropdown in the "HITL Control Panel" card, defaulting to `router-7`.
**What happens when you use it:** Client-side only — sets which node the next "Inject Fault"
click will target.
**What data is real vs. simulated:** The node list is real; selecting one has no effect on its
own.
**Judge-facing one-liner:** "I'll pick which node to fault — let's use router-7."

### Live Monitoring > HITL Control Panel — fault type select
**What it looks like:** Second dropdown, 3 options: "BGP Route Flap", "High CPU Utilization",
"Packet Loss" (exactly the 3 fault types defined in `backend/core/taxonomy.py`).
**What happens when you use it:** Client-side only, sets which fault the next injection uses.
**What data is real vs. simulated:** n/a (selector only).
**Judge-facing one-liner:** "And which kind of failure — a BGP flap, a CPU spike, or packet
loss."

### Live Monitoring > Inject Fault button
**What it looks like:** Amber button with a lightning-bolt icon, labeled "Inject Fault".
**What happens when you use it:** `POST /api/simulation/fault {node_id, fault_type}` →
`FaultInjector.inject()` creates a `FaultEpisode` and immediately marks that node
`status="degraded"`. On success, a green confirmation banner appears and the page's `load()`
callback fires immediately (not waiting for the 2.5s poll), refreshing nodes/telemetry/health.
The chosen metrics then ramp linearly toward a peak over a random 20–40 second episode; the
next telemetry tick (≤2s later) starts writing the ramped values to `telemetry_logs`. Once the
per-node anomaly score stays ≥0.4 for 3 consecutive ticks (~6s), `services/incident_manager.py`
opens an `incidents` row and the "Active Incidents" card appears via the WebSocket push.
**What data is real vs. simulated:** The fault and its effect on the network are fully
simulated (no real device is touched); everything downstream of it — the telemetry write, the
anomaly scoring model, the incident lifecycle logic, the database rows — is real code running
for real.
**Judge-facing one-liner:** "This button injects a realistic fault into our simulated network —
everything the system does in response from here is real: real scoring, real incident logic,
real database writes."

### Live Monitoring > Reset button
**What it looks like:** Outlined button with a circular-arrow icon, labeled "Reset", next to
Inject Fault.
**What happens when you use it:** `POST /api/simulation/reset`, no body → `FaultInjector.reset()`
clears every active fault episode and snaps affected nodes' telemetry back to fixed healthy
baselines, then unconditionally `IncidentManager.resolve_all()` force-resolves **every**
currently open/acknowledged incident system-wide (not just ones from faults that were still
mid-ramp — this also cleans up incidents whose underlying fault already finished on its own).
Both run inside the same `RLock` that serializes against the background tick loop, so there's
no race with an in-flight tick.
**What data is real vs. simulated:** Same as above — a simulated action with a fully real
backend response.
**Judge-facing one-liner:** "Reset wipes the board clean instantly — every open incident force-
resolves, and the network snaps back to healthy — this is the button I use to return to a clean
state between fault demos."

---

## AI Copilot (`/copilot`, `frontend/src/pages/AICopilot.jsx`)

### AI Copilot > Question input + Ask button
**What it looks like:** A text input with placeholder "Ask about the current network state..."
and a sky-blue "Ask" button below the chat window; the button reads "Thinking locally..." and
disables while a request is in flight.
**What happens when you use it:** On submit, the question is appended to the chat immediately
(optimistic user bubble) and `POST /api/chat {question, session_id}` fires. Backend:
`routers/copilot.py` resolves the target node (a literal node-id match in the question, else
the last node discussed in this session, else the highest-scoring open anomaly), reads that
node's latest `Anomaly` row and any active `Incident` row (read-only), builds a retrieval query,
calls `rag/retrieve.py` for up to 3 runbook chunks ≥0.5 cosine similarity, builds a prompt with
telemetry/anomaly/incident context plus the top 2 chunks, and calls `gemma3:4b` via Ollama
(`services/llm_service.py`, up to 2 tries, up to 50s). The parsed JSON (or a deterministic
fallback if Ollama fails) is returned and rendered as a new assistant bubble.
**What data is real vs. simulated:** The node/anomaly/incident context is simulated data; the
retrieval, the LLM inference, and the JSON validation are all real — the model genuinely runs
inference on this machine, and its answer text is not pre-written.
**Judge-facing one-liner:** "This question goes to a real local language model — it's actually
thinking, which is why it takes a moment; nothing here is a scripted response."

### AI Copilot > Suggestion chips
**What it looks like:** Three small pill buttons below the input: "Why is router-7 at risk?",
"What is causing packet loss on the edge?", "Summarise the current network risk."
**What happens when you use it:** Clicking one calls the exact same `ask()` flow as typing and
submitting that text — bypasses the input box entirely.
**What data is real vs. simulated:** Same as the question input above.
**Judge-facing one-liner:** "These are just shortcuts to the same real question flow, for a
faster demo."

### AI Copilot > Message display (chat bubbles)
**What it looks like:** A scrollable message list — user questions right-aligned in sky-blue,
assistant answers left-aligned in a bordered card with a bot icon, errors in a red card.
**What happens when you use it:** Display-only. Each assistant bubble renders, top to bottom:
badges (incident #, status, "approval required", and an amber "offline fallback · LLM
unavailable" pill if the answer came from the deterministic fallback rather than the LLM), "AI
analysis" (the summary), "Root cause", "Affected component", "Recommended actions" (a numbered
list — see below), inline citation badges, then a confidence badge and a color-coded risk badge.
**What data is real vs. simulated:** The rendering is a direct, unmodified pass-through of the
real backend response — no client-side fabrication of any field.
**Judge-facing one-liner:** "Every field here — the confidence score, the risk level, the
citations — is exactly what the backend actually computed, rendered as-is."

### AI Copilot > "Recommended actions" list
**What it looks like:** A numbered list inside the answer card (or a single code-styled action
if the older single-action shape is all that's present).
**What happens when you use it:** Display-only — this is the single most important grounding
mechanism in the system. `routers/copilot.py`'s `_recovery_steps_from_chunks()` looks for a
retrieved chunk whose section is titled exactly "Recovery Procedure" and splits its numbered
steps out via regex, verbatim from the runbook text. **The LLM never writes these steps.** Only
if no such section was retrieved does it fall back to the fault taxonomy's single canned
mitigation action (e.g. `restart_bgp_session`).
**What data is real vs. simulated:** Fully real, and specifically non-LLM — this is parsed
directly from the actual markdown files in `data/runbooks/`.
**Judge-facing one-liner:** "These steps aren't the AI's idea — they're copy-pasted, word for
word, out of our actual runbook document. The model can explain why, but it cannot invent what
to do."

### AI Copilot > Citation badges (inline + Retrieved Sources panel)
**What it looks like:** Small bordered cards showing a file icon, the source (e.g.
`bgp_flap.md § Symptoms`), a "match 0.81" similarity score, and a text snippet — both inline in
the answer bubble and in the right-hand "Retrieved Sources" panel.
**What happens when you use it:** Display-only. Both show the same `evidence` array from the
`/api/chat` response — the panel shows "Retrieving evidence..." while a question is in flight so
it never shows stale citations from the previous answer.
**What data is real vs. simulated:** Fully real — these are genuine nearest-neighbor hits from a
local ChromaDB vector index over the actual runbook markdown files, with real cosine-similarity
scores.
**Judge-facing one-liner:** "Every citation here is a real chunk of text retrieved from our
local knowledge base, with the actual similarity score — you can click through and see the
runbook text matches exactly."

### AI Copilot > Confidence badge and risk badge
**What it looks like:** Two small pills at the bottom of the answer card — "NN% confidence"
(color-coded green/amber/red) and "risk NN%" (color-coded the same way).
**What happens when you use it:** Display-only. `confidence` and `risk` come straight from the
LLM's own JSON output (coerced/clamped to `[0,1]` server-side), or are `0.0`/anomaly-derived on
the fallback path.
**What data is real vs. simulated:** Real model self-reported confidence — not independently
verified against ground truth, which is worth saying plainly rather than overstating it.
**Judge-facing one-liner:** "This is the model's own confidence in its answer, not an external
correctness check — we're honest that it's self-reported."

### AI Copilot > Approve / Reject buttons
**What it looks like:** Appears only under the most recent answer if it flagged
`requires_human_approval`; green "Approve" and outlined "Reject" buttons with a result line next
to them.
**What happens when you use it:** Calls `POST /api/hitl/approve` or `/reject`. **This backend
endpoint is still a Day-1 stub** — `backend/routers/hitl.py` ignores the request body entirely
and always returns a fixed `{"status": "approved"|"rejected", "audit_log_id": 1|2}`, writing
nothing to the database. The frontend also always sends a hardcoded `recommendation_id: 1`
regardless of which recommendation was actually shown.
**What data is real vs. simulated:** **This is not real.** It looks and behaves like a
functioning approval workflow but nothing is persisted; the response is fixed regardless of
input.
**Judge-facing one-liner (honest version):** "This HITL approval gate is wired up end to end in
the UI, but the backend behind it is still a placeholder — it doesn't yet persist a real
decision. I want to be upfront about that rather than let it look more finished than it is."

### AI Copilot > Incident Context Panel
**What it looks like:** Appears above the chat only when the latest answer named an affected
node; a card titled "Active Incident #N" (or a green "No active incident" line) with severity/
status badges, a 2×2 grid (Node / Open for / Peak score / Current score with a trend arrow), and
root cause signal.
**What happens when you use it:** Display-only except for its Acknowledge button (below). Polls
`GET /api/incidents?node_id=...` and `GET /api/anomalies` together every 4 seconds.
**What data is real vs. simulated:** Fully real — a direct read of the same `incidents` table
the Live Monitoring page's WebSocket feed is driven from.
**Judge-facing one-liner:** "This panel follows whatever node the conversation is currently
about, and shows you its live incident state in real time."

### AI Copilot > Acknowledge Incident button
**What it looks like:** Amber button inside the Incident Context Panel, only visible while the
incident's status is `open` (disappears once acknowledged).
**What happens when you use it:** `POST /api/incidents/{id}/acknowledge`. Backend rejects (400,
`INCIDENT_ALREADY_RESOLVED`) if the incident already resolved; otherwise flips
`status="acknowledged"` and broadcasts a WebSocket `UPDATE` to every connected client, including
the Live Monitoring page's Incident Feed simultaneously.
**What data is real vs. simulated:** Fully real — this is the genuine incident-lifecycle write
path, not a stub (unlike the approve/reject buttons above; verified live: an already-resolved
incident correctly returned `400 INCIDENT_ALREADY_RESOLVED` when tested).
**Judge-facing one-liner:** "Unlike the HITL approval buttons, this one is fully real — it
writes directly to the incident's row and pushes the change to every screen watching it live."

### AI Copilot > Conversation / session memory
**What it looks like:** Not a visible control — observable behavior: asking a follow-up like
"What should I do?" with no node named still resolves to the node just discussed.
**What happens when you use it:** A random `session_id` is generated once per page load and sent
on every `/api/chat` call. The backend keeps a bounded, **in-process, non-database** history of
the last 4 turns per session (`_SESSION_HISTORY`), and threads the last 2 into the prompt. If
`_pick_node()` finds no node named in the new question, it falls back to the last turn's node.
**What data is real vs. simulated:** Real, but explicitly limited — memory is lost on backend
restart and not shared across multiple browser tabs/sessions.
**Judge-facing one-liner:** "The copilot remembers the last few turns of this conversation, so
follow-ups like 'what should I do?' correctly resolve back to router-7 without me repeating
myself."

---

## Predictions (surfaced inside AI Status Summary, Live Monitoring page)

### Predictions > Failure probability / ETA / contributing signals
**What it looks like:** The "Failure forecast" list inside the AI Status Summary card (Live
Monitoring, right column): node id, a rounded failure-probability percentage, and either
"in ~N min" or "(not currently rising)".
**What happens when you use it:** Display-only, from `GET /api/predictions`, which surfaces the
latest `anomalies` row per node with `failure_probability ≥ 0.2`. `failure_probability` is a
"worst metric ÷ its critical threshold" ratio (computed independently of which anomaly-scoring
path produced `anomaly_score`); `eta_minutes` is a linear extrapolation of the fastest-rising
metric's latest slope to its critical threshold, `None` if nothing is currently rising.
`contributing_signals` (not shown in this list, but present in the underlying anomaly row and
surfaced in the Copilot's answers and the Incident Feed's "root cause" line) names the metrics
that moved most.
**What data is real vs. simulated:** Real computation over simulated telemetry — not a canned
forecast.
**Judge-facing one-liner:** "This isn't just 'anomalous or not' — it's an actual time-to-failure
estimate, extrapolated from the current trend."
**Note:** `GET /api/predictions` also now carries `incident_id`/`status`/`severity` per row
(cross-referenced from the `incidents` table) — confirmed live (`status:"healthy"`,
`severity:"none"` defaults for nodes with no active incident) — but this extra data isn't
currently rendered anywhere in the `AIStatusSummary` UI; it's available in the API response and
unused by this component today.

---

## Audit / Metrics

### Audit Trail (`/audit`, `frontend/src/pages/AuditTrail.jsx`) > Log table
**What it looks like:** A full page reachable from the sidebar, table columns ID / Timestamp /
Event / Payload / Hash, header explicitly labeled "stubbed · hash chaining lands Day 3".
**What happens when you use it:** No interaction — the page fetches `GET /api/audit-logs` once
on load and never refreshes.
**What data is real vs. simulated:** **Not real.** `backend/routers/audit.py` is still exactly
the Day-1 stub it was built as: 3 hardcoded fake rows with fabricated hash strings, never
reading the actual `audit_log` table. Despite the header's own honest label, this is worth
stating plainly again: nothing an operator does anywhere in the app writes a row this page would
ever show.
**Judge-facing one-liner:** "This page is a placeholder for the tamper-evident audit log — the
UI and its own label are upfront that the hash-chaining backend isn't built yet."

### `GET /metrics` (Prometheus scrape endpoint)
**What it looks like:** Not surfaced in the frontend UI at all — no page or component calls it.
**What happens when you use it:** It's a real Prometheus text-exposition endpoint at the
backend's root (`http://localhost:8000/metrics`, not under `/api`), scraped by the Prometheus
container defined in `backend/docker-compose.yml`, viewable directly in a browser or via
Grafana (also in the compose file) if someone builds a dashboard against it.
**What data is real vs. simulated:** Real, live-computed gauges (`noc_open_incidents_total`,
`noc_open_incidents_by_severity{severity=...}`), queried fresh from Postgres on every scrape —
but there is currently no in-app UI for it.
**Judge-facing one-liner (if asked):** "Prometheus and Grafana are wired up and already
exposing live incident metrics — we just haven't built a dashboard page for it inside the
product UI yet."

---

## Global / Header

### Header > Air-gap status strip
**What it looks like:** Top-right of every page: a green "AIR-GAPPED" pill plus four monospace
chips — NETWORK, LLM, RAG, DB — each showing a value like `OFFLINE`/`LOCAL`.
**What happens when you use it:** Display-only, refreshed every 5s from `GET /api/health`.
**What it actually checks vs. what it claims:** This is the most important honesty point in the
whole UI to get right for a judge. `GET /api/health` does **not** perform any live connectivity
check of Ollama, ChromaDB, or the network interface — it returns 4 **static configuration
strings** from `backend/config.py` (`air_gap_network="OFFLINE"`, `air_gap_llm="LOCAL"`,
`air_gap_rag="LOCAL"`, `air_gap_db="LOCAL"`), which are facts about how the system is deployed,
not measurements taken at request time. The one thing this endpoint does verify live is that the
FastAPI process itself is up and able to answer — it deliberately never touches the database, so
it still answers even if Postgres is down (that's the one honest "liveness" signal it carries).
If the endpoint is unreachable at all, the whole strip is replaced with a red "AIR-GAP STATUS
UNAVAILABLE" banner — that part is a real check (backend reachability), the four chip values
underneath it are not.
**Judge-facing one-liner:** "This strip confirms the backend is alive and reports how the system
is deployed — fully offline, everything local — as a fixed configuration fact, not a live
per-request network probe."

### Sidebar navigation
**What it looks like:** Left rail, 3 links: Live Monitoring, AI Copilot, Audit Trail. Footer
text reads "SIH 2026 · Day 1 prototype".
**What happens when you use it:** Standard client-side routing (`react-router-dom`); no backend
call.
**What data is real vs. simulated:** n/a.
**Judge-facing one-liner:** "Three pages: live monitoring, the AI copilot, and the audit trail."
**Note:** the footer label "Day 1 prototype" is stale — it hasn't been updated since the very
first frontend scaffold, despite the app now containing Day 3/4 incident-lifecycle and
WebSocket features. Purely cosmetic, but worth knowing before a judge reads it literally.

---

## Backend routers confirmed real vs. still stub (as of this inspection)

| Router | Status |
|---|---|
| `routers/health.py` | Real (static config, honest liveness-only check — see above) |
| `routers/monitoring.py` | Real (nodes/links/topology/telemetry/health-score, all live DB reads) |
| `routers/simulation.py` | Real (thin wrapper over the real `FaultInjector`/tick loop) |
| `routers/predictions.py` | Real (`/anomalies`, `/predictions`, both live DB reads, incident fields included) |
| `routers/incidents.py` | Real (`GET /incidents`, `POST /acknowledge`, `/ws/incidents` — full lifecycle) |
| `routers/copilot.py` | Real (`POST /chat` — full RAG + LLM + fallback pipeline) |
| `routers/audit.py` | **Still a stub** — 3 hardcoded fake rows, never reads `audit_log` |
| `routers/hitl.py` | **Still a stub** — fixed response, never writes anything, ignores its input |

---

## Discrepancy summary (planned vs. actual behavior)

These are the confirmed, code-verified gaps between what a feature's name/docstring/label
implies and what it actually does — surfaced explicitly per the accuracy requirement, not
smoothed over:

1. **`IncidentFeed.jsx`'s own code comment claims a polling fallback while the WebSocket is
   disconnected. No such fallback exists** — it only retries the socket every 4s.
2. **The HITL approve/reject workflow (`routers/hitl.py`) is still a Day-1 stub**, contrary to
   its own docstring's claim that "Day 3 implementation will persist the decision" — it's now
   past Day 4 and this has not changed. The frontend also sends a hardcoded
   `recommendation_id: 1` regardless of which recommendation was shown.
3. **The Audit Trail (`routers/audit.py`) is likewise still a Day-1 stub**, despite its own
   docstring's "Day 3" claim — its own frontend label is honest about this ("stubbed"), but it's
   worth stating unambiguously that it's still true.
4. **The air-gap status strip's four chips are static configuration, not a live connectivity
   check** — only the strip's fallback-to-red-banner behavior (on total backend unreachability)
   is a genuine live check.
5. **`api/client.js`'s own comment groups `getAnomalies`/`getPredictions`/`askCopilot` with
   `approveRecommendation`/`rejectRecommendation`/`getAuditLogs` under one blanket "Day 1 stubs
   - real implementations land on Day 2/3" comment.** This is now stale and misleading: the
   first three are fully real; the last three are still stubs. The comment doesn't distinguish
   them.
6. **The RAG grounding eval's headline "17/17" pass rate needs a caveat** (see
   `docs/demo_narration.md` and the note below) — it blends real LLM answers with trivially-
   passing fallback answers.

## The real current RAG grounding number, precisely

Re-run against the current code and freshly computed from the raw results file
(`backend/rag/eval_results.json`, last generated by commit `4c47b6e`, 17 in-scope golden
questions + 2 out-of-scope control questions):

- **Retrieval hit rate: 17/17 (100%)** — the correct runbook file was always among the
  retrieved chunks.
- **Grounding pass rate: 17/17 (100%)** — every answer's language traced back to its retrieved
  evidence (or, for fallback-mode answers, is trivially grounded since the fallback template is
  built from taxonomy/anomaly data with zero LLM involvement).
- **But: only 9 of those 17 in-scope questions were actually answered by the LLM in this run —
  the other 8 fell back to the deterministic template** (most likely due to gemma3:4b's ~50s
  per-call timeout on this CPU-only machine during that harness run, not a grounding failure).
  Of the 9 genuine LLM answers, all 9 passed the grounding check on their own merits.
- **Out-of-scope questions: 2/2 correctly declined** — the system correctly signaled
  insufficient evidence rather than guessing, for both control questions outside the runbooks'
  scope.

**Honest framing for a judge:** "17 out of 17 golden questions pass our grounding check, and
both of our out-of-scope control questions were correctly declined rather than answered with a
guess. About half of those 17 were answered by the LLM directly — and all of those passed
grounding on their own — while the rest hit our CPU inference timeout and fell back to the
deterministic template, which is grounded by construction since it never touches the LLM." This
is more accurate than simply citing "17/17" unqualified, and it's still a strong number.

---

*Verified against the actual running application at the time of writing. Page/component counts:
3 pages, 1 global header component, 1 sidebar, and 24 distinct feature/control entries
documented above, covering every interactive element and every major display panel found in
`frontend/src/pages/` and `frontend/src/components/`.*
