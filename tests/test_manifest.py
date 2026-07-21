from pathlib import Path

try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

MANIFEST = Path(__file__).resolve().parents[1] / "aoe-plugin.toml"


def _load():
    with MANIFEST.open("rb") as f:
        return tomllib.load(f)


def test_identity_and_api_version():
    m = _load()
    assert m["id"] == "agent-of-empires.mcp"
    # settings-page and object_list both require api_version >= 10 (host max).
    assert m["api_version"] == 10


def test_capabilities_cover_read_and_write():
    caps = _load()["capabilities"]
    assert {"runtime.worker", "config.read", "config.write"} <= set(caps)


def test_declares_settings_page_slot():
    ui = _load()["ui"]
    assert any(u["slot"] == "settings-page" and u["id"] == "mcp_manager" for u in ui)


def test_servers_object_list_fields():
    servers = next(s for s in _load()["settings"] if s["key"] == "servers")
    assert servers["type"] == "object_list"
    assert servers["item_id_key"] == "name"
    keys = {f["key"] for f in servers["fields"]}
    assert keys == {"name", "transport", "command", "args", "url", "env", "headers"}
    transport = next(f for f in servers["fields"] if f["key"] == "transport")
    assert transport["type"] == "select"
    assert transport["options"] == ["stdio", "http", "sse"]
