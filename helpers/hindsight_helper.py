"""
Hindsight Integration Helper for Agent Zero.

This helper keeps the integration close to Hermes' lifecycle model:
one recall before a user turn is answered and one structured chatlog retain
after the final response. It avoids utility-model memory extraction and does
not create per-fragment memories.
"""
import hashlib
import json
import os
import re
import sys
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


_DEFAULTS: Dict[str, Any] = {
    "hindsight_bank_id": "",
    "hindsight_bank_prefix": "a0",
    "hindsight_retain_enabled": True,
    "hindsight_recall_enabled": True,
    "hindsight_recall_max_tokens": 4096,
    "hindsight_recall_budget": "mid",
    "hindsight_retain_context": "conversation between Agent Zero and the user",
    "hindsight_retain_min_messages": 3,
    "hindsight_retain_min_chars": 800,
    "hindsight_scheduler_task_log_enabled": True,
    "hindsight_scheduler_task_context": "Agent Zero scheduled task execution result",
    "hindsight_operation_logging": True,
    "hindsight_solution_extract_enabled": False,
    "hindsight_solution_extract_min_tool_calls": 1,
    "hindsight_solution_extract_min_chars": 1200,
    "hindsight_solution_extract_max_history_chars": 80000,
    "hindsight_solution_context": "successful Agent Zero task outcome / reusable solution",
    "hindsight_debug": False,
}

_GLOBAL_SETTINGS = {"hindsight_base_url", "hindsight_bank_prefix"}
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd)\s*\(([^)\s]{12,})\)"),
    re.compile(r"(?i)(bearer)\s+[a-z0-9._~+/=-]{16,}"),
    re.compile(r"\b(am_[a-zA-Z0-9_]{24,})\b"),
]


def _debug_enabled(context: Optional["AgentContext"] = None) -> bool:
    agent = getattr(context, "agent0", None) if context else None
    return bool(_get_plugin_config(agent).get("hindsight_debug", False))


def _log(
    context: Optional["AgentContext"],
    msg: str,
    log_type: str = "info",
    debug_only: bool = False,
) -> None:
    if debug_only and not _debug_enabled(context):
        return
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
    return _import_hindsight()


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
        return Hindsight(**kwargs)
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
        def repl(match):
            if match.lastindex and match.lastindex >= 2:
                return f"{match.group(1)}=[REDACTED]"
            return "[REDACTED]"
        redacted = pattern.sub(repl, redacted)
    return redacted


def _normalize_task_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _scheduler_tasks_path() -> str:
    usr_dir = os.path.dirname(os.path.dirname(plugin_dir))
    return os.path.join(usr_dir, "scheduler", "tasks.json")


def _load_scheduler_tasks() -> list[Dict[str, Any]]:
    try:
        with open(_scheduler_tasks_path(), "r") as f:
            data = json.load(f)
        tasks = data.get("tasks", []) if isinstance(data, dict) else []
        return tasks if isinstance(tasks, list) else []
    except Exception:
        return []


def _current_user_text(loop_data: Any = None) -> str:
    user_message = getattr(loop_data, "user_message", None) if loop_data else None
    if not user_message:
        return ""
    try:
        return user_message.output_text().strip()
    except Exception:
        return str(user_message or "").strip()


def get_scheduled_task_for_text(context: "AgentContext", user_text: str) -> Optional[Dict[str, Any]]:
    user_text = re.sub(r"(?i)^\s*(user|human):\s*", "", user_text or "").strip()
    if not user_text.startswith("## Task"):
        return None

    context_id = str(getattr(context, "id", "") or "")
    normalized_user = _normalize_task_text(user_text.replace("## Task:", "", 1))
    for task in _load_scheduler_tasks():
        if not isinstance(task, dict):
            continue
        prompt = _normalize_task_text(str(task.get("prompt") or ""))
        if not prompt:
            continue
        same_context = context_id and str(task.get("context_id") or "") == context_id
        prompt_matches = prompt in normalized_user or normalized_user in prompt
        if same_context and prompt_matches:
            return task

    digest = hashlib.sha256(normalized_user.encode("utf-8")).hexdigest()[:12]
    return {
        "uuid": f"prompt-{digest}",
        "context_id": context_id,
        "name": "scheduled-task",
        "type": "scheduled",
        "prompt": user_text.replace("## Task:", "", 1).strip(),
        "schedule": {},
    }


def get_scheduled_task(context: "AgentContext", loop_data: Any = None) -> Optional[Dict[str, Any]]:
    """Return the scheduler task for the current turn, if this turn is a scheduled run."""
    return get_scheduled_task_for_text(context, _current_user_text(loop_data))


def get_latest_scheduled_task(context: "AgentContext", agent: Any) -> Optional[Dict[str, Any]]:
    try:
        messages = list(agent.history.output())
    except Exception:
        messages = []
    for message in reversed(messages):
        if not message.get("ai"):
            task = get_scheduled_task_for_text(context, _message_text(message).strip())
            if task:
                return task
            return None
    return None


def is_scheduled_task_turn(context: "AgentContext", loop_data: Any = None, agent: Any = None) -> bool:
    if get_scheduled_task(context, loop_data) is not None:
        return True
    return bool(agent and get_latest_scheduled_task(context, agent))


def _last_response_text(agent: Any) -> str:
    try:
        messages = list(agent.history.output())
    except Exception:
        messages = []
    for message in reversed(messages):
        if message.get("ai") and not _is_tool_result(message):
            text = _assistant_final_text(message)
            if text:
                return text[:12000]
    return ""


def _recent_task_errors(agent: Any) -> list[str]:
    errors_found: list[str] = []
    try:
        messages = list(agent.history.output())
    except Exception:
        messages = []
    start_index = 0
    for index, message in enumerate(messages):
        if not message.get("ai"):
            text = _message_text(message)
            if text.strip().startswith("## Task"):
                start_index = index
    for message in messages[start_index:]:
        text = _message_text(message) if not message.get("ai") else (_assistant_final_text(message) or _message_text(message))
        lowered = text.lower()
        if any(marker in lowered for marker in ("traceback", "exception", "error", "failed", "runtimeerror")):
            redacted = _redact_secrets(text).strip()
            if redacted:
                errors_found.append(redacted[:2000])
    return errors_found[-5:]


def _format_schedule(schedule: Any) -> str:
    if not isinstance(schedule, dict):
        return ""
    parts = []
    for key in ("minute", "hour", "day", "month", "weekday", "timezone"):
        value = schedule.get(key)
        if value not in (None, ""):
            parts.append(f"{key}={value}")
    return ", ".join(parts)


def build_scheduled_task_log(context: "AgentContext", agent: Any, task: Dict[str, Any]) -> str:
    result = _last_response_text(agent) or str(task.get("last_result") or "").strip()
    recent_errors = _recent_task_errors(agent)
    status = "error" if recent_errors and not result else "completed_with_errors" if recent_errors else "completed"
    lines = [
        "# Agent Zero scheduled task log",
        f"Task: {task.get('name') or 'unknown'}",
        f"Task ID: {task.get('uuid') or 'unknown'}",
        f"Type: {task.get('type') or 'scheduled'}",
        f"Context ID: {getattr(context, 'id', '')}",
        f"Schedule: {_format_schedule(task.get('schedule'))}",
        f"Last observed run: {_get_timestamp()}",
        f"Status: {status}",
        "",
        "## Prompt",
        _redact_secrets(str(task.get("prompt") or "")).strip(),
        "",
        "## Latest result",
        result or "No final response was recorded.",
    ]
    if recent_errors:
        lines.extend(["", "## Recent errors or warnings"])
        for item in recent_errors:
            lines.extend(["- " + item.replace("\n", " ")])
    return "\n".join(line for line in lines if line is not None).strip()


def _output_message_text(message: Dict[str, Any]) -> str:
    from helpers.history import output_text
    return output_text([message], ai_label="assistant", human_label="user").strip()


def _strip_role_prefix(text: str) -> str:
    return re.sub(r"(?i)^\s*(assistant|ai|user|human):\s*", "", text or "").strip()


def _message_text(message: Dict[str, Any]) -> str:
    return _strip_role_prefix(_output_message_text(message))


def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    text = _strip_role_prefix(text)
    if not text.startswith("{"):
        return None
    try:
        value = json.loads(text)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def _assistant_final_text(message: Dict[str, Any]) -> str:
    content = message.get("content")
    payload = content if isinstance(content, dict) else None
    if payload is None and isinstance(content, str):
        payload = _parse_json_object(content)

    if isinstance(payload, dict):
        tool_name = str(payload.get("tool_name") or "").strip()
        tool_args = payload.get("tool_args")
        if tool_name == "response" and isinstance(tool_args, dict):
            text = str(tool_args.get("text") or "").strip()
            return _redact_secrets(text) if text else ""
        return ""

    text = _message_text(message)
    if not text or text.startswith("{"):
        return ""
    return _redact_secrets(text)


def _is_tool_result(message: Dict[str, Any]) -> bool:
    content = message.get("content")
    return isinstance(content, dict) and "tool_name" in content and "tool_result" in content


def tool_names(messages: list[Dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, dict) and "tool_name" in content:
            name = str(content.get("tool_name") or "").strip()
            if name:
                names.append(name)
    return names


def _tag_safe(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.:-]+", "-", value.strip().lower()).strip("-")
    return cleaned[:64] or "unknown"


def build_chatlog(agent: Any) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    skip_scheduled_turn = False
    context = getattr(agent, "context", None)
    for message in agent.history.output():
        if not message.get("ai"):
            raw_text = _message_text(message).strip()
            skip_scheduled_turn = bool(
                context and get_scheduled_task_for_text(context, raw_text)
            )
            if skip_scheduled_turn:
                continue
            role = "user"
            text = _redact_secrets(raw_text)
        else:
            if skip_scheduled_turn:
                continue
            role = "assistant"
            text = _assistant_final_text(message)

        if _is_tool_result(message):
            continue
        if not text:
            continue
        entries.append({
            "role": role,
            "content": text[:12000],
            "timestamp": _get_timestamp(),
        })
    return entries


def chatlog_char_count(chatlog: list[dict[str, str]]) -> int:
    return sum(len(entry.get("content", "")) for entry in chatlog)


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


async def retain_scheduled_task_log(
    context: "AgentContext",
    agent: Any,
    task: Dict[str, Any],
) -> bool:
    if not is_configured(context):
        return False

    config = _get_plugin_config(agent)
    if not config.get("hindsight_retain_enabled", True):
        return False
    if not config.get("hindsight_scheduler_task_log_enabled", True):
        return False

    client = get_client(context)
    if not client:
        return False

    bank_id = get_bank_id(context)
    task_id = str(task.get("uuid") or getattr(context, "id", "default"))
    document_id = f"agent-zero:scheduled-task:{task_id}"
    content = _redact_secrets(build_scheduled_task_log(context, agent, task))[:12000]
    metadata = build_metadata(context, agent, 1)
    metadata.update({
        "memory_area": "scheduled-tasks",
        "task_id": task_id,
        "task_name": str(task.get("name") or ""),
        "task_type": str(task.get("type") or "scheduled"),
    })

    try:
        if config.get("hindsight_operation_logging", True):
            _log(context, f"Retain scheduled task log to bank '{bank_id}'", "util")
        await client.aretain(
            bank_id=bank_id,
            content=content,
            context=config.get("hindsight_scheduler_task_context") or _DEFAULTS["hindsight_scheduler_task_context"],
            document_id=document_id,
            metadata=metadata,
            tags=["agent-zero", "scheduled-task", f"task:{_tag_safe(task_id)}"],
        )
        return True
    except Exception as e:
        _log(context, f"Retain scheduled task log error: {e}", "error")
        return False
    finally:
        close_client(client)


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
        if config.get("hindsight_operation_logging", True):
            _log(context, f"Retain chatlog to bank '{bank_id}'", "util")
        await client.aretain_batch(
            bank_id=bank_id,
            items=[item],
            document_id=document_id,
            document_tags=["agent-zero", "chatlog"],
            retain_async=True,
        )
        if config.get("hindsight_debug", False):
            _log(
                context,
                f"Retained chatlog to bank '{bank_id}' as '{document_id}'",
                "util",
                debug_only=True,
            )
        return True
    except Exception as e:
        _log(context, f"Retain chatlog error: {e}", "error")
        return False
    finally:
        close_client(client)


def _format_solution(solution: Any) -> str:
    if isinstance(solution, dict):
        problem = str(solution.get("problem") or "Unknown problem").strip()
        solution_text = str(solution.get("solution") or solution.get("steps") or "Unknown solution").strip()
        caveats = str(solution.get("caveats") or "").strip()
        parts = [
            "# Problem",
            problem,
            "",
            "# Solution",
            solution_text,
        ]
        if caveats:
            parts.extend(["", "# Caveats", caveats])
        return "\n".join(parts).strip()
    return f"# Solution\n{str(solution).strip()}"


def _solution_document_id(solution_text: str) -> str:
    digest = hashlib.sha256(solution_text.encode("utf-8")).hexdigest()[:16]
    return f"agent-zero:solution:{digest}"


async def retain_solution(
    context: "AgentContext",
    agent: Any,
    solution: Any,
    tool_names_used: Optional[list[str]] = None,
) -> bool:
    if not is_configured(context):
        return False

    config = _get_plugin_config(agent)
    if not config.get("hindsight_solution_extract_enabled", False):
        return False

    text = _redact_secrets(_format_solution(solution))[:12000]
    if len(text.strip()) < 20:
        return False

    client = get_client(context)
    if not client:
        return False

    bank_id = get_bank_id(context)
    tools = sorted(set(tool_names_used or []))
    tool_tags = [f"tool:{_tag_safe(name)}" for name in tools[:8]]
    tags = ["agent-zero", "solution", "workflow", *tool_tags]
    metadata = build_metadata(context, agent, 1)
    metadata.update({
        "memory_area": "solutions",
        "solution_source": "agent-zero-utility-extraction",
        "tools": ", ".join(tools[:20]),
    })

    try:
        if config.get("hindsight_operation_logging", True):
            _log(context, f"Retain solution to bank '{bank_id}'", "util")
        await client.aretain(
            bank_id=bank_id,
            content=text,
            context=config.get("hindsight_solution_context") or _DEFAULTS["hindsight_solution_context"],
            document_id=_solution_document_id(text),
            metadata=metadata,
            tags=tags,
        )
        return True
    except Exception as e:
        _log(context, f"Retain solution error: {e}", "error")
        return False
    finally:
        close_client(client)


async def retain_solutions(
    context: "AgentContext",
    agent: Any,
    solutions: list[Any],
    tool_names_used: Optional[list[str]] = None,
) -> int:
    retained = 0
    for solution in solutions:
        if await retain_solution(context, agent, solution, tool_names_used):
            retained += 1
    return retained


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
        if config.get("hindsight_operation_logging", True):
            _log(context, f"Recall from bank '{bank_id}'", "util")
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
