# 🧠 Hindsight Memory Plugin for Agent Zero

Augments Agent Zero's built-in memory with [Hindsight](https://github.com/vectorize-io/hindsight) by [Vectorize.io](https://vectorize.io). Gives Agent Zero persistent, semantically-rich memory that goes beyond simple vector similarity — with disposition-aware context generation.

## What It Does

| Feature | Description |
|---------|-------------|
| **Automatic Retain** | Conversation memories are extracted and stored in Hindsight banks after each interaction |
| **Enhanced Recall** | Memory recall is enriched with Hindsight's semantic search alongside the built-in vector memory |
| **Reflect Context** | Disposition-aware context is generated and injected into the system prompt |
| **Project Isolation** | Memory banks are automatically scoped by project for clean separation |
| **Graceful Degradation** | If Hindsight is unavailable, the agent continues normally with built-in memory |
| **Settings UI** | Configure all settings directly in A0's settings panel |
| **Plugin System Conformant** | Built for A0's plugin architecture (plugin.yaml, extensions, settings) |

## How It Works

```
┌─────────────┐     recall once      ┌──────────────┐
│ Agent Zero  │ ◀────────────────── │  Hindsight   │
│ user turn   │                     │ memory bank  │
└──────┬──────┘                     └──────┬───────┘
       │                                   │
       │ fenced temporary context          │
       ▼                                   │
┌─────────────┐                            │
│ LLM answer  │                            │
└──────┬──────┘                            │
       │ one structured chatlog retain     │
       └──────────────────────────────────▶│
```

1. **Recall** — Once per user turn, Hindsight is queried from the clean user message and injected as fenced temporary context.
2. **Retain** — After the final response, the conversation is retained as one structured chatlog document via `retain_batch` with a stable `document_id`.
3. **Reflect** — Optional advanced mode. Disabled by default for the lean lifecycle.

The plugin no longer calls a utility model to create individual memory fragments during retain. Hindsight may still display individual facts in the bank because it extracts facts internally from the retained chatlog document.

## Installation

### 1. Clone into Agent Zero's user plugins directory

```bash
cd /a0/usr/plugins
git clone https://github.com/YOUR_USERNAME/a0-plugin-hindsight.git hindsight
```

Or copy the plugin files directly into `/a0/usr/plugins/hindsight/`.

### 2. Install dependencies

```bash
pip install hindsight-client>=0.4.0
```

### 3. Set up a Hindsight server

Follow the [Hindsight installation guide](https://github.com/vectorize-io/hindsight) to run a local server:

```bash
docker run -p 8888:8888 vectorize/hindsight
```

Or use the Vectorize.io hosted service.

### 4. Configure in Agent Zero

1. Go to **Settings → Agents → Hindsight Memory** and set:
   - `Hindsight Base URL` — your Hindsight server URL (optional; e.g. `http://localhost:8888`)
   - `HINDSIGHT_API_KEY` — (optional) API key if required by your server (in **Settings → Secrets**)

2. Go to **Settings → Plugins** and enable **Hindsight Memory**

3. (Optional) Click **Configure** on the plugin to adjust:
   - Bank ID prefix
   - Enable/disable retain, recall, reflect individually
   - Recall/reflect budgets and token limits
   - Cache TTL

### 5. Restart Agent Zero

The plugin will be discovered on restart. You'll see `[Hindsight] Integration enabled for bank: a0-default` in the logs.

## Plugin Structure

```
hindsight/
├── plugin.yaml                          # Plugin manifest
├── default_config.yaml                  # Settings defaults
├── requirements.txt                     # hindsight-client>=0.4.0
├── hooks.py                             # Install/update hooks
├── execute.py                           # User-triggered setup & health check
├── helpers/
│   ├── __init__.py
│   └── hindsight_helper.py              # Core integration logic
├── extensions/
│   └── python/
│       ├── monologue_start/
│       │   └── _20_hindsight_init.py    # Initialize Hindsight on agent start
│       ├── monologue_end/
│       │   └── _52_hindsight_retain.py  # Retain memories to Hindsight
│       ├── message_loop_prompts_after/
│       │   └── _51_hindsight_recall.py  # Enrich recall with Hindsight
│       └── system_prompt/
│           └── _30_hindsight_reflect.py # Inject reflect context into prompt
├── prompts/
│   ├── hindsight.retain_extract.sys.md  # Memory extraction prompt
│   ├── hindsight.recall.md              # Recall injection template
│   └── hindsight.reflect.md             # Reflect injection template
├── webui/
│   └── config.html                      # Settings UI
└── README.md
```

## Configuration

### Secrets (Settings → Secrets)

| Key | Required | Default | Description |
|-----|----------|---------|-------------|
| `HINDSIGHT_BASE_URL` | No* | — | Hindsight server URL (e.g. `http://localhost:8888`). Set in plugin settings instead. |
| `HINDSIGHT_API_KEY` | No | — | API key (optional for local servers) |

*Note: `HINDSIGHT_BASE_URL` is configured in the plugin settings UI. Setting it in Secrets is deprecated but still supported for backwards compatibility.
### Plugin Settings (Settings → Plugins → Hindsight → Configure)

| Setting | Default | Description |
|---------|---------|-------------|
| Explicit Bank ID | empty | Optional fixed bank override. Leave blank for project-derived banks. |
| Bank ID Prefix | `a0` | Prefix used only when Explicit Bank ID is blank. |
| Enable Chatlog Retain | `true` | Retain one structured conversation document after the final response. |
| Retain Context | `conversation between Agent Zero and the user` | Context string sent with chatlog retain calls. |
| Enable Recall | `true` | Run one Hindsight recall per user turn. |
| Recall Max Tokens | `4096` | Max tokens for recall results. |
| Recall Budget | `mid` | Compute budget for recall. |
| Enable Reflect | `false` | Optional advanced reflect context injection. |
| Reflect Budget | `low` | Compute budget for reflect when enabled. |
| Reflect Max Tokens | `500` | Max tokens for reflect context when enabled. |
| Cache TTL | `120` seconds | How long to cache reflect context when enabled. |
| Debug Logging | `false` | Verbose lifecycle logging. |

## Hindsight Companion Skill (Optional CLI Access)

While the Hindsight plugin handles automatic lifecycle operations (retain, recall, reflect), you can also use the **Hindsight companion skill** for direct, opt-in CLI-style access to memory banks.

### Loading the Skill

```bash
skills_tool:load hindsight
```

Once loaded, the skill provides:

| Operation | Purpose |
|-----------|----------|
| **Retain** | Manually store information to a memory bank |
| **Recall** | Manually search memories by query |
| **Reflect** | Manually generate disposition-aware context |
| **Inspect** | View memory bank contents and metadata |
| **List** | List all memories in a bank |
| **Export** | Export memories to file |
| **Delete** | Remove specific memories |

### When to Use the Skill

- **Plugin alone**: Automatic background operation (good for hands-off memory management)
- **Plugin + Skill**: Manual intervention when you need to:
  - Query specific memories outside normal conversation flow
  - Consolidate or reorganize memory banks
  - Export memory data for inspection
  - Troubleshoot or debug Hindsight service issues
  - Trigger memory operations explicitly within agent workflows

### Architecture

The plugin and skill form a complementary pair:

```
┌─────────────────────────────────────┐
│  Plugin (Automatic Lifecycle)       │
├─────────────────────────────────────┤
│ • Retain after each conversation   │
│ • Recall during memory phase       │
│ • Reflect into system prompt       │
│ • Runs invisibly in background     │
└─────────────────────────────────────┘
         ↓         ↑
  Hindsight Server
         ↑         ↓
┌─────────────────────────────────────┐
│  Skill (Manual CLI Access)          │
├─────────────────────────────────────┤
│ • Query memories on demand         │
│ • Manage memory banks explicitly   │
│ • Export and analyze data          │
│ • Requires explicit load command   │
└─────────────────────────────────────┘
```

Both use the same Hindsight server and bank infrastructure—the plugin provides automatic operation, the skill provides manual control.


## Hindsight Concepts

| Concept | Description |
|---------|-------------|
| **Bank** | A memory container scoped by project context |
| **Retain** | Store information as memories in a bank |
| **Recall** | Semantic search across stored memories |
| **Reflect** | Generate disposition-aware responses using stored knowledge |
| **Disposition** | Personality traits (skepticism, literalism, empathy) that affect how reflect generates context |

## Requirements

- Agent Zero (with plugin system)
- Python 3.12+
- `hindsight-client` >= 0.4.0
- A running Hindsight server (local Docker or hosted)

## Links

- [Hindsight GitHub](https://github.com/vectorize-io/hindsight)
- [Vectorize.io](https://vectorize.io)
- [Agent Zero](https://github.com/agent0ai/agent-zero)

## License

MIT
