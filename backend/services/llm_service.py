"""
services/llm_service.py

Thin HTTP client for the local Ollama runtime (http://127.0.0.1:11434,
model gemma3:4b). generate_json() is the only entry point: it calls the
model in JSON mode with a capped output length (num_predict), validates
the response against the copilot's answer schema, and retries once with a
stricter instruction on a parse/schema failure. Returns None if Ollama is
unreachable, or if both attempts fail -- callers (routers/copilot.py) must
treat None as "fall back to the deterministic template", never surface a
raw error or a blank response to the UI.

keep_alive is set generously (30m) so the model stays resident in memory
between demo queries instead of unloading after Ollama's 5-minute default
and paying a ~1-20s reload penalty on the next call.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

import requests

logger = logging.getLogger("llm_service")

OLLAMA_URL = "http://127.0.0.1:11434"
GENERATE_MODEL = "gemma3:4b"
REQUEST_TIMEOUT_SECONDS = 45
KEEP_ALIVE = "30m"
NUM_PREDICT = 350
TEMPERATURE = 0.1

REQUIRED_KEYS = ("summary", "root_cause", "risk", "affected_component", "recommended_action", "confidence")

# gemma3:4b sometimes ignores the "number 0-1" instruction and answers with
# a qualitative label instead; coerce those rather than treating the whole
# response as unparseable and burning a retry.
_QUALITATIVE_SCORES = {
    "critical": 0.9,
    "high": 0.85,
    "elevated": 0.6,
    "medium": 0.5,
    "moderate": 0.5,
    "low": 0.2,
    "minimal": 0.1,
    "none": 0.0,
    "n/a": 0.0,
}


def _coerce_score(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _QUALITATIVE_SCORES:
            return _QUALITATIVE_SCORES[text]
        try:
            numeric = float(text.rstrip("%"))
            if text.endswith("%"):
                numeric /= 100.0
            return max(0.0, min(1.0, numeric))
        except ValueError:
            return None
    return None


def _validate(data) -> Optional[dict]:
    if not isinstance(data, dict) or not all(key in data for key in REQUIRED_KEYS):
        return None
    risk = _coerce_score(data.get("risk"))
    confidence = _coerce_score(data.get("confidence"))
    if risk is None or confidence is None:
        return None
    return {
        "summary": str(data["summary"]),
        "root_cause": str(data["root_cause"]),
        "risk": risk,
        "affected_component": str(data["affected_component"]),
        "recommended_action": str(data["recommended_action"]),
        "confidence": confidence,
    }


def _try_parse(raw: str) -> Optional[dict]:
    try:
        return _validate(json.loads(raw))
    except json.JSONDecodeError:
        return None


def _call_ollama(prompt: str) -> Optional[str]:
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": GENERATE_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "keep_alive": KEEP_ALIVE,
                "options": {"temperature": TEMPERATURE, "num_predict": NUM_PREDICT},
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json().get("response")
    except requests.RequestException:
        logger.warning("Ollama unreachable at %s; caller must fall back", OLLAMA_URL, exc_info=True)
        return None


def generate_json(prompt: str) -> Optional[dict]:
    """
    Calls gemma3:4b in JSON mode and returns a validated dict, or None if
    Ollama is unreachable (no retry -- a second call would just time out
    again) or if two attempts both fail to produce valid, schema-matching
    JSON.
    """
    raw = _call_ollama(prompt)
    if raw is None:
        return None

    parsed = _try_parse(raw)
    if parsed is not None:
        return parsed

    logger.warning("gemma3:4b response failed JSON/schema validation; retrying with a stricter instruction")
    strict_prompt = (
        f"{prompt}\n\nSTRICT: your previous response was not valid JSON. Respond with ONLY a single "
        "valid minified JSON object matching the schema above. No markdown, no code fences, no text "
        "before or after the JSON."
    )
    raw_retry = _call_ollama(strict_prompt)
    if raw_retry is None:
        return None

    parsed_retry = _try_parse(raw_retry)
    if parsed_retry is None:
        logger.warning("gemma3:4b response still invalid after retry; falling back to the deterministic template")
    return parsed_retry
