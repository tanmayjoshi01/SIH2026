---
title: General NOC Troubleshooting and Escalation
subsystem: general
severity: info
---

## Symptoms

Use this runbook when a node's telemetry is ambiguous, when multiple
fault signatures overlap, or when the anomaly scorer flags a node without
a clear single fault type. Relevant signals to read together rather than
in isolation:

- `anomaly_score` -- how unusual the node's current telemetry window looks
  relative to normal operation, from either the trained Isolation Forest
  model (`model_version: isolation_forest_v1`) or, if that model has not
  been trained yet, a heuristic ratio of the worst metric to its critical
  threshold (`model_version: heuristic_v1`). Treat a heuristic-sourced
  score as a rougher signal than one from the trained model.
- `failure_probability` -- how close the node's single worst metric
  currently is to its critical threshold.
- `eta_minutes` -- a linear extrapolation of the fastest-rising metric's
  current slope to its critical threshold; absent when nothing is
  currently rising.
- `contributing_signals` -- which metrics moved the most over the recent
  window, e.g. `["bgp_flap_count +320%", "packet_loss +180%"]`; use this
  to identify which fault-specific runbook (`bgp_flap.md`, `high_cpu.md`,
  `packet_loss.md`) actually applies before falling back to this one.

## Diagnosis

1. Check whether `contributing_signals` points clearly at one fault
   family -- `bgp_flap_count` dominant means `bgp_flap.md`; `cpu`/`memory`
   dominant means `high_cpu.md`; `packet_loss`/`interface_errors`/
   `latency_ms` dominant with no BGP movement means `packet_loss.md`.
2. If no runbook chunk retrieved for the question clears the relevance
   threshold, or the node's `fault_type` reads `healthy` with a low
   `anomaly_score`, the correct answer is that there is **no active
   risk** -- do not invent a fault or cite a runbook section that was not
   actually retrieved as evidence.
3. If signals from more than one fault family are elevated at once,
   treat this as compounding faults rather than picking one arbitrarily,
   and prioritize whichever fault is marked critical in the fault
   taxonomy (`bgp_flap`, `packet_loss`) over the non-critical one
   (`high_cpu`).

## Root Cause

This runbook has no single root cause -- it exists for triage before a
more specific fault is identified, and for the escalation policy that
applies once a recommendation has been made regardless of fault type.

## Recovery Procedure

- **Confidence gating:** each fault type in the taxonomy has a minimum
  confidence before its action should be recommended --
  `bgp_flap` requires >= 0.75, `packet_loss` requires >= 0.70, `high_cpu`
  requires >= 0.65. A recommendation below its fault type's minimum should
  be presented as tentative, not acted on.
- **Escalation:** critical faults (`bgp_flap`, `packet_loss`) with
  confidence above their minimum should be flagged for immediate human
  approval rather than queued for normal-priority review. Non-critical
  faults (`high_cpu`) can be queued for normal-priority review unless
  compounding with a critical fault on the same node.
- **Human approval is always required** before any recommended action
  (`restart_bgp_session`, `restart_process_or_scale`, `reroute_traffic`)
  is actually executed -- the copilot recommends, it does not act
  autonomously.
- **If a fault does not clear after its recommended action**, do not
  repeat the same action blindly -- re-check `contributing_signals` for a
  second, different fault family before re-recommending, and if none is
  found, escalate to a human operator for physical/out-of-band
  investigation.
