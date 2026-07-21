"""Plan the mcp.* calls that make the global layer match the desired list.

Pure: given the desired object_list items and the names currently owned by the
global layer, produce an ordered list of add/edit/delete operations plus any
validation errors. The worker (main.py) applies the ops by calling the host and
surfaces the errors on the settings page; keeping the planning here makes it
trivially testable without a host.

A desired server already present in the global layer is always an `edit` (a full
upsert) rather than a diff: mcp.list redacts secret values (env/header values
become names only), so the worker cannot tell whether a value changed and must
re-send the authoritative desired state. mcp.edit is a full replacement, so this
is correct and idempotent.
"""

from __future__ import annotations

from typing import Any
from collections.abc import Iterable

from aoe_mcp_plugin.servers import item_to_server


def plan(items: Any, current_global: Iterable[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Return `(ops, errors)`.

    `ops` entries are `{"kind": "add"|"edit"|"delete", "name": str, "entry"?: dict}`.
    `entry` (the mcp.add/mcp.edit payload) is present for add/edit, absent for
    delete. Order: adds/edits in list order first, then deletes (sorted) for any
    global-owned server the list no longer contains.
    """
    current = set(current_global)
    desired: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for item in items if isinstance(items, list) else []:
        entry, err = item_to_server(item)
        if err is not None:
            errors.append(err)
            continue
        assert entry is not None  # noqa: S101 - err is None implies entry is set
        name = entry["name"]
        if name in desired:
            errors.append(f"{name!r}: duplicate entry; keeping the first")
            continue
        desired[name] = entry

    ops: list[dict[str, Any]] = [
        {"kind": "edit" if name in current else "add", "name": name, "entry": entry} for name, entry in desired.items()
    ]
    ops.extend({"kind": "delete", "name": name} for name in sorted(current - desired.keys()))
    return ops, errors
