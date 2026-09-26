import json

from server.brain.role_model import role_model_id, role_tool_ids


def test_role_model_uses_catalog_and_rejects_invalid_or_deleted(tmp_path):
    root = tmp_path / "roles"
    root.mkdir()
    (root / "roles.json").write_text(json.dumps([
        {"role_id": "role-a", "model_id": "deepseek-v4-flash", "deleted_at": None},
        {"role_id": "role-b", "model_id": "bad model", "deleted_at": None},
        {"role_id": "role-c", "model_id": "expensive-model", "deleted_at": "2026-09-23"},
    ]), encoding="utf-8")
    assert role_model_id("alice", "role-a", shared_root=root) == "deepseek-v4-flash"
    assert role_model_id("alice", "role-b", shared_root=root) is None
    assert role_model_id("alice", "role-c", shared_root=root) is None
    assert role_model_id("alice", "../roles", shared_root=root) is None


def test_hosted_avatar_tools_are_owner_scoped(tmp_path, monkeypatch):
    root = tmp_path / "hosted"
    root.mkdir()
    (root / "settings.json").write_text(json.dumps([
        {"owner_id": "alice", "avatar_id": "demo", "memory_enabled": True, "tool_ids": ["tool-time"]},
    ]), encoding="utf-8")
    monkeypatch.setenv("HOSTED_AVATAR_SETTINGS_DIR", str(root))
    assert role_tool_ids("alice", "hosted-avatar-demo") == {"tool-time"}
    assert role_tool_ids("bob", "hosted-avatar-demo") == set()
