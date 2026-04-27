"""
Optional Hindsight dreaming workflow for Agent Zero.

The workflow mirrors the standalone nightly script:
- refresh mental models only when bank stats changed enough to justify it
- wait for async refresh operations to finish
- store one clearly tagged dream-journal synthesis at most once per day

It is disabled by default and intended to replace host-level cron/systemd
scripts once enabled in the plugin config.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from . import hindsight_helper

TERMINAL_OPERATION_STATES = {"completed", "failed", "cancelled", "canceled"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_path() -> str:
    return os.path.join(hindsight_helper.plugin_dir, ".dreaming_state.json")


def load_state() -> dict[str, Any]:
    path = _state_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    with open(_state_path(), "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _api_base(base_url: str) -> str:
    base = (base_url or "").rstrip("/")
    if base.endswith("/v1/default"):
        return base
    if base.endswith("/v1"):
        return f"{base}/default"
    return f"{base}/v1/default"


def _headers(api_key: Optional[str]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-Key"] = api_key
    return headers


def _request_json(
    method: str,
    base_url: str,
    path: str,
    payload: Optional[dict[str, Any]] = None,
    api_key: Optional[str] = None,
    timeout: int = 120,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{_api_base(base_url)}{path}",
        data=body,
        method=method,
        headers=_headers(api_key),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {detail[:500]}") from error


def compact_stats(stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "total_documents": stats.get("total_documents"),
        "total_nodes": stats.get("total_nodes"),
        "total_observations": stats.get("total_observations"),
        "pending_consolidation": stats.get("pending_consolidation", 0),
        "last_consolidated_at": stats.get("last_consolidated_at"),
    }


def stats_unchanged(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    return (
        previous.get("total_documents") == current.get("total_documents")
        and previous.get("total_nodes") == current.get("total_nodes")
        and previous.get("total_observations") == current.get("total_observations")
        and int(current.get("pending_consolidation") or 0) == 0
    )


def due_for_run(config: dict[str, Any], state: dict[str, Any], force: bool = False) -> bool:
    if force:
        return True
    interval_hours = _as_int(config.get("hindsight_dreaming_interval_hours"), 24)
    if interval_hours <= 0:
        return True
    last_run = _parse_iso(str(state.get("last_run") or ""))
    if not last_run:
        return True
    return (_now() - last_run) >= timedelta(hours=interval_hours)


def _analysis_stored_today(state: dict[str, Any], today: str) -> bool:
    return any(item.get("date") == today for item in state.get("analysis_stored", []))


def _dedupe_analysis_stored(state: dict[str, Any]) -> None:
    latest_by_date: dict[str, dict[str, Any]] = {}
    for item in state.get("analysis_stored", []):
        if isinstance(item, dict) and item.get("date"):
            latest_by_date[str(item["date"])] = item
    state["analysis_stored"] = [latest_by_date[key] for key in sorted(latest_by_date)]


def _reflect_text(result: dict[str, Any]) -> str:
    text = str(result.get("text") or result.get("content") or "").strip()
    return "" if text.lower() == "no answer provided." else text


def _wait_for_operation(
    base_url: str,
    bank_id: str,
    operation_id: str,
    api_key: Optional[str],
    timeout_seconds: int,
    poll_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_result: dict[str, Any] = {}
    while time.monotonic() < deadline:
        result = _request_json(
            "GET",
            base_url,
            f"/banks/{bank_id}/operations/{operation_id}",
            api_key=api_key,
            timeout=60,
        )
        last_result = result
        status = str(result.get("status") or "").lower()
        if status in TERMINAL_OPERATION_STATES:
            return result
        time.sleep(max(1, poll_seconds))
    last_result["status"] = last_result.get("status") or "timeout"
    return last_result


def _dream_query() -> str:
    return (
        "You are the nightly 'dreaming' process for a personal memory system.\n\n"
        "Review source memories from the past 7 days and produce a concise dream-journal entry covering:\n"
        "1. Emerging patterns or recurring themes\n"
        "2. Unresolved questions or contradictions\n"
        "3. Notable decisions, commitments, or deadlines approaching\n"
        "4. One hypothesis about what the user might need next\n\n"
        "Ignore prior dream-journal entries and any memory tagged source:dreaming or type:dream-journal; "
        "those are meta-observations, not source facts.\n\n"
        "Keep it under 300 words. Be specific, not generic. "
        "This is a meta-level observation and must not replace native observation consolidation."
    )


def run_dreaming(context: Any = None, agent: Any = None, force: bool = False) -> dict[str, Any]:
    config = hindsight_helper._get_plugin_config(agent)
    if not force and not config.get("hindsight_dreaming_enabled", False):
        return {"ok": True, "skipped": True, "reason": "disabled"}

    base_url = hindsight_helper.get_base_url(context, agent)
    if not base_url:
        return {"ok": False, "error": "missing Hindsight base URL"}

    bank_id = hindsight_helper.get_bank_id(context)
    api_key = hindsight_helper.get_api_key(context)
    state = load_state()
    state.pop("topic_detection", None)
    if not due_for_run(config, state, force=force):
        return {"ok": True, "skipped": True, "reason": "not due"}

    now = _now()
    today = now.strftime("%Y-%m-%d")
    state["last_run"] = now.isoformat()
    state["errors"] = []

    min_refresh_age = _as_int(config.get("hindsight_dreaming_min_model_refresh_age_hours"), 12)
    operation_timeout = _as_int(config.get("hindsight_dreaming_operation_timeout_seconds"), 900)
    poll_seconds = _as_int(config.get("hindsight_dreaming_poll_seconds"), 5)

    stats = compact_stats(_request_json("GET", base_url, f"/banks/{bank_id}/stats", api_key=api_key, timeout=60))
    no_change = stats_unchanged(state.get("last_stats", {}), stats)
    last_consolidated_at = _parse_iso(str(stats.get("last_consolidated_at") or ""))

    refreshed: list[dict[str, Any]] = []
    models = _request_json("GET", base_url, f"/banks/{bank_id}/mental-models", api_key=api_key, timeout=60).get("items", [])
    for model in models if isinstance(models, list) else []:
        model_id = str(model.get("id") or "")
        name = str(model.get("name") or model_id)
        if not model_id:
            continue
        last_refreshed_at = _parse_iso(str(model.get("last_refreshed_at") or ""))
        skip_reason = None
        if no_change:
            skip_reason = "no new memories since last run"
        elif last_refreshed_at and (_now() - last_refreshed_at) < timedelta(hours=min_refresh_age):
            skip_reason = f"refreshed less than {min_refresh_age}h ago"
        elif (
            int(stats.get("pending_consolidation") or 0) == 0
            and last_refreshed_at
            and last_consolidated_at
            and last_refreshed_at >= last_consolidated_at
        ):
            skip_reason = "model newer than last consolidation"

        if skip_reason:
            refreshed.append({"id": model_id, "name": name, "ok": True, "skipped": True, "reason": skip_reason})
            continue

        try:
            result = _request_json(
                "POST",
                base_url,
                f"/banks/{bank_id}/mental-models/{model_id}/refresh",
                payload={},
                api_key=api_key,
                timeout=120,
            )
            operation_id = result.get("operation_id") or result.get("id")
            if operation_id and config.get("hindsight_dreaming_wait_for_refresh", True):
                operation_status = _wait_for_operation(
                    base_url,
                    bank_id,
                    str(operation_id),
                    api_key,
                    operation_timeout,
                    poll_seconds,
                )
                status = str(operation_status.get("status") or "").lower()
                if status != "completed":
                    raise RuntimeError(f"refresh operation ended with status={status or 'unknown'}")
            refreshed.append({
                "id": model_id,
                "name": name,
                "ok": True,
                "skipped": False,
                "operation_id": operation_id,
                "timestamp": _now().isoformat(),
            })
        except Exception as exc:
            refreshed.append({
                "id": model_id,
                "name": name,
                "ok": False,
                "skipped": False,
                "error": str(exc),
                "timestamp": _now().isoformat(),
            })
            state["errors"].append({"phase": "refresh_model", "model": name, "error": str(exc)})

    refreshed_count = len([item for item in refreshed if item.get("ok") and not item.get("skipped")])
    state["models_refreshed"] = refreshed
    state["last_stats"] = stats
    state["last_refresh_success_count"] = refreshed_count

    synthesis_enabled = config.get("hindsight_dreaming_synthesis_enabled", True)
    last_synthesis_stats = state.get("last_synthesis_stats", {})
    synthesis_unchanged = (
        last_synthesis_stats.get("total_documents") == stats.get("total_documents")
        and last_synthesis_stats.get("total_nodes") == stats.get("total_nodes")
        and last_synthesis_stats.get("total_observations") == stats.get("total_observations")
    )
    if not synthesis_enabled:
        state["last_result"] = "refreshed-only"
        save_state(state)
        return {"ok": len(state["errors"]) == 0, "refreshed": refreshed_count, "synthesized": False}
    if _analysis_stored_today(state, today) and not force:
        state["last_result"] = "synthesis-skipped-existing-today"
        save_state(state)
        return {"ok": len(state["errors"]) == 0, "refreshed": refreshed_count, "synthesized": False}
    if synthesis_unchanged and refreshed_count == 0 and not force:
        state["last_result"] = "synthesis-skipped-no-change"
        save_state(state)
        return {"ok": len(state["errors"]) == 0, "refreshed": refreshed_count, "synthesized": False}

    doc_id = f"dream-analysis-{today}"
    try:
        reflect_payload = {
            "query": _dream_query(),
            "budget": config.get("hindsight_dreaming_synthesis_budget", "mid"),
            "max_tokens": _as_int(config.get("hindsight_dreaming_synthesis_max_tokens"), 2048),
            "tags": [],
        }
        result = _request_json("POST", base_url, f"/banks/{bank_id}/reflect", reflect_payload, api_key=api_key, timeout=300)
        text = _reflect_text(result)
        if not text:
            reflect_payload["budget"] = "high"
            result = _request_json("POST", base_url, f"/banks/{bank_id}/reflect", reflect_payload, api_key=api_key, timeout=300)
            text = _reflect_text(result)
        if not text:
            raise RuntimeError("Reflect returned no synthesis text")

        tags = [
            "source:dreaming",
            "type:analysis",
            "type:dream-journal",
            "agent-zero",
            "source:agent-zero",
            *hindsight_helper._shared_tags(config),
        ]
        tags = list(dict.fromkeys(tags))
        _request_json(
            "POST",
            base_url,
            f"/banks/{bank_id}/memories",
            {
                "items": [{
                    "content": f"## Nightly Dreaming Synthesis ({today})\n\n{text}",
                    "document_id": doc_id,
                    "context": "Nightly dreaming synthesis - meta-level journal entry; do not use as source fact",
                    "tags": tags,
                    "metadata": {
                        "source": "agent-zero",
                        "memory_area": "dreaming",
                        "synthesized_at": _now().isoformat(),
                    },
                }],
                "async": False,
            },
            api_key=api_key,
            timeout=300,
        )
        state.setdefault("analysis_stored", []).append({
            "date": today,
            "document_id": doc_id,
            "timestamp": _now().isoformat(),
        })
        state["last_synthesis_stats"] = stats
        state["last_result"] = "synthesis-stored"
        _dedupe_analysis_stored(state)
        save_state(state)
        return {"ok": len(state["errors"]) == 0, "refreshed": refreshed_count, "synthesized": True, "document_id": doc_id}
    except Exception as exc:
        state["errors"].append({"phase": "synthesis", "error": str(exc)})
        state["last_result"] = "synthesis-error"
        save_state(state)
        return {"ok": False, "refreshed": refreshed_count, "synthesized": False, "error": str(exc)}
