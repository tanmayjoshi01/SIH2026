"""
services/alerting.py

Optional webhook stub: fires a POST when an incident reaches "critical"
severity, so the demo can show "the system paged someone" without standing
up real alerting infra. ALERT_WEBHOOK_URL unset (the default) is a no-op --
most demo runs won't set it.

Called synchronously from inside incident_manager.py's tick-time
processing, so a slow or unreachable endpoint must never raise or hang
the telemetry loop: a short timeout and a blanket log-and-continue around
the request are both intentional. This is a demo stub, not production
alerting (no retries, no delivery guarantees, no auth).
"""

from __future__ import annotations

import logging

import httpx

from config import settings

logger = logging.getLogger("alerting")


def send_critical_alert(incident) -> None:
    url = settings.alert_webhook_url
    if not url:
        return

    payload = {
        "incident_id": incident.id,
        "node_id": incident.node_id,
        "status": incident.status,
        "severity": incident.severity,
        "peak_anomaly_score": incident.peak_anomaly_score,
        "root_cause_signal": incident.root_cause_signal,
        "opened_at": incident.opened_at.isoformat() if incident.opened_at else None,
    }
    try:
        response = httpx.post(url, json=payload, timeout=settings.alert_webhook_timeout_seconds)
        response.raise_for_status()
    except Exception:
        logger.exception("Alert webhook POST to %s failed for incident %s; continuing", url, incident.id)
