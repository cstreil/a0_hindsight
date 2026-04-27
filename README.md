# Hindsight Memory Plugin for Agent Zero

This fork connects Agent Zero to [Hindsight](https://github.com/vectorize-io/hindsight) with a deliberately small memory lifecycle:

```text
user turn -> one Hindsight recall -> fenced temporary context -> final response -> structured chatlog retain
```

The plugin avoids plugin-side memory-fragment extraction for normal conversation. It sends clean, structured conversation logs to Hindsight and lets Hindsight do its own extraction and consolidation.

## Core Behavior

### Recall

- Runs at most once per user message.
- Uses the clean user message as the recall query.
- Injects results as temporary fenced context in `<memory-context>`.
- Does not write recalled memory back into Agent Zero history.
- Skips scheduled task turns.

### Chatlog Retain

- Retains one structured chatlog document per Agent Zero session with `retain_batch`.
- Uses stable document IDs: `agent-zero:<context-id>`.
- Stores user-visible conversation only:
  - user messages
  - final assistant responses
- Excludes Agent Zero `thoughts`, planning JSON, tool choices, and tool result messages.
- Redacts common secret patterns before retain.
- Skips scheduled task turns.

Retain is throttled by message and character thresholds:

```yaml
hindsight_retain_min_messages: 3
hindsight_retain_min_chars: 800
```

Retain runs when either threshold is reached since the last successful retain. Set both to `0` to retain after every eligible turn.

### Scheduled Task Logs

Scheduled task turns do not receive memory context and are not retained as ordinary chatlog entries. Instead, the plugin can retain one stable task-result document per scheduled task.

```yaml
hindsight_scheduler_task_log_enabled: true
hindsight_scheduler_task_context: "Agent Zero scheduled task execution result"
```

The document ID uses the scheduler task UUID when available and falls back to a stable prompt hash.

### Optional Solution Extraction

Solution extraction is disabled by default. When enabled, it is gated so the utility model is only called after substantive tool-backed work.

```yaml
hindsight_solution_extract_enabled: false
hindsight_solution_extract_min_tool_calls: 1
hindsight_solution_extract_min_chars: 1200
```

Extracted solutions are retained with tags such as:

```text
agent-zero
solution
workflow
tool:<tool-name>
```

## Removed Scope

This fork intentionally does not include Hindsight Reflect prompt injection. Recall plus structured retain is the supported default path. Reflect can be evaluated separately later, but it is not part of this lean plugin lifecycle.

## Manual Installation

This branch is not intended to be installed from the Plugin Hub. For manual testing:

```bash
cd /path/to/agent-zero/usr/plugins
git clone -b codex/hermes-style-chatlog-lifecycle \
  https://github.com/cstreil/a0_hindsight.git \
  a0_hindsight
```

Then restart Agent Zero, enable the plugin, and configure:

- Hindsight Base URL
- Explicit Bank ID or Bank ID Prefix
- Enable Recall
- Enable Chatlog Retain
- optionally Enable Solution Extraction

Make sure the Agent Zero container can reach the Hindsight server URL.

## Settings

| Setting | Default | Purpose |
|---------|---------|---------|
| `hindsight_base_url` | empty | Hindsight API server URL. Can also be set with `HINDSIGHT_BASE_URL`. |
| `hindsight_bank_id` | empty | Explicit bank ID override. |
| `hindsight_bank_prefix` | `a0` | Prefix for derived bank IDs when no explicit bank is set. |
| `hindsight_recall_enabled` | `true` | Run one recall per user turn. |
| `hindsight_recall_max_tokens` | `4096` | Max recall response size. |
| `hindsight_recall_budget` | `mid` | Hindsight recall budget. |
| `hindsight_retain_enabled` | `true` | Retain structured chatlogs to Hindsight. |
| `hindsight_retain_context` | `conversation between Agent Zero and the user` | Context for chatlog retain. |
| `hindsight_retain_min_messages` | `3` | Retain after this many new chatlog entries. |
| `hindsight_retain_min_chars` | `800` | Retain after this many new chatlog characters. |
| `hindsight_scheduler_task_log_enabled` | `true` | Retain one scheduler result document instead of using normal memory operations. |
| `hindsight_scheduler_task_context` | `Agent Zero scheduled task execution result` | Context for scheduled task result documents. |
| `hindsight_solution_extract_enabled` | `false` | Enable gated utility-model solution extraction. |
| `hindsight_solution_extract_min_tool_calls` | `1` | Require new tool activity before solution extraction. |
| `hindsight_solution_extract_min_chars` | `1200` | Require enough new chatlog content before solution extraction. |
| `hindsight_solution_extract_max_history_chars` | `80000` | Recent history window sent to the utility model. |
| `hindsight_operation_logging` | `true` | Show concise log entries for actual Hindsight operations. |
| `hindsight_debug` | `false` | Show verbose lifecycle/debug logs. |

## Repository Hygiene

Runtime files such as `config.json`, `execute_record.json`, `.dependency_status.json`, `.toggle-*`, `vendor/`, and Python caches are intentionally ignored and should not be committed.

## Limitations

- Solution documents are deduplicated by content hash. Similar but differently worded solutions may be stored as separate documents.
- Secret redaction covers common patterns, but sensitive environments should still review what is retained.
- Solution extraction uses Agent Zero's utility model when enabled.
- Scheduled task detection uses Agent Zero scheduler metadata when available and falls back to `## Task:` prompts.

## Repository Context

Original plugin repository:

https://github.com/neurocis/a0_hindsight

Proposal issue for this direction:

https://github.com/neurocis/a0_hindsight/issues/3

Proof-of-concept branch:

https://github.com/cstreil/a0_hindsight/tree/codex/hermes-style-chatlog-lifecycle

## Requirements

- Agent Zero with plugin support
- `hindsight-client >= 0.4.0`
- A running Hindsight server

## License

MIT
