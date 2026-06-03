# Claude Code -> Hermes Codex bridge

This bridge exposes a local Anthropic Messages-compatible HTTP API for Claude Code and routes requests through the Hermes `openai-codex` credential pool.

It is intended for local use only. It binds to `127.0.0.1`, reads its runtime config from `~/.hermes/cc-switch-codex-bridge/config.json`, and never requires raw Codex credentials in Claude Code.

## Features

- Anthropic `/v1/messages` compatibility for Claude Code.
- `/v1/models` exposes model aliases so Claude Code dynamic workflows and subagents can choose a fit-for-purpose profile.
- Model aliases map to backend model + Codex reasoning effort:
  - `gpt-5.5-xhigh`, `gpt-5.5-high`, `gpt-5.5-medium`, `gpt-5.5-low`, `gpt-5.5-fast`, `gpt-5.5-mini`
  - `gpt-5.4-xhigh`, `gpt-5.4-high`, `gpt-5.4-medium`, `gpt-5.4-low`
- Claude `thinking.budget_tokens` is translated into Codex reasoning effort when no explicit alias effort is present.
- Codex `response.reasoning_summary_text.delta` is streamed to Claude Code as Anthropic `thinking_delta` blocks.
- Tool-use history is flattened into non-protocol XML-like transcript markers to avoid Claude Code wrapper leakage.

## Local setup

```bash
mkdir -p ~/.hermes/cc-switch-codex-bridge
cp scripts/cc-switch-codex-bridge/config.example.json ~/.hermes/cc-switch-codex-bridge/config.json
python3 - <<'PY'
import json, secrets, pathlib
p = pathlib.Path.home() / '.hermes/cc-switch-codex-bridge/config.json'
c = json.loads(p.read_text())
c['auth_token'] = 'ccsb_' + secrets.token_urlsafe(32)
p.write_text(json.dumps(c, indent=2) + '\n')
print(p)
PY
```

Run foreground for smoke testing:

```bash
CODEX_ANTHROPIC_BRIDGE_CONFIG=~/.hermes/cc-switch-codex-bridge/config.json \
python scripts/cc-switch-codex-bridge/server.py
```

Point Claude Code at the bridge:

```bash
export ANTHROPIC_BASE_URL=http://127.0.0.1:15722
export ANTHROPIC_AUTH_TOKEN=BRIDGE_VALUE_FROM_CONFIG
export ANTHROPIC_API_KEY=BRIDGE_VALUE_FROM_CONFIG
claude -p --model gpt-5.5-low 'Reply exactly: OK'
```


## Smoke checks

```bash
curl -sS http://127.0.0.1:15722/health | python -m json.tool
curl -sS http://127.0.0.1:15722/v1/models | python -m json.tool
```

Streaming reasoning smoke should show `thinking_delta` frames. Use a prompt likely to trigger reasoning summary, for example arithmetic or debugging, because trivial prompts may not emit reasoning deltas.

## Security notes

- Do not commit `~/.hermes/cc-switch-codex-bridge/config.json`; it contains `auth_token`.
- The server refuses to bind to non-local hosts.
- Do not log request headers or raw credentials.
