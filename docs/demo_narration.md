# Demo Narration — Golden Path Script

A linear, presenter-ready script for the actual 15-step golden path this system runs today:
healthy → inject fault → telemetry changes → anomaly detected → incident opens → UI shows it →
ask copilot → copilot explains with citations → recommended action shown → acknowledge → reset
→ incident resolves → UI returns to healthy. Each step names the exact feature entry it draws
from in `docs/feature_inventory.md`, so the presenter always knows which prepared explanation
backs what they're about to say. Target: 3–5 minutes spoken aloud.

This is the demo-order subset of the inventory, not a replacement for it — if a judge asks a
deeper question mid-step, the fuller technical answer is in the matching inventory entry.

---

**Before you start:** Postgres running, backend (`uvicorn main:app --port 8000`) and frontend
(`npm run dev`) both up, Ollama serving `gemma3:4b`/`mxbai-embed-large`, simulation reset to a
clean baseline (click **Reset** or `POST /api/simulation/reset`), and you're on the **Live
Monitoring** page.

---

### Step 1 — Healthy baseline
*(Inventory: Live Monitoring > System Health Card, Active Incidents panel, Header > Air-gap
status strip)*

**Say:** "This is the NOC dashboard for an air-gapped network — nine simulated nodes, ground
stations, routers, switches, a gateway, and a server. Everything's green: 100% health, zero
active alerts, no active incidents. Up top, notice the header — AIR-GAPPED, LLM local, RAG
local, DB local. Nothing here ever leaves this machine; that's the entire premise of the problem
statement."

**Transition:** "Let's break something."

---

### Step 2 — Inject a fault
*(Inventory: Live Monitoring > HITL Control Panel — target node select, fault type select,
Inject Fault button)*

**Do:** In the HITL Control Panel, pick `router-7` and "BGP Route Flap", click **Inject Fault**.

**Say:** "I'm simulating a BGP session flap on an edge router — the kind of thing that shows up
as a wall of SNMP/syslog noise in a real NOC, not a clean English sentence. That click just sent
a real API call that started a 20-to-40-second fault ramp inside our simulated network graph."

---

### Step 3 — Telemetry starts changing
*(Inventory: Live Monitoring > Telemetry Chart, Live Telemetry Feed)*

**Do:** Point at the chart (switch it to `router-7` / `bgp_flap_count` if not already) and the
scrolling log feed.

**Say:** "Every two seconds, our telemetry generator writes new values for this node straight
into Postgres. Watch the flap count and packet loss climb in real time on the chart, and in the
raw log feed below — this node just turned amber."

---

### Step 4 — Anomaly detected
*(Inventory: Live Monitoring > AI Status Summary, Live Telemetry Feed's anomaly strip)*

**Say:** "In parallel, every single tick, a real anomaly-scoring model — an Isolation Forest we
trained offline on this project's own simulated healthy traffic — scores this node. You can see
its anomaly score climbing right here in the AI Status panel. This isn't a threshold on one
metric; it's a real model recognizing the whole shape of the telemetry window looks abnormal."

---

### Step 5 — Incident opens
*(Inventory: Live Monitoring > Active Incidents panel)*

**Say:** "Now watch this panel — Active Incidents. It only just appeared, a few seconds after
the anomaly first showed up, because it requires three consecutive anomalous readings before it
opens — about six seconds — so one noisy blip can never trigger a false incident. And notice it
appeared instantly, not on the next poll: this is pushed live over a WebSocket the moment it's
written to the database. Severity, peak score, and root cause signal — the specific metric that
moved — are all real, computed fields, not placeholders."

---

### Step 6 — Ask the Copilot (fire early, talk over the wait)
*(Inventory: AI Copilot > Question input + Ask button / Suggestion chips)*

**Do:** Switch to the **AI Copilot** page, click the "Why is router-7 at risk?" suggestion chip
(or type it), hit Ask, **and keep talking immediately — don't wait for the answer.**

**Say:** "I'm asking the copilot right now, while it's still thinking — gemma3:4b, running fully
offline through Ollama on this laptop's CPU, typically takes 30 to 90 seconds to answer, so I'll
come back to this in a moment. Notice the button says 'Thinking locally...' — it's honest about
still working, never a frozen screen."

---

### Step 7 — Copilot receives real context
*(Inventory: AI Copilot > Question input + Ask button — the backend trace; AI Copilot >
Incident Context Panel)*

**Say (while waiting):** "Behind the scenes right now, the backend has already read router-7's
live anomaly score, its incident row, and retrieved the most relevant chunks from our runbook
knowledge base — all before it even calls the language model. You'll see that incident context
panel appear above the chat in a second, following whichever node we're discussing."

---

### Step 8 — Copilot retrieves runbook evidence
*(Inventory: AI Copilot > Citation badges / Retrieved Sources panel)*

**Say (once evidence/answer starts landing):** "There — the Retrieved Sources panel on the
right just populated. These are real nearest-neighbor hits from a local vector database over our
actual runbook markdown files, each with a genuine similarity score. This isn't decorative —
it's literally what got fed to the model."

---

### Step 9 — Copilot explains with citations
*(Inventory: AI Copilot > Message display)*

**Say:** "And here's the answer. Notice the layout: it's not a chat bubble, it's a NOC read — AI
analysis, root cause, the active incident it found on its own, then recommended actions. Every
field you see — confidence, risk — is exactly what the model actually returned, unmodified."

---

### Step 10 — Recommended action shown
*(Inventory: AI Copilot > "Recommended actions" list)*

**Say:** "Now point at this specific part — the recommended actions. These are **not** the
language model's idea. They're parsed directly, word for word, out of the retrieved runbook's
Recovery Procedure section, by regex, at request time. If the runbook doesn't contain a step,
the copilot literally cannot invent one here. That is the single most important design decision
in this whole system — it's why we can trust the 'what to do' part even when the 'why' part came
from a language model."

---

### Step 11 — (Optional, if time allows) Ask a follow-up
*(Inventory: AI Copilot > Conversation / session memory)*

**Do:** Type "What should I do?" — no node named — and hit Ask (keep talking while it thinks).

**Say:** "No node named in this question — the copilot has to resolve 'it' from context. This is
backed by a small, bounded conversation memory, kept in-process, no database, last four turns —
so this follow-up correctly resolves back to router-7, not whatever node happens to be worst
right now."

*(Skip this step if short on time — go straight to Step 12.)*

---

### Step 12 — Acknowledge the incident
*(Inventory: AI Copilot > Incident Context Panel, Acknowledge Incident button)*

**Do:** Scroll to the Incident Context Panel above the chat, click **Acknowledge Incident**.

**Say:** "This calls the real incident-acknowledgement endpoint directly — no client-side
pretending. Status flips to acknowledged, live, no page reload, and that change pushes out to
every screen watching this incident, including the monitoring page's live feed."

---

### Step 13 — Reset the simulation
*(Inventory: Live Monitoring > Reset button)*

**Do:** Back on Live Monitoring, click **Reset**.

**Say:** "Reset force-resolves every open incident on the board and snaps the network back to
healthy baselines — instantly, not gradually. This is the button I use to get back to a clean
state between demos."

---

### Step 14 — Incident resolves, UI returns to healthy
*(Inventory: Live Monitoring > Active Incidents panel, System Health Card)*

**Say:** "And there it is — Active Incidents back to 'No active incidents, network is nominal',
health back to 100%. That transition was pushed live too, the same WebSocket that opened the
card is what just closed it."

---

### Step 15 — Close on measured trust, not a claim
*(Inventory: `docs/feature_inventory.md`'s "The real current RAG grounding number, precisely")*

**Say:** "We don't just claim this is grounded — we measure it. An offline evaluation harness
runs 17 golden questions across all three fault types and checks two things: did retrieval find
the right runbook, and does the answer's actual language trace back to what it retrieved. Right
now that's 17 out of 17 on both. About half of those were answered directly by the model — and
all of those passed grounding on their own merits — while the CPU-timeout cases correctly fell
back to our deterministic template, which can't hallucinate because it never touches the
language model at all. Plus two control questions completely outside the runbooks' scope, which
it correctly declined to answer rather than guess."

---

## If Ollama is down or slow when a judge asks

Don't avoid this — demonstrate it. Ask any question; after ~50s the answer still renders, tagged
**"offline fallback · LLM unavailable"** in amber, built straight from the taxonomy + anomaly +
incident data with no model involved. It's a plainer answer, but it is never blank and never a
crash.

## If a judge asks about the HITL approve/reject buttons or the Audit Trail page

Say so plainly rather than improvising: "Those two are wired up in the UI end to end, but the
backend behind them is still a placeholder that always returns the same fixed response and
doesn't persist anything yet — that's on our punch list, not something we're claiming is
finished." A judge catching an inflated claim live is far worse than a confident, honest "this
part is still a stub."

## Fallback if short on time

Skip Step 11 (the follow-up question) and go straight from Step 10 (Recommended Actions) to
Step 12 (Acknowledge). Cuts roughly 40 seconds without losing the core "grounded, not invented"
story.
