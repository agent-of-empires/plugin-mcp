from aoe_mcp_plugin.uistate import build_page


def _kinds(payload):
    return [b.get("kind") for b in payload["blocks"]]


def test_empty_effective_shows_placeholder_and_refresh():
    payload = build_page({"effective": []}, errors=[], status=None)
    assert payload["title"] == "MCP servers"
    texts = [b.get("text") for b in payload["blocks"] if b.get("kind") == "note"]
    assert "No servers forwarded." in texts
    # An action button to force a refresh is always present.
    assert any(b.get("kind") == "action" and b.get("method") == "refresh" for b in payload["blocks"])


def test_server_row_marks_global_and_redacts():
    resolve = {
        "effective": [
            {
                "name": "fs",
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "server"],
                "envNames": ["TOKEN"],
                "provenance": "global",
            },
            {"name": "n", "transport": "http", "url": "https://x", "provenance": "agent-native:claude"},
        ]
    }
    rows = [b for b in build_page(resolve, [], None)["blocks"] if b.get("kind") == "row"]
    by_name = {r["label"]: r for r in rows}
    assert by_name["fs"]["value"] == "npx -y server  [env: TOKEN]"
    assert by_name["fs"]["tone"] == "success"  # global is the editable layer
    assert "tone" not in by_name["n"]
    assert by_name["n"]["value"] == "https://x"


def test_errors_render_as_danger_section():
    payload = build_page({"effective": []}, errors=["'x': read-only layer, not written (owned by native)"], status=None)
    section = next(b for b in payload["blocks"] if b.get("kind") == "section" and b.get("title") == "Problems")
    assert section["tone"] == "danger"
    assert any("read-only" in c.get("text", "") for c in section["children"])


def test_conflicts_and_drift_and_status():
    resolve = {"effective": [], "conflicts": [{"name": "c"}], "driftPaused": True}
    payload = build_page(resolve, [], status="Synced 1 change(s).")
    assert any(b.get("kind") == "section" and b.get("title") == "Conflicts" for b in payload["blocks"])
    danger_notes = [b.get("text", "") for b in payload["blocks"] if b.get("tone") == "danger"]
    assert any("Drift detection is paused" in t for t in danger_notes)
    # status note only shows when there are no errors
    assert any(b.get("text") == "Synced 1 change(s)." for b in payload["blocks"])
