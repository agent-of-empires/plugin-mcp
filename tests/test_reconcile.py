from aoe_mcp_plugin.reconcile import plan


def _stdio(name):
    return {"name": name, "transport": "stdio", "command": "run"}


def test_add_for_new_edit_for_existing():
    ops, errors = plan([_stdio("new"), _stdio("keep")], current_global=["keep"])
    assert errors == []
    kinds = {op["name"]: op["kind"] for op in ops}
    assert kinds == {"new": "add", "keep": "edit"}
    add = next(op for op in ops if op["name"] == "new")
    assert add["entry"] == {"name": "new", "command": "run"}


def test_delete_for_removed_global():
    ops, errors = plan([], current_global=["gone", "also"])
    assert errors == []
    assert [op["kind"] for op in ops] == ["delete", "delete"]
    assert [op["name"] for op in ops] == ["also", "gone"]  # deletes are sorted
    assert "entry" not in ops[0]


def test_duplicate_names_error_and_keep_first():
    ops, errors = plan([_stdio("dup"), _stdio("dup")], current_global=[])
    assert len(ops) == 1
    assert any("duplicate" in e for e in errors)


def test_invalid_item_is_skipped_with_error():
    ops, errors = plan([{"name": "bad", "transport": "stdio"}, _stdio("ok")], current_global=[])
    assert [op["name"] for op in ops] == ["ok"]
    assert any("requires a command" in e for e in errors)


def test_non_list_input_is_empty_plan():
    assert plan(None, current_global=[]) == ([], [])
