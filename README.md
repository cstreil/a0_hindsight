# Hindsight Memory Plugin for Agent Zero - Hermes-Style Lifecycle PoC

This fork is a proof of concept based on the original Agent Zero Hindsight plugin.
The original plugin connects Agent Zero to [Hindsight](https://github.com/vectorize-io/hindsight), allowing Agent Zero to retain conversation memory, recall relevant memories, and optionally inject Hindsight reflect context.

This branch keeps that purpose, but changes the default memory lifecycle to be leaner and closer to the Hindsight integration used by Hermes Agent.

## What Changed

The main change is that routine memory retention no longer extracts many individual memory fragments in the plugin.

Instead, the default lifecycle is:

```text
user turn -> one Hindsight recall -> fenced temporary context -> LLM response -> gated structured chatlog retain
```

The plugin submits structured conversation material to Hindsight and lets Hindsight do its own fact/entity/relationship extraction internally.

## Key Improvements

### Structured Chatlog Retain

- Retains one structured chatlog document with `retain_batch`.
- Uses a stable `document_id` per Agent Zero session: `agent-zero:<context-id>`.
- Sends the full accumulated chatlog so Hindsight can reprocess the evolving conversation.
- Skips tool-result messages when building the chatlog.
- Redacts common secret patterns before retain.

### Retain Throttling

Chatlog retain can now be batched instead of running after every short message.

Defaults:

```yaml
hindsight_retain_min_messages: 3
hindsight_retain_min_chars: 800
```

Retain runs when either threshold is reached since the last successful retain.
Set both values to `0` to retain after every eligible turn.

### One Recall Per User Turn

- Recall runs at most once per user message.
- The recall query is built from the clean user message.
- Recalled context is injected as temporary fenced context:

```xml
<memory-context>
...
</memory-context>
```

The recalled memory context is not persisted back into Agent Zero history.

### Optional Gated Solution Extraction

This fork adds an optional replacement for Agent Zero's native "solutions" memory behavior.

It is disabled by default:

```yaml
hindsight_solution_extract_enabled: false
```

When enabled, it only calls Agent Zero's utility model after a cheap heuristic gate detects substantive tool-backed work:

```yaml
hindsight_solution_extract_min_tool_calls: 1
hindsight_solution_extract_min_chars: 1200
```

If reusable technical solutions are found, they are retained to Hindsight as solution documents with tags such as:

```text
agent-zero
solution
workflow
tool:<tool-name>
```

This keeps normal conversation memory cheap while still allowing successful technical workflows to become reusable Hindsight memories.

### Quieter, More Transparent Logging

Normal operation now logs one concise line per actual Hindsight API operation:

- `Recall from bank ...`
- `Retain chatlog to bank ...`
- `Retain solution to bank ...`
- `Reflect from bank ...` if reflect is enabled

Verbose lifecycle messages remain available through `hindsight_debug`.

### Reflect Is Advanced/Optional

Reflect remains supported, but is disabled by default.
The recommended default lifecycle is recall plus structured chatlog retain.

## Why This Direction

The original plugin worked, but in testing it created too much activity for routine turns:

- many plugin-side memory fragments
- repeated status log entries
- utility-model work for memory extraction even when Hindsight could extract from the retained document itself

This fork aims for:

- fewer utility-model calls
- fewer retain calls
- clearer separation between Agent Zero history and Hindsight recall context
- Hindsight as the long-term memory provider
- optional, explicit solution extraction for reusable technical workflows

## Manual Installation

This branch is not intended to be installed from the Plugin Hub.
For manual testing:

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

## Important Settings

| Setting | Default | Purpose |
|---------|---------|---------|
| `hindsight_recall_enabled` | `true` | Run one recall per user turn. |
| `hindsight_retain_enabled` | `true` | Retain structured chatlogs to Hindsight. |
| `hindsight_retain_min_messages` | `3` | Retain after this many new chatlog entries. |
| `hindsight_retain_min_chars` | `800` | Retain after this many new chatlog characters. |
| `hindsight_solution_extract_enabled` | `false` | Enable gated utility-model solution extraction. |
| `hindsight_solution_extract_min_tool_calls` | `1` | Require new tool activity before solution extraction. |
| `hindsight_solution_extract_min_chars` | `1200` | Require enough new chatlog content before solution extraction. |
| `hindsight_operation_logging` | `true` | Show concise log entries for actual Hindsight operations. |
| `hindsight_debug` | `false` | Show verbose lifecycle/debug logs. |
| `hindsight_reflect_enabled` | `false` | Enable optional Hindsight reflect context. |

## Current Limitations

- Solution documents are currently deduplicated by content hash. Similar but differently worded solutions may be stored as separate documents.
- Secret redaction covers common patterns, but solution extraction should still be treated carefully in sensitive environments.
- The solution extractor is intentionally conservative and gated, but it still uses Agent Zero's utility model when it runs.

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
