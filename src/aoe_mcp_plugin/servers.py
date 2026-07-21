"""Translate an object_list item into an mcp.add / mcp.edit server entry.

An object_list item's fields are all strings/selects (the host has no map or
array field type), so `args`, `env`, and `headers` arrive line-encoded and are
parsed here into the standard `.mcp.json` server shape the mcp.* host RPCs
expect: a `name` sibling plus the transport fields.

  stdio: { "name", "command", "args": [...], "env": {...} }        (no "type")
  http:  { "name", "type": "http", "url", "headers": {...} }
  sse:   { "name", "type": "sse",  "url", "headers": {...} }

Empty args/env/headers are omitted so the on-disk entry stays minimal, matching
the core writer (server_to_entry).
"""

from __future__ import annotations

from typing import Any

TRANSPORTS = ("stdio", "http", "sse")


def parse_lines(text: Any) -> list[str]:
    """Non-empty, stripped lines. Used for stdio `args` (one arg per line)."""
    if not isinstance(text, str):
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_kv(text: Any) -> dict[str, str]:
    """`KEY=VALUE` lines into a map, splitting on the first `=` so values may
    contain `=`. Lines without `=`, or with an empty key, are skipped. Used for
    both stdio `env` and http/sse `headers`."""
    out: dict[str, str] = {}
    if not isinstance(text, str):
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            out[key] = value.strip()
    return out


def item_to_server(item: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:  # noqa: PLR0911 - one return per validation branch
    """Map one object_list item to an mcp.* server entry.

    Returns `(entry, None)` on success or `(None, error)` with a user-facing
    message when the item is invalid (missing name, unknown transport, missing
    command/url for the transport). The transport-irrelevant fields are ignored
    rather than rejected so switching a server's transport does not require
    clearing the other transport's fields first.
    """
    if not isinstance(item, dict):
        return None, "server entry is not an object"
    name = str(item.get("name", "")).strip()
    if not name:
        return None, "server is missing a name"

    transport = item.get("transport") or "stdio"
    if transport not in TRANSPORTS:
        return None, f"{name!r}: unknown transport {transport!r} (expected stdio, http, or sse)"

    if transport == "stdio":
        command = str(item.get("command", "")).strip()
        if not command:
            return None, f"{name!r}: stdio transport requires a command"
        entry: dict[str, Any] = {"name": name, "command": command}
        args = parse_lines(item.get("args"))
        if args:
            entry["args"] = args
        env = parse_kv(item.get("env"))
        if env:
            entry["env"] = env
        return entry, None

    url = str(item.get("url", "")).strip()
    if not url:
        return None, f"{name!r}: {transport} transport requires a url"
    entry = {"name": name, "type": transport, "url": url}
    headers = parse_kv(item.get("headers"))
    if headers:
        entry["headers"] = headers
    return entry, None
