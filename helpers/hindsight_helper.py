"""
Hindsight Integration Helper for Agent Zero.

This helper keeps the integration close to Hermes' lifecycle model:
one recall before a user turn is answered and one structured chatlog retain
after the final response. It avoids utility-model memory extraction and does
not create per-fragment memories.
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from agent import AgentContext

plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
vendor_dir = os.path.join(plugin_dir, "vendor")
Hindsight = None  # type: ignore[assignment]
HINDSIGHT_AVAILABLE = False


def _import_hindsight() -> bool:
    """Import hindsight_client, preferring the runtime venv over vendored deps."""
    global Hindsight, HINDSIGHT_AVAILABLE
    if HINDSIGHT_AVAILABLE and Hindsight is not None:
        return True

    try:
        from hindsight_client import Hindsight as ImportedHindsight
        Hindsight = ImportedHindsight
        HINDSIGHT_AVAILABLE = True
        return True
    except ImportError:
        pass

    if os.path.isdir(vendor_dir) and vendor_dir not in sys.path:
        # Fallback only. The vendored tree can be incomplete, so never let it
        # shadow the Agent Zero runtime packages on normal imports.
        sys.path.append(vendor_dir)
    try:
        from hindsight_client import Hindsight as ImportedHindsight
        Hindsight = ImportedHindsight
        HINDSIGHT_AVAILABLE = True
        return True
    except ImportError:
        Hindsight = None  # type: ignore[assignment]
        HINDSIGHT_AVAILABLE = False
        return False


_import_hindsight()

_reflect_cache: Dict[str, tuple] = {}

_DEFAULTS: Dict[str, Any] = {
    "hindsight_bank_id": "",
    "hindsight_bank_prefix": "a0",
    "hindsight_retain_enabled": True,
    "hindsight_recall_enabled": True,
    "hindsight_reflect_enabled": False,
    "hindsight_recall_max_tokens": 4096,
    "hindsight_recall_budget": "mid",
    "hindsight_reflect_budget": "low",
    "hindsight_reflect_max_tokens": 500,
    "hindsight_cache_ttl": 120,
    "hindsight_retain_context": "conversation between Agent Zero and the user",
    "hindsight_debug": False,
}

_GLOBAL_SETTINGS = {"hindsight_base_url", "hindsight_bank_prefix"}
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)(bearer)\s+[a-z0-9._~+/=-]{16,}"),
]


def _log(context: Optional["AgentContext"], msg: str, log_type: str = "info") -> None:
    try:
        if context and hasattr(context, "log"):
            context.log.log(type=log_type, heading=f"[Hindsight] {msg}")
        else:
            print(f"[Hindsight] {msg}")
    except Exception:
        print(f"[Hindsight] {msg}")


def _get_plugin_config(agent: Any) -> Dict[str, Any]:
    config: Dict[str, Any] = {}
    if agent is not None:
        try:
            from helpers.plugins import get_plugin_config
            config = get_plugin_config("a0_hindsight", agent=agent) or {}
            global_config = get_plugin_config("a0_hindsight", agent=agent, project_name="") or {}
            for key in _GLOBAL_SETTINGS:
                if key in global_config:
                    config[key] = global_config[key]
        except Exception as e:
            print(f"[HINDSIGHT DEBUG] _get_plugin_config() framework API failed: {type(e).__name__}: {e}")
            config = {}

    if not config or not config.get("hindsight_base_url"):
        try:
            config_path = os.path.join(plugin_dir, "config.json")
            if os.path.isfile(config_path):
                with open(config_path, "r") as f:
                    file_config = json.load(f)
                for key, value in file_config.items():
                    if key not in config:
                        config[key] = value
        except Exception as e:
            print(f"[HINDSIGHT DEBUG] _get_plugin_config() config.json fallback failed: {e}")

    for key, default in _DEFAULTS.items():
        if key not in config:
            config[key] = default
    return config


def _get_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_hindsight_client_available() -> bool:
    available = _import_hindsight()
    if available:
        _update_status_file_success()
    return available


def _update_status_file_success(context: Optional["AgentContext"] = None) -> None:
    try:
        status_file = os.path.join(plugin_dir, ".dependency_status.json")
        status_data = {
            "checked_at": _get_timestamp(),
            "hindsight_client": True,
            "warnings": [],
            "errors": [],
        }
        with open(status_file, "w") as f:
            json.dump(status_data, f, indent=2)
    except Exception as e:
        if context:
            _log(context, f"Could not update status file: {e}", "warning")


def _get_secret(key: str, default: str = "", context: Optional["AgentContext"] = None) -> str:
    try:
        from helpers.secrets import get_secrets_manager
        secrets_mgr = get_secrets_manager(context)
        secrets = secrets_mgr.load_secrets()
        return secrets.get(key, "").strip() or default
    except Exception as e:
        _log(context, f"Error loading secret {key}: {e}", "error")
        return default


def get_base_url(context: Optional["AgentContext"] = None, agent: Any = None) -> Optional[str]:
    url = os.environ.get("HINDSIGHT_BASE_URL", "").strip()
    if url:
        return url
    try:
        config = _get_plugin_config(agent)
        url = config.get("hindsight_base_url", "").strip()
        if url:
            return url
    except Exception as e:
        _log(context, f"Error reading plugin config: {e}", "debug")
    return None


def get_api_key(context: Optional["AgentContext"] = None) -> Optional[str]:
    key = _get_secret("HINDSIGHT_API_KEY", "", context)
    return key if key else None


def is_configured(context: Optional["AgentContext"] = None) -> bool:
    if not is_hindsight_client_available():
        return False
    agent = getattr(context, "agent0", None) if context else None
    return bool(get_base_url(context, agent))


def get_client(context: Optional["AgentContext"] = None) -> Optional[Any]:
    if not is_hindsight_client_available() or Hindsight is None:
        return None

    agent = getattr(context, "agent0", None) if context else None
    base_url = get_base_url(context, agent)
    if not base_url:
        return None

    api_key = get_api_key(context)
    try:
        kwargs: Dict[str, Any] = {"base_url": base_url}
        if api_key:
            kwargs["api_key"] = api_key
        client = Hindsight(**kwargs)
        _log(context, f"Connected to Hindsight at: {base_url}", "util")
        return client
    except Exception as e:
        _log(context, f"Client creation error: {e}", "error")
        return None


def close_client(client: Any) -> None:
    try:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


def get_bank_id(context: "AgentContext") -> str:
    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    explicit_id = config.get("hindsight_bank_id", "").strip()
    if explicit_id:
        return explicit_id

    prefix = config.get("hindsight_bank_prefix", "a0")
    project_name = None
    try:
        from helpers.projects import get_context_project_name
        project_name = get_context_project_name(context)
    except Exception:
        pass
    if not project_name:
        try:
            if hasattr(context, "project") and context.project:
                project_name = getattr(context.project, "name", None)
        except Exception:
            pass
    if project_name:
        return f"{prefix}-{project_name}"
    return f"{prefix}-default"


def _redact_secrets(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(lambda m: f"{m.group(1)}=[REDACTED]", redacted)
    return redacted


def _output_message_text(message: Dict[str, Any]) -> str:
    from helpers.history import output_text
    return output_text([message], ai_label="assistant", human_label="user").strip()


def _is_tool_result(message: Dict[str, Any]) -> bool:
    content = message.get("content")
    return isinstance(content, dict) and "tool_name" in content and "tool_result" in content


def build_chatlog(agent: Any) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for message in agent.history.output():
        if _is_tool_result(message):
            continue
        text = _redact_secrets(_output_message_text(message))
        if not text:
            continue
        entries.append({
            "role": "assistant" if message.get("ai") else "user",
            "content": text[:12000],
            "timestamp": _get_timestamp(),
        })
    return entries


def build_metadata(context: "AgentContext", agent: Any, message_count: int) -> Dict[str, str]:
    metadata = {
        "framework": "agent-zero",
        "session_id": str(getattr(context, "id", "")),
        "agent_name": str(getattr(agent, "agent_name", "")),
        "agent_profile": str(getattr(getattr(agent, "config", None), "profile", "")),
        "message_count": str(message_count),
        "retained_at": _get_timestamp(),
    }
    try:
        from helpers.projects import get_context_project_name
        project_name = get_context_project_name(context)
        if project_name:
            metadata["project"] = str(project_name)
    except Exception:
        pass
    return {key: value for key, value in metadata.items() if value}


async def retain_chatlog(context: "AgentContext", agent: Any) -> bool:
    if not is_configured(context):
        return False

    config = _get_plugin_config(agent)
    if not config.get("hindsight_retain_enabled", True):
        return False

    chatlog = build_chatlog(agent)
    if not chatlog:
        return False

    client = get_client(context)
    if not client:
        return False

    bank_id = get_bank_id(context)
    document_id = f"agent-zero:{getattr(context, 'id', 'default')}"
    item = {
        "content": json.dumps(chatlog, ensure_ascii=False),
        "context": config.get("hindsight_retain_context") or _DEFAULTS["hindsight_retain_context"],
        "metadata": build_metadata(context, agent, len(chatlog)),
        "tags": ["agent-zero", "chatlog"],
    }

    try:
        await client.aretain_batch(
            bank_id=bank_id,
            items=[item],
            document_id=document_id,
            document_tags=["agent-zero", "chatlog"],
            retain_async=True,
        )
        if config.get("hindsight_debug", False):
            _log(context, f"Retained chatlog to bank '{bank_id}' as '{document_id}'", "util")
        return True
    except Exception as e:
        _log(context, f"Retain chatlog error: {e}", "error")
        return False
    finally:
        close_client(client)


async def retain_memory(context: "AgentContext", content: str, metadata: Optional[Dict[str, str]] = None) -> bool:
    if not is_configured(context):
        return False
    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    if not config.get("hindsight_retain_enabled", True):
        return False

    client = get_client(context)
    if not client:
        return False

    bank_id = get_bank_id(context)
    try:
        kwargs: Dict[str, Any] = {
            "bank_id": bank_id,
            "content": _redact_secrets(content)[:10000],
            "context": config.get("hindsight_retain_context"),
            "tags": ["agent-zero", "manual"],
        }
        if metadata:
            kwargs["metadata"] = metadata
        await client.aretain(**kwargs)
        return True
    except Exception as e:
        _log(context, f"Retain error: {e}", "error")
        return False
    finally:
        close_client(client)


def _format_recall_result(result: Any) -> Optional[str]:
    if hasattr(result, "results"):
        results = getattr(result, "results", None) or []
        lines = []
        for idx, item in enumerate(results, 1):
            text = getattr(item, "text", None) or getattr(item, "content", None) or str(item)
            text = text.strip()
            if text:
                lines.append(f"{idx}. {text}")
        return "\n".join(lines) if lines else None

    for attr in ("content", "text", "response"):
        value = getattr(result, attr, None)
        if value:
            return str(value)
    result_str = str(result)
    return result_str if result_str and result_str != "None" else None


async def recall_memories(context: "AgentContext", query: str) -> Optional[str]:
    if not is_configured(context):
        return None

    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    if not config.get("hindsight_recall_enabled", True):
        return None

    safe_query = query.strip()[:1500] if query else ""
    if len(safe_query) < 3:
        return None

    client = get_client(context)
    if not client:
        return None
    bank_id = get_bank_id(context)

    try:
        result = await client.arecall(
            bank_id=bank_id,
            query=safe_query,
            max_tokens=config.get("hindsight_recall_max_tokens", 4096),
            budget=config.get("hindsight_recall_budget", "mid"),
        )
        return _format_recall_result(result)
    except Exception as e:
        error_msg = str(e)
        if "400" in error_msg or "Bad Request" in error_msg:
            _log(context, f"Recall 400 Bad Request: {error_msg[:200]}. Query length: {len(query) if query else 0}. Bank: {bank_id}", "warning")
        else:
            _log(context, f"Recall error: {error_msg}", "error")
        return None
    finally:
        close_client(client)


async def reflect_context(context: "AgentContext", query: str) -> Optional[str]:
    if not is_configured(context):
        return None

    agent0 = getattr(context, "agent0", None)
    config = _get_plugin_config(agent0)
    if not config.get("hindsight_reflect_enabled", False):
        return None

    bank_id = get_bank_id(context)
    cache_key = f"{bank_id}:{getattr(context, 'id', 'default')}"
    cache_ttl = config.get("hindsight_cache_ttl", 120)
    if cache_key in _reflect_cache:
        cached_time, cached_content = _reflect_cache[cache_key]
        if time.time() - cached_time < cache_ttl:
            return cached_content

    safe_query = query.strip()[:1500] if query else ""
    if not safe_query:
        return None

    client = get_client(context)
    if not client:
        return None

    try:
        result = await client.areflect(
            bank_id=bank_id,
            query=safe_query,
            budget=config.get("hindsight_reflect_budget", "low"),
            max_tokens=config.get("hindsight_reflect_max_tokens", 500),
        )
        content = getattr(result, "content", None) or getattr(result, "text", None) or getattr(result, "response", None)
        if not content:
            result_str = str(result)
            content = result_str if result_str and result_str != "None" else None
        _reflect_cache[cache_key] = (time.time(), content)
        return content
    except Exception as e:
        _log(context, f"Reflect error: {e}", "error")
        return None
    finally:
        close_client(client)


def clear_cache(bank_id: Optional[str] = None) -> None:
    global _reflect_cache
    if bank_id:
        for key in [k for k in _reflect_cache if k.startswith(f"{bank_id}:")]:
            del _reflect_cache[key]
    else:
        _reflect_cache = {}


def cleanup(context: Optional["AgentContext"] = None) -> None:
    if context:
        bank_id = get_bank_id(context)
        clear_cache(bank_id)
    else:
        clear_cache()
