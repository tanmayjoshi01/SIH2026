# System Documentation — Air-Gapped AI Predictive NOC Copilot

This document is a complete, code-verified account of how the system actually works today,
covering the backend simulation/anomaly/incident pipeline, the RAG/Copilot/LLM pipeline, and
the frontend. It was produced by reading the current implementation directly (not by relying
on prior planning docs), and it explicitly flags points where the code differs from what
docstrings/comments elsewhere claim.

---

## 1. High-Level System Architecture

```
NetworkX topology (simulation/topology_def.py)
        |  build_topology() — 9 nodes, 10 links, baseline telemetry
        v
Telemetry generation (simulation/telemetry_generator.py, tick() every 2s)
        |  writes telemetry_logs rows + syncs nodes table
        v
Fault injection (simulation/fault_injector.py + fault_profiles.py)
        |  mutates the SAME in-memory graph node the generator reads from
        v
Anomaly scoring (services/anomaly_scoring_service.py, called inside the same tick)
        |  writes one anomalies row per (node, tick)
        v
Incident lifecycle (services/incident_manager.py, called inside the same tick, same transaction)
        |  writes/updates one incidents row per (node, active episode)
        v
PostgreSQL (db/models.py — 9 tables)
        v
API layer (routers/*.py, FastAPI, prefix /api; /metrics and /ws/incidents at root)
        |  (Copilot path only, on demand per question)
        v
RAG retrieval (rag/retrieve.py over a pre-built ChromaDB store)
        v
LLM / Ollama (services/llm_service.py -> gemma3:4b via raw HTTP)
        v
Copilot response (routers/copilot.py, POST /api/chat)
        v
Frontend (React/Vite, polling + one WebSocket)
        v
Human operator
```

Two independent data-refresh mechanisms exist side by side: a **background tick loop** (2s,
threaded, no HTTP involved) continuously drives simulation -> telemetry -> anomaly -> incident,
and a **request/response Copilot path** that only runs when a human asks a question — it reads
the same tables the tick loop just wrote but does not affect the tick loop at all
(`routers/copilot.py`'s incident read is explicitly read-only; all incident *writes* live only
in `services/incident_manager.py`).

| Stage | File | Receives | Produces | Next | DB table(s) | Endpoint(s) |
|---|---|---|---|---|---|---|
| Topology | `simulation/topology_def.py` | nothing (constants) | an `nx.Graph` with 9 nodes/10 edges, baseline attrs | Fault injector + generator | `nodes`, `links` (via seed script only) | `GET /api/nodes`, `/links`, `/topology` |
| Telemetry gen | `simulation/telemetry_generator.py` | the live graph | `telemetry_logs` rows + updated `nodes` row | Anomaly scorer | `telemetry_logs`, `nodes` | `GET /api/telemetry` |
| Fault injection | `simulation/fault_injector.py`, `fault_profiles.py` | `(node_id, fault_id)` | mutated graph node attrs over a 20-40s ramp | Telemetry gen (same tick) | none directly | `POST /api/simulation/fault`, `/reset` |
| Anomaly scoring | `services/anomaly_scoring_service.py` | a 5-sample telemetry window per node | one `Anomaly` row (score, prob, ETA, signals, model_version) | Incident manager | `anomalies` | `GET /api/anomalies`, `/predictions` |
| Incident lifecycle | `services/incident_manager.py` | the just-built (unflushed) `Anomaly` row | open/updated/resolved `Incident` row + WS event | Frontend / Copilot | `incidents` | `GET/POST /api/incidents...`, `/ws/incidents` |
| RAG retrieval | `rag/retrieve.py` | a text query | list of `RetrievedChunk` (file, section, excerpt, score) | Prompt builder | (ChromaDB, not Postgres) | internal to `/api/chat` |
| LLM | `services/llm_service.py` | a built prompt string | validated JSON dict or `None` | Copilot router | none | internal to `/api/chat` |
| Copilot | `routers/copilot.py` | a user question + session id | JSON answer (LLM or deterministic fallback) | Frontend | `anomalies`, `incidents`, `nodes` (read), `recommendations` (write) | `POST /api/chat` |
| Frontend | `frontend/src/` | polled/pushed API data | rendered dashboard | Operator | — | (calls almost every endpoint above) |

---

## 2. Backend File-by-File

### `backend/main.py`
- **Purpose:** FastAPI app entrypoint — CORS, global error envelope, router mounting, lifespan-managed background loop.
- **Input:** HTTP requests. **Output:** JSON/WS responses; on startup, spawns the telemetry thread.
- **Used by:** uvicorn (`uvicorn main:app`).
- **Database impact:** calls `init_db()` (idempotent `create_all`) at startup.
- **API impact:** mounts `health, monitoring, simulation, copilot, predictions, audit, hitl, incidents` under `/api`; `incidents.ws_router` at root (`/ws/incidents`); `/` and `/metrics` defined directly here.
- **Important logic:** `lifespan()` always calls `incident_manager.register_metrics()` (so `/metrics` works even if the loop is disabled), then conditionally starts `simulation_service.start_background_loop()` gated by `settings.run_telemetry_loop`. A global exception handler wraps every unhandled error/`HTTPException`/`SQLAlchemyError` into `{"error", "code"}`.

### `backend/config.py`
- **Purpose:** Single `pydantic-settings` `Settings` object, env-overridable via `.env`.
- **Important logic:** Holds simulation/incident thresholds (`incident_anomaly_threshold=0.4`, `incident_open_after_n_ticks=3`, `incident_resolve_after_n_ticks=3`, `incident_high/critical_severity_threshold=0.7/0.85`, `alert_webhook_url=None`) and static air-gap status strings. **Does NOT hold any RAG/LLM settings** — those are hardcoded module constants scattered across `rag/retrieve.py`, `rag/prompt_builder.py`, `services/llm_service.py`, `routers/copilot.py`.

### `backend/core/taxonomy.py`
- **Purpose:** Single source of truth for the 3 fault types + `healthy`. `FAULTS` list of `{id, label, display, action, critical, min_confidence}`; `ID_TO_INFO`/`LABEL_TO_ID` lookups; `policy_for_action()`.
- **Used by:** `anomaly_scoring_service.py`, `incident_manager.py` (severity's `critical`/`min_confidence` gate), `routers/copilot.py` (fallback text + deterministic recommended actions), `ml/train_anomaly_model.py`, `scripts/seed_demo_data.py`.

### `backend/db/models.py` / `database.py`
Full schema covered in section 3.

### `backend/simulation/topology_def.py`
- **Purpose:** Fixed 9-node/10-link demo topology + per-type baselines.
- **Output:** `build_topology()` returns a fresh `nx.Graph`, each node seeded with `status="healthy"`, type-specific `cpu`/`memory`, and fixed `packet_loss=0.2, latency_ms=8.0, interface_errors=0, bgp_flap_count=0`.
- **Used by:** `fault_injector.py` (baseline for reset), `telemetry_generator.py` (builds the live graph), `ml/train_anomaly_model.py` (synthetic healthy sequences), `scripts/seed_demo_data.py`.

### `backend/simulation/fault_profiles.py`
- **Purpose:** Defines the 3 fault ramps as `(baseline -> peak -> baseline)` linear curves over a random 20-40s episode (`ramp_up_fraction=0.55`).
- **Important logic:** `bgp_flap` ramps `bgp_flap_count, packet_loss, latency_ms`; `high_cpu` ramps `cpu, memory`; `packet_loss` ramps `packet_loss, interface_errors, latency_ms`. Each `MetricRamp` also carries `warning_threshold`/`critical_threshold` used for log-line banding (not incident severity — that's derived from `anomaly_score`, a separate computation).

### `backend/simulation/fault_injector.py`
- **Purpose:** Owns `active_episodes: Dict[node_id, FaultEpisode]` against the live graph. `inject()` starts a ramp; `tick(now)` advances all episodes and self-clears completed ones; `reset()` clears all episodes and snaps affected nodes to baseline.
- **Important logic:** Deliberately DB-agnostic (pure graph mutation) — incident resolution is wired around it (`TelemetryGenerator.reset()`) rather than inside it, so this module has zero knowledge of incidents/DB.

### `backend/simulation/telemetry_generator.py`
- **Purpose:** The heart of the pipeline. `TelemetryGenerator.tick()`: baseline jitter for non-faulted nodes -> `injector.tick()` for faulted nodes -> one DB transaction that writes all telemetry rows, syncs `nodes`, scores every node (`anomaly_scoring_service.score_node`), feeds each freshly-scored anomaly into `incident_manager.process_tick()`, commits, then broadcasts any pending WS events.
- **Important logic:** `reset()` calls `injector.reset()` then unconditionally `incident_manager.resolve_all()` (not scoped to which nodes were "active" — see section 15).

### `backend/services/simulation_service.py`
- **Purpose:** Process-wide singleton holder for one `TelemetryGenerator`, plus the daemon thread running `tick()` every `TICK_SECONDS=2.0`, plus a `threading.RLock` (`_lock`) serializing inject/reset/tick against each other.

### `backend/services/anomaly_scoring_service.py`
Full detail in section 5.

### `backend/services/incident_manager.py`
Full detail in section 6.

### `backend/services/alerting.py`
- **Purpose:** Optional demo webhook — POSTs a JSON payload when an incident first reaches `critical` severity, if `ALERT_WEBHOOK_URL` is set (default: no-op). Short timeout, log-and-continue on any failure, called synchronously inside the tick.

### `backend/services/telemetry_collector.py`
- **Purpose (as written):** A real `psutil`-based *local machine* telemetry collector.
- **Actual status:** **Dead code.** Nothing in the backend imports this module. It appears to be an early draft superseded by the simulated `telemetry_generator.py` and never removed.

### `backend/services/llm_service.py`
- **Purpose:** Talks to Ollama's raw HTTP API (`/api/generate`, model `gemma3:4b`) and validates/coerces its JSON output. Full detail in section 8/9.

### `backend/ml/feature_engineering.py`
- **Purpose:** Shared feature-vector builder — 6 metrics x 3 stats (mean/std/diff) over a 5-sample window = 18 features, used identically by the live scorer and the offline trainer.

### `backend/ml/train_anomaly_model.py`
- **Purpose:** Offline script (run by hand) that builds synthetic healthy + fault-episode telemetry from the project's *own* simulation code, fits an `IsolationForest(n_estimators=200, contamination=0.05)` on healthy windows only, min-max normalizes scores to `[0,1]`, and saves the artifact + a held-out sanity-check report to `ml/models/anomaly_isolation_forest.pkl`.

### `backend/routers/health.py`
- **Purpose:** `GET /api/health` — static air-gap status strip, deliberately touches no database so it answers even if Postgres is down.

### `backend/routers/monitoring.py`
- **Purpose:** Read-only topology/telemetry/health-score endpoints over `nodes`, `links`, `telemetry_logs`.

### `backend/routers/simulation.py`
- **Purpose:** Thin wrapper — `POST /api/simulation/fault`, `POST /api/simulation/reset` — delegates entirely to `services/simulation_service.py`.

### `backend/routers/predictions.py`
- **Purpose:** `GET /api/anomalies`, `GET /api/predictions` — "latest row per node" queries over `anomalies`. `PredictionOut` includes `incident_id`, `status` (default `"healthy"`), `severity` (default `"none"`) via a Python-side lookup against `incidents`. `AnomalyOut` does **not** carry incident fields.

### `backend/routers/incidents.py`
- **Purpose:** `GET /api/incidents`, `POST /api/incidents/{id}/acknowledge`, `GET /ws/incidents` (mounted at root). Full detail in sections 6/7.

### `backend/routers/copilot.py`
- **Purpose:** `POST /api/chat` — the entire Copilot orchestration (node resolution, anomaly/incident read, RAG retrieval, prompt build, LLM call, fallback, response assembly, session memory, best-effort `Recommendation` logging). Full trace in section 9.

### `backend/routers/audit.py`
- **Purpose (docstring):** "STUB (Day 1)... real implementation will read the audit_log table."
- **Actual status:** Still exactly that stub — only one commit ever touches this file. `GET /api/audit-logs` returns 3 hardcoded fake rows with fabricated hashes; never touches the `audit_log` table.

### `backend/routers/hitl.py`
- **Purpose (docstring):** "STUB (Day 1)... Day 3 implementation will persist the decision."
- **Actual status:** Also still exactly that stub. `POST /api/hitl/approve` / `/reject` return fixed `{"status": ..., "audit_log_id": 1 or 2}` regardless of input, and write nothing to the database. This is the endpoint the frontend's Copilot approve/reject buttons actually call — see section 15.

### `backend/rag/ingest.py`, `retrieve.py`, `prompt_builder.py`
Full detail in section 8.

### `backend/scripts/seed_demo_data.py`
- **Purpose:** Utility that wipes and re-populates all 8 original tables with one realistic sample row each, so the frontend could be built against real-shaped data before the live loop existed. Not part of the live demo path.

### `backend/scripts/stress_test_lifecycle.py`, `ws_reconnect_test.py`
Hardening test scripts that drive the full incident lifecycle and WS reconnection repeatedly against a running server to catch races/leaks. Not part of the app itself.

---

## 3. Database Flow

**TABLE: `nodes`** — one row per simulated device (9 rows). Columns: `id, name, type, status, cpu, memory, packet_loss, latency_ms, interface_errors, bgp_flap_count, node_metadata (JSONB, DB column literally "metadata")`. Writer: `telemetry_generator._sync_node_row()` every tick. Readers: `routers/monitoring.py`, `routers/copilot.py` (telemetry snapshot), frontend via `/api/nodes`.

**TABLE: `links`** — 10 static edges, written once (seed script / not re-synced live), read by `routers/monitoring.py` (`/api/links`, `/api/topology`) — **note: the frontend never calls either of these**, no topology visualization exists.

**TABLE: `telemetry_logs`** — one row per `(node, metric, tick)` — the hot-path table. Columns: `timestamp, node_id, subsystem, metric_name, value, unit, raw_log_line`. Writer: `telemetry_generator.tick()`. Readers: `ml/feature_engineering.fetch_window()`, `routers/monitoring.get_telemetry()`.

**TABLE: `fault_events`** — modeled but essentially unused in the live loop. `FaultInjector` tracks episodes purely in memory, never writing to this table.

**TABLE: `anomalies`** — one row per `(node, tick)`. Columns: detection fields (`fault_type, confidence, status`) plus scoring fields (`anomaly_score, failure_probability, eta_minutes, contributing_signals, model_version`). Writer: `anomaly_scoring_service.score_node()`, every tick, every node. Readers: `incident_manager.process_tick()` (same transaction), `routers/predictions.py`, `routers/copilot.py`.

**TABLE: `recommendations`** — one row per LLM answer that names an action. Writer: `routers/copilot.py` (best-effort, `anomaly_id` FK, `status="pending"` always — nothing ever flips it, since `hitl.py` is a stub that doesn't touch this table either).

**TABLE: `operators`, `audit_log`** — modeled, effectively unused live; `audit.py`/`hitl.py` are stubs that never write here.

**TABLE: `incidents`** — the lifecycle table. Columns: `id, node_id, opened_at, closed_at, status (open|acknowledged|resolved), severity (low|medium|high|critical), peak_anomaly_score, root_cause_signal`. Writer: `services/incident_manager.py` exclusively. Readers: `routers/incidents.py`, `routers/predictions.py`, `routers/copilot.py` (read-only), frontend `IncidentFeed`/`IncidentContextPanel`, Prometheus collector.

**Relationships:** No foreign key between `incidents` and `anomalies` (a deliberate choice — see section 6). `anomalies.node_id`, `telemetry_logs.node_id`, `incidents.node_id`, `links.source_id/target_id` all FK to `nodes.id`. `recommendations.anomaly_id` FKs to `anomalies.id`. `fault_events`, `operators`, `audit_log` are essentially orphaned in the live pipeline.

**Corrected data-flow diagram:**

```
telemetry_logs  <-- written every 2s tick, same transaction as below
      |  (5-sample window read)
      v
anomaly scoring (services/anomaly_scoring_service.py)
      |  (unflushed Anomaly object passed directly, not re-queried)
      v
anomalies  <-- written same transaction
      |
      v
incident manager (services/incident_manager.py) -- same transaction, commits together
      |
      v
incidents
      |                                    \
      v                                     v
GET /api/incidents, /ws/incidents      GET /api/predictions (status/severity)
      |                                     |
      v                                     v
frontend IncidentFeed/                 frontend AIStatusSummary
IncidentContextPanel                         |
      |                              routers/copilot.py (read-only lookup)
      \----------------------------------> RAG prompt -> LLM -> recommendations (write)
```

---

## 4. Simulation and Fault Injection

**Topology:** 9 fixed nodes (2 ground stations, 3 routers, 2 switches, 1 gateway, 1 server), 10 links (satellite/fiber/ethernet), built fresh by `build_topology()` on process start.

**Tick interval:** `TICK_SECONDS = 2.0`, driven by `simulation_service._run_loop()` in a daemon thread, wrapped by an `RLock` (`_lock`) that also guards `inject()`/`reset()`.

**Fault profiles:** `bgp_flap` (bgp_flap_count/packet_loss/latency_ms), `high_cpu` (cpu/memory), `packet_loss` (packet_loss/interface_errors/latency_ms) — each a linear ramp-up (55% of a random 20-40s duration) then ramp-down back to baseline. Episodes self-complete; there's no manual "end fault" action.

**Reset:** `FaultInjector.reset()` clears all `active_episodes` and snaps affected nodes to fixed baseline values, all under the RLock. `TelemetryGenerator.reset()` wraps this and additionally force-resolves every open/acknowledged incident system-wide.

**Complete example — `bgp_flap` on `router-7`:**
1. `POST /api/simulation/fault {node_id: "router-7", fault_type: "bgp_flap"}` -> `FaultInjector.inject()` creates a `FaultEpisode`, sets `node["status"]="degraded"`.
2. Next tick (<=2s later): `injector.tick()` samples the ramp, writes new `bgp_flap_count`/`packet_loss`/`latency_ms` graph values, emits a deterministic syslog line if a threshold band changed (e.g. `%BGP-4-FLAP_WARN`).
3. Same tick: `telemetry_generator` writes those as `telemetry_logs` rows and syncs `nodes.router-7`.
4. Same tick: `anomaly_scoring_service.score_node()` reads router-7's last-5-sample window, computes `anomaly_score`, writes an `anomalies` row.
5. Same tick: `incident_manager.process_tick()` sees `anomaly_score >= 0.4`, increments router-7's consecutive-above-threshold counter. Nothing opens yet.
6. After 3 consecutive above-threshold ticks (~6s): an `incidents` row opens (`status="open"`, severity derived from the score, `root_cause_signal` from the dominant contributing signal), and an `OPEN` event is broadcast on `/ws/incidents` after commit.
7. Frontend: `IncidentFeed` (Live Monitoring page) receives the WS push and shows the new card immediately; `AnomalyFeed`/`AIStatusSummary` pick it up on their next 3s poll; `GET /api/predictions` for router-7 now carries `status="open"`.

---

## 5. Anomaly Detection

**Features (`ml/feature_engineering.py`):** 6 metrics (`cpu, memory, packet_loss, latency_ms, interface_errors, bgp_flap_count`) x 3 stats (rolling mean, rolling std, first-difference) over the last 5 telemetry samples = 18-dim feature vector, identical code path for live scoring and offline training.

**Model:** `IsolationForest` (200 estimators, 5% contamination) trained only on synthetic healthy-jitter windows generated from the project's own baseline/jitter constants; fault-episode windows are held out purely to report precision/recall, never used to fit. Raw `score_samples` is sign-flipped and min-max normalized so live scores land in `[0,1]`, 1 = most anomalous.

- **`anomaly_score`:** the model's (or heuristic's) `[0,1]` anomaly reading for the node's current window.
- **`failure_probability`:** a separate, always-computed "worst metric / its critical threshold" ratio, clipped to `[0,1]`.
- **`eta_minutes`:** linear extrapolation of the fastest-rising metric's latest single-tick slope to its critical threshold; `None` if nothing is currently rising.
- **`contributing_signals`:** top-3 metrics by % change over the window, filtered to >=5% moves.
- **`model_version`:** `"isolation_forest_v1"` if the trained `.pkl` is present and loads, else `"heuristic_v1"` (the fallback — literally the same ratio as `failure_probability`, never presented as the trained classifier).

**Cadence:** every node, every 2s tick, one row each — regardless of whether a fault is active.

**Concrete example:** `router-7` under `bgp_flap` — as `bgp_flap_count` and `packet_loss` climb, their rolling mean/std/diff features grow; the isolation forest (trained only on flat healthy jitter) scores the window as increasingly out-of-distribution; `anomaly_score` crosses 0.4 within a couple of ticks, `contributing_signals` names `bgp_flap_count`/`packet_loss` as the dominant movers.

---

## 6. Incident Lifecycle

**States that actually exist** (the `incidents.status` column): **`open`**, **`acknowledged`**, **`resolved`** — exactly 3. There is no `RESOLVING` status in the schema.

**Corrected diagram:**
```
NORMAL (no incident row)
   |  3 consecutive ticks with anomaly_score >= 0.4 (in-memory counter, not a DB state)
   v
INCIDENT OPEN  (status="open")
   |  operator calls POST /api/incidents/{id}/acknowledge
   v
ACKNOWLEDGED   (status="acknowledged")
   |  3 consecutive ticks with anomaly_score < 0.4  -- OR --  a global reset (force, any active status)
   v
RESOLVED       (status="resolved", closed_at set)
```
"ANOMALOUS" and "RESOLVING" are not separate persisted states — "anomalous" is the in-memory
pre-open counter state, and resolution is a single atomic status flip once the resolve-gate
fires, not a gradual phase. An incident can resolve directly from `open` *or* `acknowledged`.

- **Open gate:** `IncidentManager.process_tick()` tracks per-node consecutive-above/below counters in memory (one `IncidentManager` per process). One noisy tick can't flip status either direction.
- **Severity:** derived only from `anomaly_score` (`>=0.85` and taxonomy `critical=True` and `score >= min_confidence` -> `critical`; `>=0.7` -> `high`; `>=0.4` -> `medium`; else `low`), then capped one level down if the anomaly's `model_version` is the heuristic fallback. Severity only ever escalates within one incident's lifetime.
- **`peak_anomaly_score`:** max score seen across the incident's life, updated every tick.
- **`root_cause_signal`:** the dominant `contributing_signals` entry from the anomaly row that most recently changed the incident, tagged `[heuristic score]` if that anomaly was heuristic-sourced.
- **One-open-per-node:** enforced in Python (`_active_incident()` looks up the node's current open/acknowledged row before deciding to open vs. update) — not a DB constraint.
- **Acknowledge:** `acknowledge_incident()` rejects (400) an already-resolved incident; is idempotent if already acknowledged; broadcasts a WS `UPDATE`.
- **Reset:** force-resolves *every* open/acknowledged incident system-wide — not scoped to `FaultInjector`'s momentarily-active episodes, since an episode can self-complete before its incident decays below threshold.
- **Re-crossing:** if anomaly returns after resolution and re-crosses the open gate, a brand-new incident row is created — a resolved row is never reopened.
- **WebSocket events:** `{"event": "OPEN"|"UPDATE"|"RESOLVE", "incident": {...}}`, broadcast only after the triggering DB transaction commits.
- **Metrics:** `/metrics` exposes `noc_open_incidents_total` and `noc_open_incidents_by_severity{severity=...}`, computed fresh from Postgres on every scrape.

---

## 7. API / Router Map

| Method | Endpoint | Purpose | Input | Output | Frontend user |
|---|---|---|---|---|---|
| GET | `/api/health` | air-gap status strip | — | `{status, air_gap:{...}}` | `TopHeaderBar` |
| GET | `/api/nodes` | node list | — | `NodeOut[]` | `LiveMonitoring`, `HITLControlPanel` |
| GET | `/api/links` | link list | — | `LinkOut[]` | unused (dead export) |
| GET | `/api/topology` | nodes+links | — | `TopologyOut` | unused (dead export) |
| GET | `/api/telemetry` | recent telemetry rows | `node_id?, since?, limit?` | `TelemetryOut[]` | `LiveMonitoring` (feed + chart) |
| GET | `/api/health-score` | fleet health rollup | — | `{overall_pct, active_alerts}` | `SystemHealthCard` |
| POST | `/api/simulation/fault` | inject a fault | `{node_id, fault_type}` | `{status:"injecting"}` | `HITLControlPanel` |
| POST | `/api/simulation/reset` | clear faults + resolve incidents | — | `{status:"reset"}` | `HITLControlPanel` |
| GET | `/api/anomalies` | surfaced anomalies | — | `AnomalyOut[]` | `AIStatusSummary` |
| GET | `/api/predictions` | failure forecasts + incident status | — | `PredictionOut[]` | `AIStatusSummary` |
| POST | `/api/chat` | ask the Copilot | `{question, session_id}` | answer dict (section 9) | `AICopilot`/`ChatWindow` |
| GET | `/api/incidents` | list incidents | `status?, node_id?` | `IncidentOut[]` | `IncidentFeed`, `IncidentContextPanel` |
| POST | `/api/incidents/{id}/acknowledge` | acknowledge | — | `IncidentOut` | `IncidentContextPanel` |
| GET | `/api/audit-logs` | audit trail | — | fixed fake rows (stub) | `AuditTrail` |
| POST | `/api/hitl/approve` | approve a recommendation | `{recommendation_id?, operator, note}` | fixed stub response | `ChatWindow` approve button |
| POST | `/api/hitl/reject` | reject a recommendation | same | fixed stub response | `ChatWindow` reject button |
| GET | `/metrics` | Prometheus scrape | — | text exposition | Prometheus/Grafana only |
| WS | `/ws/incidents` | live incident events | — | `{event, incident}` stream | `IncidentFeed` |

---

## 8. RAG Pipeline

1. **Runbooks:** `data/runbooks/*.md` (`bgp_flap.md`, `high_cpu.md`, `packet_loss.md`, `general_troubleshooting.md`).
2. **Chunking:** `##`-heading section splitting (not fixed-size), with a further per-bullet split for unordered policy-bullet sections — numbered step-by-step Recovery Procedures are kept as one chunk so the Copilot can parse the whole ordered sequence.
3. **Embeddings:** `mxbai-embed-large` via raw `POST http://127.0.0.1:11434/api/embeddings` (no `ollama`/LangChain packages actually used, despite being in `requirements.txt`).
4. **Why mxbai-embed-large:** an asymmetric retrieval model — queries (not documents) are prefixed with `"Represent this sentence for searching relevant passages: ..."` at retrieval time.
5. **Vector store:** ChromaDB `PersistentClient` at `backend/rag/chroma_store/`, collection `"runbooks"`, cosine similarity space, deterministic chunk IDs (`file::section-slug`). Fully wiped and rebuilt on every manual run of `ingest.py` — never auto-run; the API server never re-ingests.
6. **Retrieval:** `retrieve(query, k=3)` (Copilot's override of the module default `k=5`), cosine `score = 1 - distance`, threshold `0.5` — anything below is dropped.
7. **Similarity threshold:** `0.5`, hardcoded in `rag/retrieve.py`.
8. **Top-k:** module default 5; Copilot requests `k=3`, then sends only the top 2 (`PROMPT_CHUNK_LIMIT=2`) to the LLM prompt while showing all 3 in the frontend evidence panel.
9. **Telemetry in prompt:** one line, omitted entirely (not stated as absent) if unavailable — this avoids the model echoing an "absent" statement instead of answering.
10. **Anomaly info:** always present as one line, even when `None` (renders `"no anomaly scoring available for this node"`).
11. **Incident info:** one line if an active incident exists, otherwise omitted entirely.
12. **Retrieved evidence:** numbered `[i] file / section: excerpt` block, excerpts truncated to 260 chars at word boundaries; a fixed string if empty.
13. **Final prompt:** system preamble (strict JSON-only, evidence-only instruction, worked "insufficient evidence" example) -> optional history -> question -> node -> optional telemetry -> anomaly (always) -> optional incident -> evidence block -> `"JSON:"` cue.
14. **Gemma 3 4B call:** `POST /api/generate` with `format:"json"`, `temperature=0.1`, `num_predict=220`, `keep_alive="30m"`, `timeout=50s`, fully synchronous (blocks the request thread).
15. **JSON validation:** `json.loads` + a strict 6-key schema check; qualitative labels for `risk`/`confidence` are coerced to numbers via a lookup table.
16. **Retry:** exactly one retry, only on malformed/invalid-schema output (never on network failure/timeout). Max 2 Ollama calls per request. `generate_json()` never raises.
17. **Ollama failure:** any request exception -> logged, returns `None`, immediate deterministic fallback.
18. **Deterministic fallback:** built entirely from `core.taxonomy` + the latest `Anomaly` row (no LLM, no hallucination risk) — `summary` prefixed `"[Offline fallback] "`, plus a `"mode": "fallback"` field the frontend keys off.

**Anti-hallucination design:** the single most important mechanism is that `recommended_actions`
(the ordered list a judge sees) is parsed directly out of the retrieved Recovery Procedure
chunk's numbered steps via regex, never generated by the LLM — only the free-text
`summary`/`root_cause`/singular `recommended_action` come from Gemma, and even those are
constrained to "Evidence section only, or say so" by the system prompt, with a hard
similarity-threshold on retrieval and a fully non-LLM fallback path when Ollama fails.

---

## 9. Copilot Flow

```
USER QUESTION ("Why is router-7 failing and what should I do?")
     |
ChatWindow / AICopilot.jsx -- optimistic user bubble appended immediately
     v
POST /api/chat {question, session_id}
     v
routers/copilot.py: post_chat()
     v
_pick_node() -- literal node-id substring in the question -> node_id="router-7"
     v
_latest_anomaly()  +  session.get(Node, "router-7")
     v
_active_incident() -- read-only select on incidents
     v
retrieval_query = question + taxonomy display name of the active fault
     v
rag/retrieve.py: retrieve(retrieval_query, k=3) -> up to 3 chunks >=0.5 similarity
     v
prompt_builder.build_prompt(question, node_id, telemetry, anomaly, chunks[:2], incident, history[-2:])
     v
services/llm_service.generate_json(prompt) -> gemma3:4b via Ollama, <=2 calls, <=50s
     v
   success -> mode="llm", requires_human_approval = (LLM's recommended_action not "none")
   failure -> _fallback_response() -> mode="fallback"
     v
_recommended_actions() -- regex-parsed numbered steps from the Recovery Procedure chunk
     v
_remember_turn() -- appends to in-process 4-turn session history; best-effort Recommendation insert
     v
API RESPONSE: {summary, root_cause, risk, affected_component, recommended_action,
               recommended_actions[], evidence[], confidence, requires_human_approval,
               mode, incident_id, affected_node, status, severity}
     v
frontend: MessageBubble renders badges, summary, root cause, affected component,
          numbered recommended actions, citation badges, confidence + risk badges
     v
RetrievedSourcesPanel renders the same evidence[] as clickable source cards
     v
IncidentContextPanel (if affected_node present) independently polls /api/incidents every 4s
```

---

## 10. Frontend Pages

**Live Monitoring** — `frontend/src/pages/LiveMonitoring.jsx`, route `/`. Main NOC dashboard:
`SystemHealthCard`, `TelemetryChart`, `HITLControlPanel`, plus a right column of `IncidentFeed`,
`AnomalyFeed`, `AIStatusSummary`. Own polling loop every 2500ms. Fault injection/reset trigger an
immediate re-poll rather than waiting for the next tick.

**AI Copilot** — `frontend/src/pages/AICopilot.jsx`, route `/copilot`. Chat interface:
`IncidentContextPanel` (conditional), `ChatWindow`, `RetrievedSourcesPanel`. One-shot
`POST /api/chat` per question; `IncidentContextPanel` polls every 4s. Approve/reject calls the
**stub** `POST /api/hitl/approve|reject` with a **hardcoded `recommendation_id: 1`**; acknowledge
calls the real `POST /api/incidents/{id}/acknowledge`.

**Audit Trail** — `frontend/src/pages/AuditTrail.jsx`, route `/audit`. Read-only table from
`GET /api/audit-logs`, header labeled "stubbed · hash chaining lands Day 3" (never actually
implemented). One-shot fetch on mount, no polling/refresh.

---

## 11. Frontend Feature Map

| Feature | Component | Endpoint / WS | Backend router | Table | Displayed as |
|---|---|---|---|---|---|
| Live Monitoring | `LiveMonitoring.jsx` | `/api/nodes,/telemetry,/health-score` | `monitoring.py` | `nodes,telemetry_logs` | cards/chart |
| Network topology | *(none — dead API export)* | `/api/topology` | `monitoring.py` | `nodes,links` | not rendered anywhere |
| Node status | `SystemHealthCard.jsx` | `/api/nodes,/health-score` | `monitoring.py` | `nodes` | stat tiles + degraded list |
| Telemetry/metrics | `TelemetryChart.jsx` | `/api/telemetry` | `monitoring.py` | `telemetry_logs` | Recharts line |
| Anomaly feed | `AnomalyFeed.jsx` | `/api/telemetry` + own `/api/anomalies` poll | `monitoring.py`, `predictions.py` | `telemetry_logs,anomalies` | scrolling log |
| Incident feed | `IncidentFeed.jsx` | `/api/incidents` + `/ws/incidents` | `incidents.py` | `incidents` | live cards |
| Incident context panel | `IncidentContextPanel.jsx` | `/api/incidents,/anomalies` | `incidents.py`, `predictions.py` | `incidents,anomalies` | detail card + ack button |
| AI Copilot | `AICopilot.jsx` | `/api/chat` | `copilot.py` | `anomalies,incidents,nodes,recommendations` | chat page |
| Retrieved sources | `RetrievedSourcesPanel.jsx` | (from `/api/chat` response) | `copilot.py` | (ChromaDB) | citation cards |
| AI status summary | `AIStatusSummary.jsx` | `/api/anomalies,/predictions` | `predictions.py` | `anomalies,incidents` | two ranked lists |
| Fault injection | `HITLControlPanel.jsx` | `POST /api/simulation/fault` | `simulation.py` | (graph, not DB) | select + button |
| Reset | `HITLControlPanel.jsx` | `POST /api/simulation/reset` | `simulation.py` | `incidents` (resolved) | button |
| Incident acknowledgement | `IncidentContextPanel.jsx` | `POST /api/incidents/{id}/acknowledge` | `incidents.py` | `incidents` | button -> badge flip |
| Approve/Reject | `ChatWindow.jsx` | `POST /api/hitl/approve|reject` | `hitl.py` (stub) | none | inline text result |
| Audit trail | `AuditTrail.jsx` | `GET /api/audit-logs` | `audit.py` (stub) | none | static table |
| Air-gap status | `TopHeaderBar.jsx` | `GET /api/health` | `health.py` | none | pill + 4 chips |

---

## 12. Frontend User Journey

1. **Operator opens dashboard** (`/`) — healthy fleet: green "AIR-GAPPED" pill, 0 active alerts, empty incident feed, flat telemetry chart.
2. **Operator injects `high_cpu`** via `HITLControlPanel` -> `POST /api/simulation/fault` -> success banner -> forces an immediate re-poll.
3. **Telemetry starts changing** — next poll cycle shows rising `cpu`/`memory` in `TelemetryChart` and `AnomalyFeed`.
4. **Anomaly appears** — `AnomalyFeed`'s strip and `AIStatusSummary`'s "Detected anomalies" list.
5. **Incident opens** (after 3 consecutive above-threshold ticks, ~6s) — `IncidentFeed` gets a live WS `OPEN` push instantly.
6. **Operator opens Copilot** and asks a question — receives the resolved node, its latest `Anomaly` row, its active `Incident` row, retrieved runbook chunks, and up to 2 turns of prior conversation.
7. **Copilot retrieves runbook evidence** — shown in `RetrievedSourcesPanel` regardless of whether the LLM call succeeds.
8. **Gemma generates the explanation** — "Thinking locally..." for up to ~50s, then summary/root-cause/affected-component render, tagged `mode:"llm"` (or an amber "offline fallback" pill with `mode:"fallback"`).
9. **Recommended remediation appears** — a numbered list parsed directly from the retrieved runbook's Recovery Procedure (not LLM-authored).
10. **Operator acknowledges/resets:** acknowledge flips status via `IncidentContextPanel` and pushes a WS `UPDATE`; reset force-resolves every open/acknowledged incident and returns the board to a clean state.

---

## 13. Real-Time Data Flow

| Frontend feature | Mechanism | Interval | Endpoint | Component | If it fails |
|---|---|---|---|---|---|
| Live Monitoring core | polling | 2500ms | `/api/nodes,/telemetry,/health-score` | `LiveMonitoring.jsx` | red "Backend unreachable... Retrying every 2.5s" banner |
| Anomaly strip | polling | 3000ms | `/api/anomalies` | `AnomalyFeed.jsx` | silently swallowed |
| AI status summary | polling | 3000ms | `/api/anomalies,/predictions` | `AIStatusSummary.jsx` | red error box |
| Incident context panel | polling | 4000ms | `/api/incidents,/anomalies` | `IncidentContextPanel.jsx` | red error box |
| Air-gap header | polling | 5000ms | `/api/health` | `TopHeaderBar.jsx` | red "AIR-GAP STATUS UNAVAILABLE" banner |
| Incident feed | **WebSocket** + REST seed/resync | reconnect every 4000ms on close | `/ws/incidents` (+ `GET /api/incidents` on mount and every reconnect) | `IncidentFeed.jsx` | auto-reconnects every 4s; no interim REST polling while disconnected despite a code comment claiming one |
| Copilot chat | synchronous request/response | on submit only | `POST /api/chat` | `AICopilot.jsx`/`ChatWindow.jsx` | red error bubble, no retry |
| Audit trail | one-shot fetch | none | `GET /api/audit-logs` | `AuditTrail.jsx` | red banner; never refreshes without navigation |

Backend-side: the telemetry/anomaly/incident pipeline is a background thread loop, not tied to
any request; `POST /api/chat` is fully synchronous — up to 50s of Ollama latency inside one HTTP
request, no streaming.

---

## 14. Air-Gapped Design

- **Internet needed only at setup:** pulling Docker images, `pip install`, `npm install`, and `ollama pull gemma3:4b` / `mxbai-embed-large`.
- **Fully local at runtime:** Ollama (localhost:11434), ChromaDB (file-backed, pre-built and committed to the repo), PostgreSQL (local Docker container), the FastAPI backend, the Vite frontend — none make any outbound network call during the demo.
- **If internet is completely unavailable during the demo:** everything still works, because every component already runs entirely on localhost with locally-cached model weights and a pre-built vector index. The `air_gap_*` fields in `GET /api/health` are static labels asserting this, not a live connectivity check.

---

## 15. Failure / Fallback Paths

| Scenario | Normal path | Failure | Fallback | User sees |
|---|---|---|---|---|
| Ollama unavailable | `generate_json()` calls `/api/generate` | request exception | immediate deterministic fallback, no retry | `[Offline fallback]` summary, amber pill |
| LLM timeout (50s) | same | request exceeds timeout | same fallback, no retry | same |
| Invalid LLM JSON | `_validate()` parses response | schema/type failure | one retry with a stricter prompt, then fallback | same (only if both attempts fail) |
| No RAG evidence | `retrieve()` returns chunks | 0 chunks >= threshold | prompt states no evidence found; LLM told to say so | low-confidence, honest "not covered" answer |
| Low similarity | `retrieve()` filters by score | all k results < 0.5 | dropped, not surfaced | same |
| Anomaly model unavailable | `_load_model()` looks for the `.pkl` | file missing/fails to load | `heuristic_v1` scoring | severity capped one level down |
| Database issue | any router's session | `SQLAlchemyError` | global handler -> `503 DB_UNAVAILABLE`; Copilot also has its own DB-unavailable fallback | red banners; Copilot still answers (degraded) |
| WebSocket disconnect | `IncidentFeed`'s open socket | `onclose`/`onerror` | auto-reconnect every 4s + REST resync on every reopen | "reconnecting..." header; no interim REST polling |
| Frontend API failure | any polled/one-shot fetch | network error / non-2xx | `ApiError{code,message}` per component | red banner in that component only |
| HITL approve/reject | `ChatWindow` buttons | n/a — always "succeeds" | `routers/hitl.py` is a stub, always returns a fixed response | success message even though nothing was persisted — a real gap |
| Audit trail | `AuditTrail.jsx` | n/a | `routers/audit.py` is a stub, hardcoded fake rows | plausible-looking but fabricated audit history |

---

## 16. Complete Architecture Diagram

```
+----------------------------------------------------------------------+
|  Frontend (React 19 + Vite, :5173)                                   |
|  LiveMonitoring / AICopilot / AuditTrail                             |
|  polling (2.5-5s, per component) + one WebSocket (/ws/incidents)     |
+-------------------------------+--------------------------------------+
                                 | HTTP + WS
+-------------------------------v--------------------------------------+
|  FastAPI (backend/main.py, :8000)                                    |
|  routers: health, monitoring, simulation, predictions, incidents,    |
|           copilot, audit(stub), hitl(stub)         + /metrics        |
+-------+---------------+------------------+-----------------+---------+
        |               |                  |                 |
+-------v------+ +------v-------+  +-------v--------+ +------v----------+
| simulation_  | | incident_    |  | rag/retrieve.py| | llm_service.py  |
| service.py   | | manager.py   |  | prompt_builder | | (gemma3:4b)     |
| (RLock +     | | (WS pub-sub, |  +-------+--------+ +------+----------+
| 2s tick loop | | metrics)     |          |                  |
| thread)      | +------+-------+   +------v--------+         |
+------+-------+        |           | ChromaDB      |         |
       |                |           | (chroma_store)|         |
+------v-------+        |           +---------------+  +------v------+
| fault_       |        |                               |  Ollama     |
| injector.py  |        |                               | (localhost, |
| + fault_     |        |                               |  :11434)    |
| profiles.py  |        |                               +-------------+
+------+-------+        |
       |                |
+------v----------------v-----------------------------------------------+
| anomaly_scoring_service.py (isolation_forest_v1 / heuristic_v1)       |
+------+------------------------------------------------------------+
       |
+------v-----------------------------------------------------------------+
| PostgreSQL (Docker, :5432) -- nodes, links, telemetry_logs,            |
| anomalies, incidents, recommendations, fault_events, operators,        |
| audit_log                                                              |
+--------------------------------------------------------------------+

Background loop (thread, no HTTP): topology -> fault ramp -> telemetry write
-> anomaly score -> incident open/update/resolve -> WS broadcast, every 2s,
all inside one DB transaction, serialized by an RLock against inject/reset.

Request-time loop (only on a Copilot question): read anomaly+incident ->
retrieve evidence -> build prompt -> call Ollama (<=2 tries, <=50s) ->
validate/fallback -> parse recommended actions from evidence -> respond.
```

---

## 17. Judge-Facing Explanation

**30 seconds:** "This is an air-gapped NOC copilot for ISRO-style networks that can never touch
the internet. We simulate a 9-node network, inject realistic faults, detect anomalies with a
locally-trained Isolation Forest, track them through a real incident lifecycle, and let an
operator ask a fully local LLM — gemma3 via Ollama — what's wrong and what to do, with every
recommended action pulled straight from actual runbook text, never invented."

**2 minutes:** "The backend simulates network telemetry every 2 seconds using NetworkX, so we
can inject faults like BGP flaps or packet loss and watch metrics ramp realistically. Every
tick, an Isolation Forest — trained offline on our own synthetic healthy/fault data — scores
every node's anomaly level. When a node stays anomalous for 3 consecutive ticks, we open a
persistent incident: severity, peak score, root cause signal, tracked through
open -> acknowledged -> resolved in Postgres, pushed live to the dashboard over a WebSocket. On
the AI side, when an operator asks a question, we retrieve the most relevant chunks from our
runbooks — chunked and embedded with mxbai-embed-large into a local ChromaDB — feed that plus
live telemetry and incident context into gemma3:4b running fully offline through Ollama, and get
back a grounded JSON answer. Critically, the actual recommended remediation steps aren't
generated by the LLM at all — they're parsed directly out of the retrieved runbook's numbered
Recovery Procedure, so the system literally cannot hallucinate an action it didn't read. If
Ollama is slow or down, we fall back to a deterministic answer built from taxonomy and anomaly
data — never a blank screen."

**Technical deep dive ("show me exactly how the prediction reaches the Copilot"):**
"`anomaly_scoring_service.score_node()` runs inside `telemetry_generator.tick()`'s single DB
transaction, writing one `anomalies` row per node every 2 seconds with `anomaly_score`,
`failure_probability`, `contributing_signals`, and `model_version`. That same unflushed row is
passed directly to `incident_manager.process_tick()` in the same transaction — no re-query —
which increments a per-node in-memory consecutive-tick counter and opens/updates/resolves an
`incidents` row accordingly, committing both tables atomically. When a user later asks the
Copilot a question, `routers/copilot.py` does a plain read-only SQLAlchemy select against both
`anomalies` (latest row for the resolved node) and `incidents` (any row with
`status in (open, acknowledged)`) — there's no queue, no cache, just direct Postgres reads at
request time. Those get folded as two lines into the LLM prompt alongside retrieved runbook
evidence, and the response also independently echoes `incident_id`/`status`/`severity` back to
the frontend so `IncidentContextPanel` can render it without a second round-trip."

---

## 18. Twenty Likely Judge Questions

1. **How do you guarantee the LLM doesn't hallucinate remediation steps?**
   The steps shown aren't LLM output — they're regex-parsed from the retrieved runbook text.
   `_recovery_steps_from_chunks()` in `routers/copilot.py` finds the retrieved chunk whose
   section title is exactly "Recovery Procedure" and splits its raw excerpt on numbered-list
   markers. Code: `backend/routers/copilot.py`, `backend/rag/prompt_builder.py`.

2. **What happens if Ollama crashes mid-demo?**
   The Copilot still answers, tagged as an offline fallback, built entirely from
   `core.taxonomy` + the latest `Anomaly` row. Code: `backend/services/llm_service.py`,
   `backend/routers/copilot.py`.

3. **Why can't a single noisy telemetry spike open a false incident?**
   It requires 3 consecutive above-threshold ticks (~6s). Code:
   `backend/services/incident_manager.py`, `backend/config.py`.

4. **How is severity computed?**
   From the anomaly score and fault criticality, capped down for the heuristic fallback model.
   Code: `backend/services/incident_manager.py` (`_severity_for_anomaly`).

5. **Is the incident table linked to the anomaly table by foreign key?**
   No — deliberately, by time-range instead, to avoid FK-maintenance overhead on a hot-path
   table. Code: `backend/services/incident_manager.py`, `backend/db/models.py`.

6. **How does the dashboard get incident updates — polling or push?**
   Push, over a WebSocket, with a REST fallback on mount/reconnect. Code:
   `backend/routers/incidents.py`, `frontend/src/components/monitoring/IncidentFeed.jsx`.

7. **What happens if the WebSocket client's tab crashes without closing cleanly?**
   The server detects it within ~10 seconds and cleans up, rather than leaking a thread
   forever. Code: `backend/routers/incidents.py`.

8. **Is the anomaly detector a real ML model or a rules engine?**
   Both — a real Isolation Forest, with a heuristic fallback if the model file is missing,
   transparently recorded in `model_version`. Code: `backend/ml/train_anomaly_model.py`,
   `backend/services/anomaly_scoring_service.py`.

9. **How does the Copilot know which node the follow-up question is about?**
   Bounded, in-process conversation memory per session (last 4 turns). Code:
   `backend/routers/copilot.py`.

10. **Where does the vector index live and when is it built?**
    A pre-built local ChromaDB folder, built by hand once via `ingest.py`, never rebuilt by the
    running server. Code: `backend/rag/ingest.py`.

11. **Why mxbai-embed-large specifically?**
    It's an asymmetric retrieval model — queries get an instruction prefix, documents don't.
    Code: `backend/rag/retrieve.py`.

12. **What's the retrieval similarity threshold and why?**
    Cosine similarity >= 0.5; below that, no evidence is shown at all, so the system can
    correctly say "not covered" instead of always citing something. Code:
    `backend/rag/retrieve.py`.

13. **How do you keep gemma3:4b fast enough for a live demo on CPU?**
    Trimmed prompt/output size (`num_predict=220`, 2-of-3 chunks sent, 260-char truncation) plus
    `keep_alive="30m"` to avoid Ollama's default 5-minute unload. Code:
    `backend/services/llm_service.py`, `backend/rag/prompt_builder.py`.

14. **Does resetting the simulation clean up incidents from faults that already ended on their own?**
    Yes — reset force-resolves every open/acknowledged incident system-wide, not just ones from
    currently-active faults. Code: `backend/services/incident_manager.py`,
    `backend/simulation/telemetry_generator.py`.

15. **Is the HITL approve/reject workflow real?**
    No — it's still a stub that always returns a fixed success response and writes nothing.
    Code: `backend/routers/hitl.py`, `frontend/src/pages/AICopilot.jsx`.

16. **Is the audit trail cryptographically hash-chained as the schema suggests?**
    Not yet — the `audit_log` table has `prev_hash`/`hash` columns, but the endpoint is still a
    hardcoded stub. Code: `backend/routers/audit.py`, `backend/db/models.py`.

17. **Does the frontend show a network topology diagram?**
    No — despite backend endpoints for it existing, no topology visualization is implemented.
    Code: `frontend/src/api/client.js`, `backend/routers/monitoring.py`.

18. **What happens to an in-flight fault ramp if you reset mid-episode — any race condition?**
    No — an `RLock` serializes reset against the background tick loop; stress-tested 20+ cycles
    per fault type with zero orphaned/duplicate incidents. Code:
    `backend/services/simulation_service.py`.

19. **Can two incidents ever be open at once for the same node?**
    No, enforced in application code and verified under repeated re-injection stress testing.
    Code: `backend/services/incident_manager.py`, `backend/scripts/stress_test_lifecycle.py`.

20. **How do you know the RAG answers are actually grounded, not just plausible-sounding?**
    An offline evaluation harness measures it directly against a golden-question set, checking
    both retrieval correctness and whether the answer traces back to what was retrieved. Code:
    `backend/rag/eval_harness.py`, `backend/rag/golden_questions.json`,
    `backend/rag/eval_results.json`.

---

## 19. Top 10 Files to Understand as a Developer

1. `backend/simulation/telemetry_generator.py` — the single transaction that ties everything together each tick.
2. `backend/services/incident_manager.py` — the entire incident state machine.
3. `backend/db/models.py` — the schema contract every other file depends on.
4. `backend/routers/copilot.py` — the whole Copilot orchestration in one file.
5. `backend/rag/prompt_builder.py` — exactly what the LLM does/doesn't see, and why.
6. `backend/services/llm_service.py` — retry/timeout/JSON-validation contract with Ollama.
7. `backend/services/anomaly_scoring_service.py` — the isolation-forest/heuristic split and what `model_version` means downstream.
8. `frontend/src/components/monitoring/IncidentFeed.jsx` — the only real-time (WebSocket) piece of UI.
9. `frontend/src/pages/AICopilot.jsx` — the demo's centerpiece interaction, end to end.
10. `backend/config.py` — where thresholds live (and where RAG/LLM ones conspicuously don't).

---

## 20. Known Architectural Risks / Confusing Areas

- **`routers/hitl.py` and `routers/audit.py` are still pure stubs**, contradicting their own
  docstrings. The frontend's approve/reject flow and the entire Audit Trail page look fully
  functional but persist nothing.
- **The frontend's approve/reject call hardcodes `recommendation_id: 1`**, disconnected from
  whichever recommendation was actually shown — cosmetic today only because the stub ignores
  the value anyway.
- **No network topology visualization exists**, despite two backend endpoints
  (`/api/links`, `/api/topology`) built for exactly that and exported (unused) in the frontend
  API client.
- **`IncidentFeed.jsx`'s own code comment claims a polling fallback while the WebSocket is
  disconnected; no such fallback is actually implemented** — it just retries the socket every
  4s with no interim REST polling.
- **`services/telemetry_collector.py` is dead code** (a real-psutil collector from an early
  design direction, never wired in).
- **RAG/LLM configuration is scattered as hardcoded module constants** across 4 different files
  rather than centralized in `config.py`, unlike every other threshold in the system.
- **`requirements.txt` lists a much heavier stack** (LangChain/LangGraph, sentence-transformers,
  torch, the `ollama` package) than the RAG/LLM code actually imports — all of it is hand-rolled
  `requests`/`chromadb` calls.
- **No FK between `incidents` and `anomalies`** is a deliberate, documented design choice
  (time-range join instead) — worth knowing so it isn't "fixed" by someone unfamiliar with the
  reasoning.
- **The Copilot's LLM call is fully synchronous inside a FastAPI route** (not `async def`),
  meaning a single `/api/chat` request can block that request's worker thread for up to 50s —
  acceptable for a single-demo-operator scenario but not concurrency-safe for multiple
  simultaneous users.

---

*This document reflects a direct code read at the time of writing. If the implementation
changes, re-verify against the source rather than assuming this stays accurate.*
