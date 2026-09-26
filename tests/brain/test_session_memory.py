import json

from server.brain.session_memory import SessionMemory


def test_memory_is_scoped_and_respects_role_toggle(tmp_path):
    root = tmp_path / "memory"
    root.mkdir()
    (root / "memories.json").write_text(json.dumps([
        {"owner_id": "alice", "role_id": "role-a", "kind": "preference", "content": "喜欢简洁回答"},
        {"owner_id": "bob", "role_id": "role-a", "kind": "preference", "content": "私人信息"},
        {"owner_id": "alice", "role_id": "role-b", "kind": "goal", "content": "另一个角色"},
    ]), encoding="utf-8")
    roles = tmp_path / "roles"
    roles.mkdir()
    (roles / "roles.json").write_text(json.dumps([
        {"role_id": "role-a", "memory_enabled": True, "deleted_at": None},
        {"role_id": "role-b", "memory_enabled": False, "deleted_at": None},
    ]), encoding="utf-8")
    memory = SessionMemory("alice", root=root, role_root=roles)
    memory.select_role("role-a")
    prompt = memory.apply("系统提示")
    assert "喜欢简洁回答" in prompt
    assert "私人信息" not in prompt
    assert "另一个角色" not in prompt
    memory.select_role("role-b")
    assert memory.apply("系统提示") == "系统提示"


def test_hosted_avatar_memory_uses_its_own_settings(tmp_path, monkeypatch):
    root = tmp_path / "memory"
    root.mkdir()
    (root / "memories.json").write_text(json.dumps([
        {"owner_id": "alice", "role_id": "hosted-avatar-demo", "kind": "preference", "content": "喜欢简洁回答"},
    ]), encoding="utf-8")
    settings = tmp_path / "hosted"
    settings.mkdir()
    (settings / "settings.json").write_text(json.dumps([
        {"owner_id": "alice", "avatar_id": "demo", "memory_enabled": True},
    ]), encoding="utf-8")
    monkeypatch.setenv("HOSTED_AVATAR_SETTINGS_DIR", str(settings))
    memory = SessionMemory("alice", root=root)
    memory.select_role("hosted-avatar-demo")
    assert "喜欢简洁回答" in memory.apply("系统提示")
    other = SessionMemory("bob", root=root)
    other.select_role("hosted-avatar-demo")
    assert other.apply("系统提示") == "系统提示"
