# MCP plugin for Agent of Empires

Manage MCP servers from [Agent of Empires](https://github.com/agent-of-empires/agent-of-empires):
add, edit, and delete the servers AoE forwards to your agents, without hand
editing `mcp.json`.

> Status: **CRUD for the AoE-owned (global) layer.** The plugin drives the core
> MCP host RPCs (`mcp.list` / `mcp.resolve` / `mcp.add` / `mcp.edit` /
> `mcp.delete`) so every surface that reads MCP config sees your changes.
> Agent-native, profile, and project-local servers stay read-only by design;
> the host rejects a write to them and the plugin surfaces the reason.

## How it works

The plugin contributes two host-rendered surfaces (it ships no UI code; the host
renders everything):

- **A `servers` list setting** (an `object_list`), rendered as an
  add/edit/delete/reorder list on both the web Settings tab and the TUI Plugins
  tab. This is where you edit servers.
- **An `MCP servers` settings page**, showing the effective server set with
  provenance, any drift conflicts, kept-on-removal servers, and reconcile
  status. Display only.

When you change the `servers` list, the host notifies the worker
(`plugin.settings.changed`). The worker diffs your list against the servers the
global layer currently owns and issues `mcp.add` / `mcp.edit` / `mcp.delete` to
converge, then repaints the page.

### Server fields

Each row in the `servers` list is one MCP server:

| Field | Applies to | Notes |
| --- | --- | --- |
| `name` | all | Unique server name (required). |
| `transport` | all | `stdio`, `http`, or `sse`. |
| `command` | stdio | Executable to launch (required for stdio). |
| `args` | stdio | One argument per line. |
| `url` | http/sse | Server URL (required for http/sse). |
| `env` | stdio | `KEY=VALUE`, one per line. |
| `headers` | http/sse | `NAME=VALUE`, one per line. |

`args`, `env`, and `headers` are line-encoded because the host's object-list
fields are plain strings (no map or array field type). The worker parses them
into the standard `mcp.json` shape.

## Layout

```
src/aoe_mcp_plugin/
  main.py        JSON-RPC stdio loop, host-RPC correlation, reconcile (entrypoint)
  reconcile.py   pure add/edit/delete planning (desired list vs current global set)
  servers.py     object_list item -> mcp.* server entry, arg/env/header parsing
  uistate.py     resolved state -> settings-page blocks
  rpc.py         JSON-RPC response builders for inbound commands
tests/           pytest suite (drives the worker over stdio with a stub host)
```

## Install

From the dashboard (Settings -> Plugins -> Discover) or the CLI:

```sh
aoe plugin install agent-of-empires/plugin-mcp
```

Installing prompts for the plugin's declared capabilities (`runtime.worker`,
`config.read`, `config.write`) before anything is written.

## Develop

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

Drive the worker by hand (it reconciles on startup, then reacts to settings
changes and commands):

```sh
echo '{"jsonrpc":"2.0","method":"plugin.settings.changed","params":{"changed_keys":["servers"]}}' \
  | uv run aoe-mcp-worker
```

## Security note

Server secrets (stdio `env` values, http/sse header values) are stored in the
plugin settings inside the global AoE config and are also written to
`mcp.json`. Both files are owner-only, but the values do live at rest in two
places; treat the AoE config directory accordingly.
