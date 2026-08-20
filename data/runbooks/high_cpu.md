---
title: High CPU Utilization
subsystem: compute
severity: warning
---

## Symptoms

A node's CPU utilization climbs steadily and the generator logs threshold
crossings as it enters the warning and critical bands:

```
%SYS-4-CPUHIGH: server-1: CPU utilization at 74.2% - above warning threshold
%SYS-1-CPUCRIT: server-1: CPU utilization at 93.5% - process scheduling degraded
```

The same fault profile also ramps memory utilization on the same node,
so expect these alongside the CPU lines:

```
%SYS-4-MEMHIGH: server-1: memory utilization at 62.1% - above warning threshold
%SYS-1-MEMCRIT: server-1: memory utilization at 69.4% - risk of OOM
```

Recovery is logged the same way once the node settles:

```
%SYS-5-CPUNORMAL: server-1: CPU utilization back to 29.1% - nominal
%SYS-5-MEMNORMAL: server-1: memory utilization back to 38.0% - nominal
```

Unlike BGP flap or packet loss, a high-CPU node's `status` field may still
read `degraded` without any packet loss, latency, or interface-error
lines appearing -- this fault is compute-bound, not link-bound.

## Diagnosis

- `cpu` crosses warning at 70% and critical at 90%.
- `memory` crosses warning at 60% and critical at 68% -- the two metrics
  are ramped together by the same fault profile, so a node showing only
  one of the two crossing its threshold is more likely mid-ramp (still
  rising) than showing a different fault.
- Check `contributing_signals` from the anomaly scorer: a high-CPU episode
  should show `cpu` and `memory` as the dominant movers, with
  `packet_loss` / `latency_ms` / `bgp_flap_count` essentially flat.
- This fault type is registered as **not critical** in the fault taxonomy
  (unlike bgp_flap and packet_loss), with a minimum recommendation
  confidence of 0.65 -- it can be queued for normal-priority review rather
  than paged immediately, unless it is compounding with another active
  fault on a node the network depends on for routing.

## Root Cause

Sustained high CPU utilization is typically caused by a runaway or
looping process, an unexpected spike in control-plane work (e.g. route
recomputation, SNMP polling storms), or a workload that has outgrown the
node's provisioned capacity. Rising memory alongside CPU is consistent
with a process leaking memory under that same load rather than a
transient spike.

## Recovery Procedure

1. Confirm the node is still in the critical band (`cpu` >= 90% or
   `memory` >= 68%) and not already recovering.
2. Recommended action per the fault taxonomy: **restart_process_or_scale**
   -- restart the offending process to clear a runaway loop or memory
   leak; if the load is legitimate (not a leak), scale the workload to
   another node instead of restarting in place.
3. After the action, watch for `%SYS-5-CPUNORMAL` and `%SYS-5-MEMNORMAL`
   recovery lines and confirm both metrics settle back to baseline
   (~28% CPU / ~38% memory for a server-class node, per node-type
   baselines).
4. Because this fault is not marked critical, it does not require the
   same immediate escalation as BGP flap or packet loss -- follow the
   normal-priority human-approval flow before the restart/scale action
   is executed.
5. If CPU immediately climbs again after a restart, the load is likely
   legitimate rather than a leak; escalate for capacity planning rather
   than repeating the restart (see `general_troubleshooting.md`).
