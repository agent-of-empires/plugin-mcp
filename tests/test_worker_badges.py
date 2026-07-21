"""Drive the worker's tool-card-badge push against an in-process stub host.

The stub answers each worker->host request synchronously (like
test_worker_contract), and additionally serves `sessions.list`, so the badge
push/prune path runs without a real subprocess.
"""

from aoe_mcp_plugin.main import Runtime


class Host:
    def __init__(self, effective, sessions, kept=()):
        self.effective = effective
        self.sessions = sessions  # list of session ids, or None to fail the call
        self.kept = list(kept)
        self.sent = []
        self.rt = Runtime(send=self.send)

    def send(self, msg):
        self.sent.append(msg)
        method = msg.get("method")
        rid = msg.get("id")
        if method is None or rid is None:
            return
        if method in ("ui.state.set", "ui.state.remove"):
            return  # fire-and-forget from the worker; not awaited
        result, error = self._respond(method, msg.get("params") or {})
        reply = {"jsonrpc": "2.0", "id": rid}
        reply["error" if error is not None else "result"] = error if error is not None else result
        self.rt.inbox.put(reply)

    def _respond(self, method, _params):
        if method == "config.get":
            return {"value": []}, None
        if method == "mcp.list":
            return {"servers": self.effective}, None
        if method == "mcp.resolve":
            return {
                "effective": self.effective,
                "conflicts": [],
                "keptOnRemoval": self.kept,
                "driftPaused": False,
            }, None
        if method == "sessions.list":
            if self.sessions is None:
                return None, {"code": -32603, "message": "boom"}
            return {"sessions": [{"id": s} for s in self.sessions]}, None
        return {}, None


def _badge_sets(host):
    return [m for m in host.sent if m.get("method") == "ui.state.set" and m["params"]["slot"] == "tool-card-badge"]


def _badge_removes(host):
    return [m for m in host.sent if m.get("method") == "ui.state.remove" and m["params"]["slot"] == "tool-card-badge"]


def test_reconcile_pushes_a_badge_set_per_session():
    host = Host(
        effective=[{"name": "github", "provenance": "global"}],
        sessions=["s1", "s2"],
    )
    host.rt.reconcile()
    sets = _badge_sets(host)
    assert {m["params"]["session_id"] for m in sets} == {"s1", "s2"}
    for m in sets:
        assert m["params"]["id"] == "provenance"
        item = m["params"]["payload"]["items"][0]
        assert item["target"] == {"kind": "mcp", "name": "github"}
        assert item["text"] == "AoE"
    assert host.rt._badge_session_ids == {"s1", "s2"}


def test_kept_on_removal_servers_are_badged():
    host = Host(
        effective=[],
        kept=[{"name": "legacy", "provenance": "kept-on-removal:claude"}],
        sessions=["s1"],
    )
    host.rt.reconcile()
    items = _badge_sets(host)[-1]["params"]["payload"]["items"]
    assert [i["target"]["name"] for i in items] == ["legacy"]
    assert items[0]["text"] == "Kept"


def test_poll_prunes_vanished_session():
    host = Host(effective=[{"name": "github", "provenance": "global"}], sessions=["s1", "s2"])
    host.rt.reconcile()
    host.sent.clear()
    host.sessions = ["s1"]  # s2 closed
    host.rt._poll_badges()
    assert [m["params"]["session_id"] for m in _badge_removes(host)] == ["s2"]
    assert host.rt._badge_session_ids == {"s1"}


def test_poll_pushes_to_newly_opened_session():
    host = Host(effective=[{"name": "github", "provenance": "global"}], sessions=["s1"])
    host.rt.reconcile()
    host.sent.clear()
    host.sessions = ["s1", "s2"]  # s2 opened
    host.rt._poll_badges()
    assert {m["params"]["session_id"] for m in _badge_sets(host)} == {"s1", "s2"}


def test_poll_is_noop_when_session_set_unchanged():
    host = Host(effective=[{"name": "github", "provenance": "global"}], sessions=["s1"])
    host.rt.reconcile()
    host.sent.clear()
    host.rt._poll_badges()
    # The cheap sessions.list tick still runs; but an unchanged set means no
    # re-resolve and no badge re-push.
    methods = [m.get("method") for m in host.sent]
    assert methods == ["sessions.list"]
    assert _badge_sets(host) == []
    assert _badge_removes(host) == []


def test_unavailable_session_list_skips_push_and_prune():
    host = Host(effective=[{"name": "github", "provenance": "global"}], sessions=["s1"])
    host.rt.reconcile()
    host.rt._badge_session_ids = {"s1"}
    host.sent.clear()
    host.sessions = None  # host fails sessions.list
    host.rt._refresh_badges({"effective": host.effective})
    assert _badge_sets(host) == []
    assert _badge_removes(host) == []
    assert host.rt._badge_session_ids == {"s1"}  # untouched
