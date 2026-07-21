"""Build the settings-page payload from the resolved MCP state.

Pure: maps an `mcp.resolve` response (effective servers with provenance, drift
conflicts, kept-on-removal) plus this run's reconcile errors/status into the
host block vocabulary. The block vocabulary is display-only (heading, note,
row, section, divider, and a parameterless action button), so this page shows
state and points the user at the Servers list for edits; it cannot itself
collect input.
"""

from __future__ import annotations

from typing import Any

SETTINGS_PAGE_SLOT = "settings-page"
SETTINGS_PAGE_ID = "mcp_manager"

_EDIT_HINT = (
    "Add, edit, and delete servers in the Servers list on this plugin's settings "
    "(web Settings and the TUI Plugins tab). AoE writes only the global layer; "
    "agent-native, profile, and project-local servers are read-only."
)


def _detail(server: dict[str, Any]) -> str:
    """One-line redacted summary: stdio shows command + args; http/sse the url.
    Secret values are never present (mcp.resolve emits names only)."""
    if server.get("command"):
        base = " ".join([server["command"], *(server.get("args") or [])])
    else:
        base = server.get("url", "")
    tags = []
    if server.get("envNames"):
        tags.append("env: " + ", ".join(server["envNames"]))
    if server.get("headerNames"):
        tags.append("headers: " + ", ".join(server["headerNames"]))
    if tags:
        base = f"{base}  [{'; '.join(tags)}]"
    return base


def _server_row(server: dict[str, Any]) -> dict[str, Any]:
    provenance = server.get("provenance", "")
    row: dict[str, Any] = {
        "kind": "row",
        "label": server.get("name", ""),
        "value": _detail(server),
        "sublabel": f"{server.get('transport', '')} · {provenance}",
    }
    # Global is the AoE-owned, editable layer; flag it so the user can tell at a
    # glance which rows the Servers list controls.
    if provenance == "global":
        row["tone"] = "success"
    return row


def build_page(resolve: dict[str, Any] | None, errors: list[str], status: str | None) -> dict[str, Any]:
    """Assemble the `{title, blocks}` settings-page payload."""
    resolve = resolve or {}
    blocks: list[dict[str, Any]] = [{"kind": "note", "text": _EDIT_HINT}]

    if resolve.get("driftPaused"):
        blocks.append(
            {
                "kind": "note",
                "tone": "danger",
                "text": "Drift detection is paused: an agent's native config has a malformed entry.",
            }
        )

    if errors:
        blocks.append(
            {
                "kind": "section",
                "title": "Problems",
                "tone": "danger",
                "children": [{"kind": "note", "tone": "danger", "text": e} for e in errors],
            }
        )
    elif status:
        blocks.append({"kind": "note", "tone": "success", "text": status})

    blocks.append({"kind": "divider"})
    blocks.append({"kind": "heading", "text": "Effective servers"})
    effective = resolve.get("effective") or []
    if effective:
        blocks.extend(_server_row(s) for s in effective)
    else:
        blocks.append({"kind": "note", "text": "No servers forwarded."})

    conflicts = resolve.get("conflicts") or []
    if conflicts:
        blocks.append(
            {
                "kind": "section",
                "title": "Conflicts",
                "tone": "danger",
                "children": [
                    {
                        "kind": "row",
                        "label": c.get("name", ""),
                        "value": "changed in the native config since AoE last saw it",
                    }
                    for c in conflicts
                ],
            }
        )

    kept = resolve.get("keptOnRemoval") or []
    if kept:
        blocks.append(
            {
                "kind": "section",
                "title": "Kept after removal from the native config",
                "children": [_server_row(s) for s in kept],
            }
        )

    blocks.append({"kind": "action", "label": "Refresh", "method": "refresh", "icon": "refresh-cw"})
    return {"title": "MCP servers", "blocks": blocks}
