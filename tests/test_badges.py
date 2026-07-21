"""Pure provenance -> tool-card-badge mapping.

Covers the issue's user stories at the plugin layer:
- Story 1: a called MCP server's card gets a source badge keyed by server name.
- Story 2: the badge derives from the provenance value via one function, and the
  canonical provenance label is preserved so it stays consistent with the
  settings-page listing.
"""

from aoe_mcp_plugin import badges


def test_each_provenance_maps_to_expected_text_and_tone():
    cases = {
        "global": ("AoE", "info"),
        "project-local": ("Project", "info"),
        "agent-native:claude": ("Claude", "neutral"),
        "profile:rust": ("Profile", "info"),
        "kept-on-removal:claude": ("Kept", "warn"),
    }
    for label, (text, tone) in cases.items():
        display = badges.provenance_display(label)
        assert display["text"] == text
        assert display["tone"] == tone


def test_unknown_provenance_falls_back_to_raw_label():
    display = badges.provenance_display("brand-new-variant")
    assert display["text"] == "brand-new-variant"
    assert display["tone"] == "neutral"
    assert display["tooltip"] == "brand-new-variant"


def test_agent_native_preserves_uppercased_agent_names():
    assert badges.provenance_display("agent-native:GPT")["text"] == "GPT"


def test_badge_item_is_keyed_by_raw_server_name():
    item = badges.badge_item({"name": "github", "provenance": "global"})
    assert item is not None
    assert item["target"] == {"kind": "mcp", "name": "github"}
    assert item["text"] == "AoE"
    # Story 2: canonical label wording is reconcilable via the tooltip.
    assert item["tooltip"] == "AoE-managed (global)"


def test_badge_item_appends_shadow_chain_to_tooltip():
    item = badges.badge_item(
        {"name": "db", "provenance": "profile:rust", "shadowed": ["global", "agent-native:claude"]},
    )
    assert item is not None
    assert item["tooltip"] == "Profile: rust; shadows: global, agent-native:claude"


def test_badge_item_drops_server_without_name():
    assert badges.badge_item({"provenance": "global"}) is None
    assert badges.badge_item({"name": "", "provenance": "global"}) is None


def test_callable_servers_merges_effective_and_kept_deduped():
    resolve = {
        "effective": [{"name": "github", "provenance": "global"}],
        "keptOnRemoval": [
            {"name": "github", "provenance": "kept-on-removal:claude"},  # dup, effective wins
            {"name": "old", "provenance": "kept-on-removal:claude"},
        ],
    }
    servers = badges.callable_servers(resolve)
    assert [s["name"] for s in servers] == ["github", "old"]
    assert servers[0]["provenance"] == "global"


def test_callable_servers_tolerates_missing_groups():
    assert badges.callable_servers(None) == []
    assert badges.callable_servers({}) == []


def test_badge_items_one_entry_per_named_server():
    servers = [
        {"name": "github", "provenance": "global"},
        {"name": "sentry", "provenance": "agent-native:claude"},
        {"provenance": "global"},  # unnamed, dropped
    ]
    items = badges.badge_items(servers)
    assert [i["target"]["name"] for i in items] == ["github", "sentry"]
