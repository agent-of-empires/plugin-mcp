"""Drive the worker's reconcile against an in-process stub host.

The stub's `send` answers each worker->host request synchronously by putting the
reply on the runtime's inbox, so `Runtime.call_host` finds it without a real
subprocess. This exercises the full path: read desired settings, read the
effective set, issue the add/edit/delete host RPCs, and push the settings page.
"""

from aoe_mcp_plugin.main import Runtime


class Host:
    def __init__(self, servers_setting, effective, forbidden=(), *, fail_list=False):
        self.servers_setting = servers_setting
        self.effective = effective
        self.forbidden = set(forbidden)
        self.fail_list = fail_list
        self.sent = []
        self.writes = []  # (method, params) for every mcp.add/edit/delete attempt
        self.rt = Runtime(send=self.send)

    def send(self, msg):
        self.sent.append(msg)
        method = msg.get("method")
        rid = msg.get("id")
        if method is None or rid is None:
            return
        if method == "ui.state.set":
            return  # fire-and-forget from the worker; not awaited
        result, error = self._respond(method, msg.get("params") or {})
        reply = {"jsonrpc": "2.0", "id": rid}
        reply["error" if error is not None else "result"] = error if error is not None else result
        self.rt.inbox.put(reply)

    def _respond(self, method, params):
        if method == "config.get":
            return {"value": self.servers_setting}, None
        if method == "mcp.list":
            if self.fail_list:
                return None, {"code": -32603, "message": "boom"}
            return {"servers": self.effective}, None
        if method == "mcp.resolve":
            return {"effective": self.effective, "conflicts": [], "keptOnRemoval": [], "driftPaused": False}, None
        if method in ("mcp.add", "mcp.edit", "mcp.delete"):
            self.writes.append((method, params))
            name = params.get("name")
            if name in self.forbidden:
                return None, {"code": -32001, "message": f"MCP server {name!r} is owned by a non-global layer"}
            return {"status": "ok"}, None
        return {}, None


def _stdio_item(name):
    return {"name": name, "transport": "stdio", "command": "run"}


def _last_page(host):
    sets = [m for m in host.sent if m.get("method") == "ui.state.set"]
    assert sets, "worker never pushed a settings page"
    params = sets[-1]["params"]
    assert params["slot"] == "settings-page"
    assert params["id"] == "mcp_manager"
    assert "session_id" not in params  # global slot
    return params["payload"]


def test_add_new_server_calls_mcp_add():
    host = Host(servers_setting=[_stdio_item("foo")], effective=[])
    host.rt.reconcile()
    assert host.writes == [("mcp.add", {"name": "foo", "command": "run"})]
    _last_page(host)  # a page was pushed


def test_existing_global_server_is_edited():
    host = Host(
        servers_setting=[_stdio_item("foo")],
        effective=[{"name": "foo", "transport": "stdio", "command": "run", "provenance": "global"}],
    )
    host.rt.reconcile()
    assert host.writes == [("mcp.edit", {"name": "foo", "command": "run"})]


def test_removed_global_server_is_deleted():
    host = Host(
        servers_setting=[],
        effective=[{"name": "bar", "transport": "stdio", "command": "x", "provenance": "global"}],
    )
    host.rt.reconcile()
    assert host.writes == [("mcp.delete", {"name": "bar"})]


def test_non_global_target_is_forbidden_and_surfaced():
    # 'foo' exists only in the agent-native layer, so it is not in the global set;
    # the worker attempts mcp.add and the host refuses with FORBIDDEN.
    host = Host(
        servers_setting=[_stdio_item("foo")],
        effective=[{"name": "foo", "transport": "stdio", "command": "run", "provenance": "agent-native:claude"}],
        forbidden=["foo"],
    )
    host.rt.reconcile()
    assert host.writes == [("mcp.add", {"name": "foo", "command": "run"})]
    assert "read-only" in _all_texts(_last_page(host))


def _all_texts(payload):
    """Every note/row text on the page, including inside sections."""
    texts = []
    for block in payload["blocks"]:
        texts.append(block.get("text", ""))
        texts.extend(c.get("text", "") for c in block.get("children", []))
    return " ".join(texts)


def test_unreadable_effective_set_skips_writes():
    host = Host(servers_setting=[_stdio_item("foo")], effective=[], fail_list=True)
    host.rt.reconcile()
    assert host.writes == []  # no destructive calls against unknown state
    assert "skipping sync" in _all_texts(_last_page(host))
