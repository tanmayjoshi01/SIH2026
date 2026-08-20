---
title: BGP Session Flap
subsystem: bgp
severity: critical
---

## Symptoms

A node begins logging repeated BGP adjacency transitions to a neighbor over
a short window. The generator emits these lines as the flap count crosses
its warning and critical bands:

```
%BGP-4-FLAP_WARN: router-7: BGP session to router-5 flapped 4 times in the last interval - monitoring
%BGP-2-FLAP_CRIT: router-7: BGP session to router-5 flapping (9 flaps) - session unstable, dampening applied
```

BGP flap episodes rarely occur alone. The same fault profile ramps
`packet_loss` and `latency_ms` on the affected uplink at the same time, so
expect these alongside the BGP lines:

```
%IF-4-PKTLOSS_WARN: router-7: packet loss at 2.6% on uplink to router-5
%IF-1-PKTLOSS_CRIT: router-7: packet loss at 6.1% on uplink to router-5 - link degraded
%QOS-4-LATENCY_WARN: router-7: round-trip latency at 24.3ms - above baseline
%QOS-2-LATENCY_CRIT: router-7: round-trip latency at 41.0ms - SLA breach
```

Operators will see the affected node's status move from `healthy` to
`degraded`, and `bgp_flap_count` climb well above its normal resting value
of 0.

## Diagnosis

- `bgp_flap_count` crosses its warning threshold at 3 flaps and its
  critical threshold at 8 flaps within the sampling window.
- `packet_loss` crosses warning at 2.0% and critical at 5.0% on the same
  uplink -- BGP re-convergence during a flap episode causes transient
  drops, so co-occurring packet loss is expected corroborating evidence,
  not a separate fault.
- `latency_ms` crosses warning at 20ms and critical at 35ms for the same
  reason (route reconvergence adds hops or forces a slower backup path).
- A `%BGP-5-ADJCHANGE: ... Up - flapping stopped` line marks recovery --
  treat this as the episode closing, not a new event.
- Cross-check the node's `anomaly_score` / `failure_probability` from the
  scoring service: this fault type is registered as **critical** in the
  fault taxonomy with a minimum recommendation confidence of 0.75, so a
  BGP flap call below that confidence should be treated as tentative.

## Root Cause

Repeated BGP session resets between two neighbors, most commonly caused by
an unstable underlying link (intermittent physical/satellite link loss),
a keepalive timer mismatch, or a neighbor router silently dropping and
re-establishing the TCP session. Each reset forces a full route
withdrawal and re-advertisement, which is what produces the correlated
packet loss and latency spikes during the same window -- the network is
briefly re-converging around the flapping link.

## Recovery Procedure

1. Confirm the flap is still active (check for a recent
   `%BGP-2-FLAP_CRIT` line and no `%BGP-5-ADJCHANGE ... flapping stopped`
   since).
2. Recommended action per the fault taxonomy: **restart_bgp_session** --
   manually reset the BGP session to the flapping neighbor rather than
   waiting for dampening to clear on its own, since the router is applying
   route dampening that will otherwise suppress the route for an extended
   penalty period.
3. After the restart, watch for the `%BGP-5-ADJCHANGE ... Up` recovery
   line and confirm `bgp_flap_count`, `packet_loss`, and `latency_ms` all
   settle back to their baseline values within one or two ticks.
4. This fault is marked critical in the taxonomy -- page the on-call
   operator immediately rather than queuing it for normal-priority review,
   and require human approval before the session restart is executed.
5. If flapping resumes immediately after a restart, escalate: this
   indicates a persistent physical-layer or neighbor-side problem that a
   session restart alone will not fix (see
   `general_troubleshooting.md` for the escalation procedure).
