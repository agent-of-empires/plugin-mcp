"""Tier 1 worker entrypoint.

Speaks ndjson JSON-RPC 2.0 over stdio, both directions. The worker *answers*
host->worker messages (the `status`/`refresh` commands and the
`plugin.settings.changed` notification) and *initiates* its own host RPCs: it
reads the desired server list via `config.get`, reads the effective set via
`mcp.list`/`mcp.resolve`, and writes the global layer via
`mcp.add`/`mcp.edit`/`mcp.delete`, then pushes the settings-page via
`ui.state.set`.

Concurrency model -- the single-stdin-reader invariant. Only ONE thread reads
stdin: a dedicated reader thread drains it onto an in-process queue (an `_EOF`
sentinel at end of stream). The main thread owns everything else: it consumes
the queue, correlates replies to its own outbound host RPCs (`Runtime.call_host`),
and dispatches inbound host messages. Because only the reader touches stdin, a
slow reconcile never drops host messages -- they buffer in the queue.

Reconcile model. The user edits an `object_list` setting the host renders; on
each change the host sends `plugin.settings.changed`, and the worker diffs the
desired list against the current global-owned set and issues the add/edit/delete
host RPCs to converge. Read-only layers need no client enforcement: the host
rejects a non-global target with a FORBIDDEN error the worker surfaces on the
page. Exits on stdin EOF, which is how the host shuts the worker down.

Run via the `aoe-mcp-worker` console script or `python -m aoe_mcp_plugin.main`.
"""

from __future__ import annotations

import sys
import json
import time
import queue
import logging
import itertools
import threading
from typing import Any
from collections.abc import Callable

from aoe_mcp_plugin import uistate
from aoe_mcp_plugin.rpc import error_response
from aoe_mcp_plugin.rpc import result_response
from aoe_mcp_plugin.reconcile import plan

Sink = Callable[[dict[str, Any]], None]

CONFIG_GET = "config.get"
MCP_LIST = "mcp.list"
MCP_RESOLVE = "mcp.resolve"
MCP_ADD = "mcp.add"
MCP_EDIT = "mcp.edit"
MCP_DELETE = "mcp.delete"
UI_STATE_SET = "ui.state.set"
SETTINGS_CHANGED = "plugin.settings.changed"
SERVERS_KEY = "servers"

# The host's FORBIDDEN JSON-RPC code (src/plugin/protocol.rs); mcp.* returns it
# when a name is owned by a read-only (non-global) layer.
ERR_FORBIDDEN = -32001

# A wedged host must never freeze the worker: outbound host RPCs time out and
# the caller falls back rather than blocking forever.
HOST_RPC_TIMEOUT = 10.0

# End-of-stdin sentinel placed on the queue by the reader thread.
_EOF = object()

# Host-bound request ids live in their own high range so they never collide
# with the ids the host assigns to its requests to us.
_outbound_ids = itertools.count(1_000_000)
_stdout_lock = threading.Lock()


def _send(message: dict[str, Any]) -> None:
    """Write one JSON-RPC message line to stdout, serialized across threads."""
    with _stdout_lock:
        sys.stdout.write(json.dumps(message) + "\n")
        sys.stdout.flush()


class HostReply:
    """A worker->host RPC outcome: `ok` with `result`, or an `error` dict
    (`{code, message}`) on an error reply / timeout / stream close."""

    __slots__ = ("error", "ok", "result")

    def __init__(self, *, ok: bool, result: Any = None, error: dict[str, Any] | None = None) -> None:
        self.ok = ok
        self.result = result
        self.error = error or {}


class Runtime:
    """The worker's main-loop runtime. Owns the inbound queue and the outbound
    host-RPC correlation. The reader thread is the only stdin reader; everything
    here runs on the main thread."""

    def __init__(self, send: Sink = _send, stdin: Any = None) -> None:
        self.send = send
        self.stdin = stdin if stdin is not None else sys.stdin
        self.inbox: queue.Queue[Any] = queue.Queue()
        self.stopped = False

    def _read_stdin(self) -> None:
        """Reader thread: drain stdin into the queue, then post `_EOF`."""
        for raw in self.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            self.inbox.put(msg)
        self.inbox.put(_EOF)

    def call_host(self, method: str, params: dict[str, Any], timeout: float = HOST_RPC_TIMEOUT) -> HostReply:
        """Blocking worker->host RPC: send the request, then drain the queue
        until its reply arrives, servicing any inbound host messages meanwhile.
        Returns a `HostReply`; a timeout or stream close is `ok=False` so the
        caller can fall back rather than freeze."""
        req_id = next(_outbound_ids)
        self.send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return HostReply(ok=False, error={"code": 0, "message": "host timeout"})
            try:
                item = self.inbox.get(timeout=remaining)
            except queue.Empty:
                return HostReply(ok=False, error={"code": 0, "message": "host timeout"})
            if item is _EOF:
                self.stopped = True
                self.inbox.put(_EOF)  # re-arm so the main loop also sees EOF
                return HostReply(ok=False, error={"code": 0, "message": "stream closed"})
            if item.get("id") == req_id and "method" not in item:
                if "error" in item:
                    err = item["error"] if isinstance(item["error"], dict) else {"message": str(item["error"])}
                    return HostReply(ok=False, error=err)
                return HostReply(ok=True, result=item.get("result"))
            self.handle_inbound(item)

    def _desired_servers(self) -> list[Any]:
        """The desired server list from our own `servers` setting, or empty."""
        reply = self.call_host(CONFIG_GET, {"key": SERVERS_KEY})
        if reply.ok and isinstance(reply.result, dict):
            value = reply.result.get("value")
            if isinstance(value, list):
                return value
        return []

    def _current_global_names(self) -> list[str] | None:
        """Names currently owned by the global layer, or `None` if the effective
        set could not be read. `None` is distinct from empty: acting on unknown
        state would issue add/delete calls that either error or wrongly remove
        servers, so the caller skips the sync instead."""
        reply = self.call_host(MCP_LIST, {})
        if not reply.ok or not isinstance(reply.result, dict):
            return None
        servers = reply.result.get("servers")
        if not isinstance(servers, list):
            return None
        return [
            s["name"]
            for s in servers
            if isinstance(s, dict) and s.get("provenance") == "global" and isinstance(s.get("name"), str)
        ]

    def _apply(self, op: dict[str, Any]) -> str | None:
        """Apply one reconcile op via the matching host RPC. Returns `None` on
        success or a user-facing error string, translating FORBIDDEN into a
        read-only-layer message."""
        kind = op["kind"]
        name = op["name"]
        if kind == "delete":
            reply = self.call_host(MCP_DELETE, {"name": name})
        else:
            reply = self.call_host(MCP_ADD if kind == "add" else MCP_EDIT, op["entry"])
        if reply.ok:
            return None
        message = str(reply.error.get("message", "unknown error"))
        if reply.error.get("code") == ERR_FORBIDDEN:
            return f"{name!r}: read-only layer, not written ({message})"
        return f"could not {kind} {name!r}: {message}"

    def reconcile(self) -> None:
        """Converge the global layer to the desired list, then repaint the page.

        Skips applying anything (but still repaints) when the current effective
        set is unreadable, so a transient host failure never issues destructive
        calls against unknown state."""
        desired = self._desired_servers()
        current = self._current_global_names()
        if current is None:
            self._push_page(["Could not read the current MCP servers; skipping sync."], status=None)
            return
        ops, errors = plan(desired, current)
        applied = 0
        for op in ops:
            err = self._apply(op)
            if err is None:
                applied += 1
            else:
                errors.append(err)
        status = f"Synced {applied} change(s)." if applied and not errors else None
        self._push_page(errors, status)

    def _push_page(self, errors: list[str], status: str | None) -> None:
        """Push the settings-page blocks built from a fresh `mcp.resolve`."""
        reply = self.call_host(MCP_RESOLVE, {})
        resolve = reply.result if reply.ok and isinstance(reply.result, dict) else None
        payload = uistate.build_page(resolve, errors, status)
        # settings-page is a global slot: no session_id.
        self.send(
            {
                "jsonrpc": "2.0",
                "id": next(_outbound_ids),
                "method": UI_STATE_SET,
                "params": {"slot": uistate.SETTINGS_PAGE_SLOT, "id": uistate.SETTINGS_PAGE_ID, "payload": payload},
            }
        )

    def handle_inbound(self, msg: dict[str, Any]) -> None:
        """Service one host->worker message. `plugin.settings.changed` (scoped to
        our `servers` key) and the `status`/`refresh` commands all trigger a
        reconcile; a stray reply is ignored."""
        method = msg.get("method")
        if not isinstance(method, str):
            return  # a host reply we are not currently waiting on
        params = msg.get("params") or {}
        if method == SETTINGS_CHANGED:
            changed = params.get("changed_keys")
            if not isinstance(changed, list) or SERVERS_KEY in changed:
                self.reconcile()
            return
        msg_id = msg.get("id")
        command = method.rsplit(".", 1)[-1]
        if command not in ("status", "refresh"):
            if isinstance(msg_id, int):
                self.send(error_response(msg_id, LookupError(method)))
            return
        try:
            self.reconcile()
        except Exception as exc:  # noqa: BLE001 - any failure becomes a JSON-RPC error
            if isinstance(msg_id, int):
                self.send(error_response(msg_id, exc))
            return
        if isinstance(msg_id, int):
            self.send(result_response(msg_id, {"ok": True}))

    def run(self) -> None:
        threading.Thread(target=self._read_stdin, daemon=True).start()
        # Sync and paint once at startup so the page reflects reality before any
        # edit, and any servers configured while the worker was down converge now.
        self.reconcile()
        while not self.stopped:
            item = self.inbox.get()
            if item is _EOF:
                break
            self.handle_inbound(item)


def main() -> None:
    # stdout is the JSON-RPC channel; diagnostics go to stderr, which the host
    # captures in the per-worker log.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    Runtime().run()


if __name__ == "__main__":
    main()
