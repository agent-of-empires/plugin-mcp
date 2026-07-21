from aoe_mcp_plugin.servers import parse_kv
from aoe_mcp_plugin.servers import parse_lines
from aoe_mcp_plugin.servers import item_to_server


def test_parse_lines_strips_and_drops_blanks():
    assert parse_lines("--port\n\n  8080  \n") == ["--port", "8080"]
    assert parse_lines(None) == []
    assert parse_lines("") == []


def test_parse_kv_splits_on_first_equals():
    assert parse_kv("TOKEN=abc\nURL=https://x?a=b\n\nBAD\n=nokey") == {
        "TOKEN": "abc",
        "URL": "https://x?a=b",
    }
    assert parse_kv(None) == {}


def test_stdio_item_maps_and_omits_empty():
    entry, err = item_to_server({"name": "fs", "transport": "stdio", "command": "npx", "args": "a\nb", "env": "K=v"})
    assert err is None
    assert entry == {"name": "fs", "command": "npx", "args": ["a", "b"], "env": {"K": "v"}}

    bare, err = item_to_server({"name": "fs", "command": "run"})
    assert err is None
    assert bare == {"name": "fs", "command": "run"}  # no args/env keys when empty


def test_http_and_sse_items():
    http, err = item_to_server(
        {"name": "api", "transport": "http", "url": "https://x", "headers": "Authorization=Bearer z"}
    )
    assert err is None
    assert http == {"name": "api", "type": "http", "url": "https://x", "headers": {"Authorization": "Bearer z"}}

    sse, err = item_to_server({"name": "s", "transport": "sse", "url": "https://y"})
    assert err is None
    assert sse == {"name": "s", "type": "sse", "url": "https://y"}


def test_validation_errors():
    assert item_to_server({"transport": "stdio", "command": "x"})[1] == "server is missing a name"
    assert "requires a command" in item_to_server({"name": "a", "transport": "stdio"})[1]
    assert "requires a url" in item_to_server({"name": "a", "transport": "http"})[1]
    assert "unknown transport" in item_to_server({"name": "a", "transport": "grpc"})[1]
    assert item_to_server("nope")[0] is None
