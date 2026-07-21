"""Map resolved MCP provenance to tool-card-badge display state.

Pure: given the servers from an `mcp.resolve` response (each a redacted entry
with a `name`, a `provenance` label, and any `shadowed` lower layers), build the
`tool-card-badge` item list the worker pushes via `ui.state.set`. The host
matches each item to a transcript MCP tool-call card by the raw server `name` and
renders the pill.

Provenance labels come verbatim from `McpProvenance::label()` in core
(src/session/mcp_model.rs): `global`, `agent-native:<agent>`, `profile:<name>`,
`project-local`, `kept-on-removal:<agent>`. The full label plus any shadow chain
go in each badge tooltip so the call-time pill stays reconcilable with the
provenance the `MCP servers` settings page lists.
"""

from __future__ import annotations

from typing import Any

SLOT = "tool-card-badge"
SLOT_ID = "provenance"

# Valid Tone values (core src/plugin/ui_state.rs, serde kebab-case):
# neutral | info | success | warn | danger.


def _humanize_agent(agent: str) -> str:
    """A bare agent key rendered for display, e.g. `claude` -> `Claude`. An
    already-cased key (e.g. `GPT`) is left untouched."""
    cleaned = agent.replace("_", " ").replace("-", " ").strip()
    return cleaned.title() if cleaned.islower() else cleaned or agent


def provenance_display(label: str) -> dict[str, str]:
    """Short `text` + `tone` + base `tooltip` for a provenance label. An unknown
    label falls back to the raw label, so a new core variant still renders."""
    if label == "global":
        return {"text": "AoE", "tone": "info", "tooltip": "AoE-managed (global)"}
    if label == "project-local":
        return {"text": "Project", "tone": "info", "tooltip": "Project-local"}
    if label.startswith("agent-native:"):
        agent = label.split(":", 1)[1]
        return {"text": _humanize_agent(agent), "tone": "neutral", "tooltip": f"Native to {agent}"}
    if label.startswith("profile:"):
        name = label.split(":", 1)[1]
        return {"text": "Profile", "tone": "info", "tooltip": f"Profile: {name}"}
    if label.startswith("kept-on-removal:"):
        agent = label.split(":", 1)[1]
        return {"text": "Kept", "tone": "warn", "tooltip": f"Kept on removal from {agent}"}
    return {"text": label, "tone": "neutral", "tooltip": label}


def badge_item(server: dict[str, Any]) -> dict[str, Any] | None:
    """One `tool-card-badge` item for a server, or `None` if it has no usable
    name (the host requires a non-empty `target.name`)."""
    name = server.get("name")
    if not isinstance(name, str) or not name:
        return None
    display = provenance_display(str(server.get("provenance", "")))
    tooltip = display["tooltip"]
    shadowed = [s for s in server.get("shadowed", []) if isinstance(s, str) and s]
    if shadowed:
        tooltip = f"{tooltip}; shadows: {', '.join(shadowed)}"
    return {
        "target": {"kind": "mcp", "name": name},
        "text": display["text"],
        "tone": display["tone"],
        "tooltip": tooltip,
    }


def callable_servers(resolve: dict[str, Any] | None) -> list[dict[str, Any]]:
    """The servers an agent can actually call, from an `mcp.resolve` response:
    the effective forwarded set plus any kept-on-removal servers (still present in
    the agent's native config). Deduped by name, effective winning, so a server in
    both layers is badged once with its effective provenance."""
    resolve = resolve or {}
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for group in ("effective", "keptOnRemoval"):
        for server in resolve.get(group) or []:
            name = server.get("name") if isinstance(server, dict) else None
            if isinstance(name, str) and name not in seen:
                seen.add(name)
                out.append(server)
    return out


def badge_items(servers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The item list for the `tool-card-badge` payload, one entry per named
    server keyed by its raw name."""
    return [item for server in servers if (item := badge_item(server)) is not None]
