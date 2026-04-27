# Hindsight Memory Plugin Notes

This file documents the Agent Zero plugin in this repository. It is not a separate executable skill and it does not expose standalone inspect, list, export, delete, or delete_bank operations.

## What The Plugin Does

The plugin adds a lean Hindsight memory lifecycle to Agent Zero:

- Recall relevant Hindsight memories once per interactive user turn.
- Inject recalled memory as temporary fenced context.
- Retain clean structured chatlogs after thresholds are reached.
- Retain scheduled task results as one stable task-log document per task.
- Optionally extract reusable technical solutions after gated tool-backed work.

## What The Plugin Does Not Do

- It does not provide a manual Hindsight management CLI.
- It does not list, export, or delete memories.
- It does not inject Hindsight Reflect context.
- It does not store Agent Zero internal thoughts in normal chatlogs.

## Relevant Files

- helpers/hindsight_helper.py: Hindsight client access, chatlog building, redaction, retain/recall helpers.
- extensions/python/message_loop_prompts_after/_51_hindsight_recall.py: one recall per user turn.
- extensions/python/monologue_end/_52_hindsight_retain.py: chatlog retain and scheduled task logs.
- extensions/python/monologue_end/_53_hindsight_solution_extract.py: optional gated solution extraction.
- prompts/hindsight.recall.md: fenced recall-context template.
- prompts/hindsight.solution_extract.sys.md: utility-model prompt for solution extraction.

## Configuration

See README.md and default_config.yaml for supported settings. Runtime configuration belongs in Agent Zero plugin settings or local ignored config.json, not in committed files.
