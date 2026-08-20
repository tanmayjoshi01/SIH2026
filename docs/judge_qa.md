# Judge Q&A Prep — Air-Gapped AI Predictive NOC Copilot (PS13)

Answers reflect what is actually implemented and running, not the original planning-doc pitch.
Where our build diverged from the original tech-stack proposal, the honest answer says so —
judges probing a hackathon build respect an accurate answer far more than a rehearsed one that
doesn't match the demo.

---

### "Is this a real network?"

No — it's a deterministic simulation (`backend/simulation/`) generating synthetic telemetry and
SNMP/syslog-style log lines across 9 nodes (routers, switches, ground stations, gateway). The
telemetry schema and log line format are modeled on real SNMP/syslog conventions
(`%BGP-2-FLAP_CRIT`, `%IF-1-PKTLOSS_CRIT`, etc. — see `data/runbooks/*.md`), and the fault
injector ramps realistic warning→critical threshold crossings rather than random noise. We used
synthetic data deliberately, the same way the original PS13 planning doc anticipated this
question: real ISRO network data cannot leave their perimeter, so a synthetic-but-realistic
simulation is the only responsible way to build and demo this outside that perimeter.

### "How do you stop hallucination?"

Two independent layers, and we measure the second one rather than just asserting it:

1. **Structural**: the LLM never sees a blank slate. Every prompt includes the node's real
   telemetry, Developer 1's anomaly score, the active incident (if any), and retrieved runbook
   evidence — and the system prompt explicitly instructs it to answer only from that evidence.
   `recommended_actions` bypasses the LLM's own wording entirely — it's parsed directly out of the
   retrieved runbook's Recovery Procedure section, or falls back to the fault taxonomy's one
   canonical action. The model cannot invent an operational step here even if it wanted to.
2. **Measured**: `backend/rag/eval_harness.py` runs offline against 17 golden questions across all
   three fault types plus general troubleshooting, checking (a) did the correct runbook clear the
   retrieval threshold, and (b) is the model's answer lexically grounded in what it was actually
   given. Current numbers: **retrieval hit rate 17/17 (100%)**, **grounding pass rate 17/17
   (100%)**, plus 2 additional out-of-scope control questions (not counted in that 17) that the
   copilot correctly declined to answer rather than guessing. We publish the real number, not a
   rounded-up one: the Day 3 run of this same harness measured 12/17 (71%) grounding, and Day 4 was
   spent finding and fixing the actual cause rather than tuning the harness's pass bar. Reading the
   literal failing question/chunk/answer triples (not just the score) found two distinct bugs: the
   prompt stated "no live telemetry available" as its own sentence when telemetry was absent, and
   the small model would echo that verbatim as its answer instead of using the retrieved evidence
   — even when the evidence contained the answer; and one runbook section (a bulleted policy list)
   was chunked too coarsely for retrieval to isolate the specific policy a question asked about.
   Both are fixed at the source (prompt phrasing and chunking granularity, respectively), not
   papered over with a lower bar.
3. If retrieved evidence doesn't clear the similarity threshold, the system is instructed to say
   so plainly rather than guess — and if Ollama itself is unreachable or returns invalid JSON, the
   deterministic fallback template takes over and is clearly labeled `mode: fallback` in the UI.

### "Why gemma3:4b and not something bigger?"

This machine is a CPU-only Windows laptop with no GPU — the realistic hardware profile for an
on-prem, air-gapped NOC deployment, not a GPU cluster. gemma3:4b is the largest model that answers
in a demo-tolerable window (40–90s measured) on that hardware; anything larger pushed prompt
evaluation time (the actual bottleneck — see below) well past what's usable live. The original
planning doc proposed a 7B–8B class model (Llama 3 / Mistral); we tested against this machine's
real constraints and gemma3:4b was the size that actually worked here. This is exactly the
tradeoff the problem statement itself calls out: small local models are weaker at raw reasoning,
which is why we lean on RAG grounding rather than model size to keep answers trustworthy.

One specific, measured finding worth stating if asked to go deeper: on this machine, *prompt
evaluation* (reading the input), not token generation, is the latency bottleneck — a small
87-token prompt alone took ~12.5s to evaluate. That's why the prompt is kept deliberately short
(2 retrieved chunks, ~260 chars each, no telemetry history) rather than a knob we could just turn
up.

### "What happens if Ollama dies mid-demo?"

Ask it live. After Ollama is killed, `POST /api/chat` still returns a complete, usable answer —
summary, root cause, recommended action, incident context, evidence — built entirely from Developer
1's incident/anomaly data and the fault taxonomy, no LLM involved, clearly tagged **"offline
fallback · LLM unavailable"** in amber in the UI. It never returns a blank response or a crash.
This is a deliberately demonstrable failure mode, not just a claim — showing it live is more
convincing than describing it.

### "How is this different from Splunk ITSI / Nagios / other AIOps tools?"

Cloud AIOps platforms (Splunk ITSI, Moogsoft, Datadog) run their AI/ML layer on vendor cloud
servers — architecturally excluded here by the air-gap requirement, not a feature gap. Threshold
NMS tools (Nagios, Zabbix) are purely reactive with no prediction and no natural-language
reasoning. This system combines predictive anomaly scoring (Isolation Forest, trained locally,
with a heuristic fallback when untrained) with a RAG-grounded local LLM, entirely offline, with
every recommendation traceable to a specific retrieved runbook section.

### "Where did the retrieval/RAG stack actually end up, versus the original plan?"

The original planning doc proposed LangChain for RAG orchestration. In the actual build, retrieval
is hand-rolled (`backend/rag/retrieve.py`) — a direct ChromaDB cosine-similarity query against
`mxbai-embed-large` embeddings, no orchestration framework — because the retrieval logic itself
(embed query, top-k search, threshold filter) is simple enough that a framework added a dependency
without adding capability for this scope. Runbooks are chunked at ingest time by `##` section, with
list-structured sections (numbered steps, bulleted policies) further split into one chunk per
item — a Day 4 fix that let retrieval surface the exact policy a question asks about instead of a
truncated slice of a longer section. ChromaDB itself matches the original plan.

### "Is a human always in the loop before anything happens?"

Yes, and this is enforced in two places, not just stated. The taxonomy (`backend/core/taxonomy.py`)
marks every fault's mitigation action as requiring human approval before execution: the copilot
recommends, an operator decides. The `requires_human_approval` field in every `/api/chat` response
drives the UI's approve/reject controls, and the incident acknowledge flow is a separate, explicit
operator action against Developer 1's real incident endpoint — nothing in this system executes a
network change autonomously.

### "What's the audit trail story?"

Every `/api/chat` call that identifies a fault logs a `Recommendation` row (anomaly_id, action,
confidence, status) to Postgres. `GET /api/audit-logs` and the Audit Trail page surface the
operator-approval history. This maps to the "Security/Audit Officer" role described in the
original PS13 planning doc.

### "Does this scale beyond a 9-node demo network?"

The retrieval and LLM layers are stateless per-request — the bottleneck is Ollama's single-process
CPU inference, not the RAG pipeline or the database, so the realistic scaling path is more/better
on-prem compute (or model quantization) for the LLM layer specifically, not an architecture change.
Postgres and ChromaDB both handle far more than 9 nodes' worth of data without modification.
