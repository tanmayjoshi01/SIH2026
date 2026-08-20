---
title: Packet Loss / Link Degradation
subsystem: network
severity: critical
---

## Symptoms

A node's uplink starts dropping packets and the generator logs threshold
crossings as loss climbs into the warning and critical bands:

```
%IF-4-PKTLOSS_WARN: router-7: packet loss at 6.8% on uplink to switch-4
%IF-1-PKTLOSS_CRIT: router-7: packet loss at 17.2% on uplink to switch-4 - link degraded
```

The same fault profile also ramps interface errors and round-trip latency
on the same node, so expect these alongside the packet-loss lines:

```
%IF-4-ERRWARN: router-7: interface error count at 34 - above warning threshold
%IF-2-ERRCRIT: router-7: interface error count at 96 - CRC/input errors climbing rapidly
%QOS-4-LATENCY_WARN: router-7: round-trip latency at 27.5ms - above baseline
%QOS-2-LATENCY_CRIT: router-7: round-trip latency at 44.0ms - SLA breach
```

Recovery is logged the same way once the link clears:

```
%IF-5-LINKUP: router-7: packet loss recovered to 0.4% on uplink to switch-4
%IF-5-ERRCLEAR: router-7: interface error count back to 0 - nominal
%QOS-5-LATENCY_OK: router-7: round-trip latency back to 8.2ms - nominal
```

## Diagnosis

- `packet_loss` crosses warning at 5.0% and critical at 15.0% -- a
  materially higher critical threshold than the packet loss seen as a
  side effect of a BGP flap (5.0%), so >15% loss with rapidly climbing
  interface errors is this fault, not a flap.
- `interface_errors` crosses warning at 30 and critical at 90 -- climbing
  CRC/input errors is the strongest corroborating signal that this is a
  physical/link-layer problem rather than a routing problem.
- `latency_ms` crosses warning at 25ms and critical at 40ms, higher
  thresholds than the BGP-flap profile's latency bands, consistent with a
  degraded physical link rather than a routing reconvergence delay.
- This fault type is registered as **critical** in the fault taxonomy with
  a minimum recommendation confidence of 0.70.

## Root Cause

Physical or link-layer degradation on the uplink -- a failing transceiver,
a marginal cable/satellite link, or congestion overrunning buffers on the
interface. The climbing interface-error count is the key differentiator
from a BGP-flap-induced packet loss: BGP flap loss comes from routing
churn with clean interface counters, while this fault shows the interface
itself accumulating errors as loss climbs.

## Recovery Procedure

1. Confirm the link is still degraded (`packet_loss` >= 15% or
   `interface_errors` >= 90, with errors still climbing).
2. Recommended action per the fault taxonomy: **reroute_traffic** -- shift
   traffic off the degraded uplink onto a healthy alternate path while the
   physical link issue is investigated out-of-band; do not wait for the
   link to self-heal, since climbing CRC errors indicate a hardware or
   cabling problem rather than a transient condition.
3. After rerouting, watch for `%IF-5-LINKUP`, `%IF-5-ERRCLEAR`, and
   `%QOS-5-LATENCY_OK` recovery lines on the original link before
   considering it safe to route traffic back.
4. This fault is marked critical -- page the on-call operator immediately
   and require human approval before the reroute is executed.
5. If loss and interface errors do not clear after rerouting away from the
   link, the fault is likely hardware-level (transceiver/cable) and needs
   physical inspection -- escalate per `general_troubleshooting.md` rather
   than repeating the reroute.
