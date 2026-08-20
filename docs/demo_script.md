# Demo Script — Air-Gapped AI Predictive NOC Copilot (PS13)

A timed walkthrough of the real, currently-running system. Every step below is something
the app actually does today — nothing in this script is aspirational.

## Before you start

- [ ] Postgres running (`docker start sih2026_postgres`)
- [ ] Ollama running with `gemma3:4b` and `mxbai-embed-large` pulled
- [ ] Backend: `backend/venv/Scripts/python.exe -m uvicorn main:app --port 8000` (from `backend/`)
- [ ] Frontend: `npm run dev` (from `frontend/`), open `http://localhost:5173`
- [ ] Simulation reset (`POST /api/simulation/reset`, or click **Reset** in the HITL panel) so the
      board starts clean — 0 active incidents, all nodes healthy
- [ ] Confirm you're on the **Live Monitoring** page

## The one timing fact that shapes this whole script

gemma3:4b on this CPU-only laptop takes **40–90 seconds** to answer a copilot question — prompt
evaluation, not generation, is the bottleneck (see `backend/rag/prompt_builder.py`'s module
docstring for the measured numbers). A live demo cannot sit in silence for 90 seconds. **The fix
is pacing, not pretending the latency doesn't exist**: fire the copilot question early and talk
over the wait, so the answer is already on screen by the time you get to it. The script below is
built around that.

---

## Timed walkthrough (~4 minutes)

**0:00 — Open on Live Monitoring, everything healthy.**
"This is the NOC dashboard for an air-gapped MPLS network — nine simulated nodes, ground stations,
routers, switches. Notice the header: AIR-GAPPED, LLM: LOCAL, RAG: LOCAL, DB: LOCAL. Nothing here
ever leaves this machine, which is the entire premise of the problem statement — ISRO's ground
segment can't touch the public internet, not even for monitoring."

**0:20 — Inject a fault.**
In the HITL Control Panel, pick `router-7` and `BGP Route Flap`, click **Inject Fault**.
"I'm simulating a BGP session flap on an edge router — the kind of thing that shows up as a wall
of SNMP/syslog noise in a real NOC, not a clean English sentence."

**0:35 — While the anomaly ramps, switch to AI Copilot and ask the question now.**
Type "What is happening on router-7?" and hit **Ask**. The button shows "Thinking locally..."
"I'm asking the copilot right now, while it's still thinking — I'll come back to this in a moment.
Notice the wait state: it's honest about still working, never a frozen screen."

**0:50 — Back to Live Monitoring.**
Point at the **Active Incidents** panel: a row for router-7, severity **critical**, status **open**,
live duration ticking up, peak anomaly score, and a `root_cause_signal` naming the exact metric
that moved. "This came from Developer 1's incident manager — it required 3 consecutive ticks above
threshold before opening, so one noisy reading can't flip the board. It's pushed to this panel live
over a WebSocket, not polled."

**1:20 — Back to AI Copilot — the answer has landed.**
"Here's the model's answer, and notice the layout: it's not a chat bubble, it's a NOC read —
AI analysis, the active incident it found on its own by reading the incidents table, root cause,
then recommended actions."

**1:40 — Point at Recommended Actions specifically.**
"These steps are not the language model's idea. They're parsed directly out of the retrieved
runbook's Recovery Procedure section at request time — if the runbook doesn't contain a step, the
copilot cannot invent one here. That's the single most important design decision in this whole
system."

**2:00 — Point at Retrieved Sources.**
"Every citation is a real chunk retrieved from the local ChromaDB index, with its similarity score.
Click into the "Recovery Procedure" one — the recommended actions in the chat and the runbook text
on the right are the same words."

**2:20 — Ask a follow-up in the same session.**
Type "What should I do?" and hit Ask (again, keep talking while it thinks). "No node named in this
question — the copilot has to resolve 'it' from context." While it's thinking: "This is backed by a
small, bounded conversation memory — last 4 turns, kept in-process, no database — so this follow-up
correctly resolves back to router-7, not whatever node happens to be worst right now."

**2:50 — Acknowledge the incident.**
Scroll to the **Active Incident** panel above the chat, click **Acknowledge Incident**.
"This calls Developer 1's `POST /api/incidents/{id}/acknowledge` directly — no state-transition
logic on my side of this. Status flips to acknowledged, live, no page reload."

**3:10 — Reset the simulation.**
Back on Live Monitoring, click **Reset**. "This force-resolves every active incident and clears the
board." Point at Active Incidents going back to "No active incidents. Network is nominal."

**3:30 — Close on the eval harness number.**
"We don't just claim this is grounded — we measure it. An offline harness runs 17 golden questions
across all three fault types and asks two things: did retrieval find the right runbook, and does
the answer's language actually trace back to what it retrieved. Right now that's 17/17 on
retrieval and 17/17 on grounding, plus two control questions outside the runbooks' scope that it
correctly declined to answer instead of guessing."

---

## If Ollama is down or slow when a judge asks

Don't avoid this — demonstrate it. Ask any question; after ~50s the answer still renders, tagged
**"offline fallback · LLM unavailable"** in amber, built straight from the taxonomy + anomaly +
incident data with no model involved. It's a plainer answer, but it is never blank and never a
crash. This is the single best answer to "what if the model hallucinates or dies mid-demo" — show
it happening rather than describing it.

## Fallback if you're short on time

Skip the follow-up question (2:20–2:50) and go straight from Recommended Actions to Acknowledge.
Cuts ~40s without losing the core "grounded, not invented" story.
