import json
from pathlib import Path

import pytest

from server.brain.avatar_persona import AvatarPersonaPromptCatalog, SessionAvatarPersona


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_avatar_persona_prompt_loads_linked_markdown_in_openclaw_order(tmp_path):
    persona_root = tmp_path / "personas"
    persona_dir = persona_root / "intellectual-warmth"
    persona_dir.mkdir(parents=True)
    (persona_dir / "AGENTS.md").write_text("对话规则", encoding="utf-8")
    (persona_dir / "SOUL.md").write_text("温柔而清醒", encoding="utf-8")
    (persona_dir / "IDENTITY.md").write_text("姓名：昭宁", encoding="utf-8")
    links_path = tmp_path / "avatar-persona-links.json"
    links_path.write_text(
        json.dumps({
            "version": 2,
            "links": {
                "avatar-zhaoning": {
                    "personaId": "intellectual-warmth",
                    "avatarDisplayName": "昭宁",
                }
            },
        }),
        encoding="utf-8",
    )

    catalog = AvatarPersonaPromptCatalog(
        persona_root=persona_root,
        links_path=links_path,
    )

    assert catalog.system_prompt_for_avatar("avatar-zhaoning", "BASE") == (
        "BASE\n\n"
        "# Role Context\n"
        "The selected role's display name is 昭宁. Use this name when introducing "
        "yourself; the Persona remains a reusable style asset.\n\n"
        "# Persona Context\n"
        "The following trusted Persona files are linked to the selected Avatar.\n\n"
        "## AGENTS.md\n\n对话规则\n\n"
        "## SOUL.md\n\n温柔而清醒\n\n"
        "## IDENTITY.md\n\n姓名：昭宁"
    )


def test_avatar_persona_prompt_rejects_untrusted_paths(tmp_path):
    links_path = tmp_path / "avatar-persona-links.json"
    links_path.write_text(
        json.dumps({
            "version": 2,
            "links": {
                "avatar-zhaoning": {
                    "personaId": "../outside",
                    "avatarDisplayName": "昭宁",
                }
            },
        }),
        encoding="utf-8",
    )
    catalog = AvatarPersonaPromptCatalog(
        persona_root=tmp_path / "personas",
        links_path=links_path,
    )

    with pytest.raises(ValueError, match="Persona ID"):
        catalog.system_prompt_for_avatar("avatar-zhaoning", "BASE")

    with pytest.raises(ValueError, match="Avatar ID"):
        catalog.system_prompt_for_avatar("../../catalog", "BASE")


def test_session_avatar_persona_switches_and_clears_the_active_prompt(tmp_path):
    persona_root = tmp_path / "personas"
    persona_dir = persona_root / "melancholic-mist"
    persona_dir.mkdir(parents=True)
    (persona_dir / "IDENTITY.md").write_text("# 忧郁薄雾", encoding="utf-8")
    (persona_dir / "SOUL.md").write_text("安静而克制", encoding="utf-8")
    links_path = tmp_path / "avatar-persona-links.json"
    links_path.write_text(
        json.dumps({
            "version": 2,
            "links": {
                "avatar-qingzhao": {
                    "personaId": "melancholic-mist",
                    "avatarDisplayName": "清照",
                }
            },
        }),
        encoding="utf-8",
    )
    context = SessionAvatarPersona(
        AvatarPersonaPromptCatalog(
            persona_root=persona_root,
            links_path=links_path,
        )
    )

    assert context.apply("BASE") == "BASE"
    assert context.select_avatar("avatar-qingzhao") == "melancholic-mist"
    assert "display name is 清照" in context.apply("BASE")
    assert "# 忧郁薄雾" in context.apply("BASE")
    assert context.select_avatar(None) is None
    assert context.apply("BASE") == "BASE"


def test_session_persona_can_be_selected_without_an_avatar(tmp_path):
    persona_root = tmp_path / "personas"
    persona_dir = persona_root / "intellectual-warmth"
    persona_dir.mkdir(parents=True)
    (persona_dir / "IDENTITY.md").write_text("# 产品顾问", encoding="utf-8")
    (persona_dir / "SOUL.md").write_text("清晰而耐心", encoding="utf-8")
    context = SessionAvatarPersona(
        AvatarPersonaPromptCatalog(
            persona_root=persona_root,
            links_path=tmp_path / "missing-links.json",
        )
    )

    assert context.select(
        persona_id="intellectual-warmth",
    ) == "intellectual-warmth"
    assert "# Role Context" not in context.apply("BASE")
    assert "## SOUL.md" in context.apply("BASE")


def test_missing_persona_catalog_keeps_the_default_brain_prompt(tmp_path):
    catalog = AvatarPersonaPromptCatalog(
        persona_root=tmp_path / "personas",
        links_path=tmp_path / "missing-links.json",
    )

    assert catalog.system_prompt_for_avatar("avatar-unconfigured", "BASE") == "BASE"


def test_link_with_missing_persona_files_keeps_the_default_brain_prompt(tmp_path):
    links_path = tmp_path / "avatar-persona-links.json"
    links_path.write_text(
        json.dumps({
            "version": 2,
            "links": {
                "avatar-unconfigured": {
                    "personaId": "missing",
                    "avatarDisplayName": "未配置",
                }
            },
        }),
        encoding="utf-8",
    )
    catalog = AvatarPersonaPromptCatalog(
        persona_root=tmp_path / "personas",
        links_path=links_path,
    )

    assert catalog.system_prompt_for_avatar("avatar-unconfigured", "BASE") == "BASE"


@pytest.mark.parametrize(
    ("avatar_id", "avatar_name", "persona_name"),
    [
        ("default-anam", "Shuchang", "知性温柔"),
        ("shuchang", "Shuchang", "知性温柔"),
        ("companion", "陪伴", "柔光纯欲"),
        ("avatar-zhaoning", "昭宁", "知性温柔"),
        ("avatar-meichuqing", "梅初晴", "甜美元气"),
        ("avatar-qingyun", "清韫", "忧郁薄雾"),
        ("avatar-selin", "瑟琳", "浪漫法式"),
        ("avatar-shiruoshui", "施若水", "柔光纯欲"),
        ("avatar-zhaoyue", "曌月", "冷艳都市"),
        ("avatar-qingzhao", "清照", "忧郁薄雾"),
    ],
)
def test_project_avatar_personas_are_complete(avatar_id, avatar_name, persona_name):
    catalog = AvatarPersonaPromptCatalog(
        persona_root=PROJECT_ROOT / "config" / "personas",
        links_path=PROJECT_ROOT / "config" / "avatar-persona-links.json",
    )

    prompt = catalog.system_prompt_for_avatar(avatar_id, "BASE")

    assert f"display name is {avatar_name}" in prompt
    assert f"# {persona_name}" in prompt
    for filename in ("AGENTS.md", "SOUL.md", "IDENTITY.md"):
        assert f"## {filename}" in prompt


def test_avatar_persona_prompt_rejects_oversized_files(tmp_path):
    persona_root = tmp_path / "personas"
    persona_dir = persona_root / "intellectual-warmth"
    persona_dir.mkdir(parents=True)
    (persona_dir / "SOUL.md").write_text("x" * 8_001, encoding="utf-8")
    links_path = tmp_path / "avatar-persona-links.json"
    links_path.write_text(
        json.dumps({
            "version": 2,
            "links": {
                "avatar-zhaoning": {
                    "personaId": "intellectual-warmth",
                    "avatarDisplayName": "昭宁",
                }
            },
        }),
        encoding="utf-8",
    )

    catalog = AvatarPersonaPromptCatalog(persona_root=persona_root, links_path=links_path)

    with pytest.raises(ValueError, match="too large"):
        catalog.system_prompt_for_avatar("avatar-zhaoning", "BASE")


def test_agents_file_is_optional_but_identity_and_soul_are_required(tmp_path):
    persona_root = tmp_path / "personas"
    persona_dir = persona_root / "intellectual-warmth"
    persona_dir.mkdir(parents=True)
    (persona_dir / "SOUL.md").write_text("温柔而清醒", encoding="utf-8")
    (persona_dir / "IDENTITY.md").write_text("# 昭宁", encoding="utf-8")
    links_path = tmp_path / "avatar-persona-links.json"
    links_path.write_text(
        json.dumps({
            "version": 2,
            "links": {
                "avatar-zhaoning": {
                    "personaId": "intellectual-warmth",
                    "avatarDisplayName": "昭宁",
                }
            },
        }),
        encoding="utf-8",
    )
    catalog = AvatarPersonaPromptCatalog(persona_root=persona_root, links_path=links_path)

    prompt = catalog.system_prompt_for_avatar("avatar-zhaoning", "BASE")

    assert "## AGENTS.md" not in prompt
    assert "## SOUL.md" in prompt
    assert "## IDENTITY.md" in prompt

    (persona_dir / "SOUL.md").unlink()
    with pytest.raises(ValueError, match="missing required files"):
        catalog.system_prompt_for_avatar("avatar-zhaoning", "BASE")
