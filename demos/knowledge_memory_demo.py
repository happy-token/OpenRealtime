"""Run real retrieval, Memory loading and context projection without a model API.

Run from the project root: .venv/bin/python -m demos.knowledge_memory_demo
Fixtures live in a temporary directory and never enter the user's catalogs.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from server.brain.session_memory import SessionMemory
from server.conversation_journal import (
    ConversationItemDraft,
    ConversationItemKind,
    ConversationItemStatus,
    InMemoryConversationJournal,
    JournalScope,
    TextContent,
)
from server.core.interaction_context import InteractionContext
from server.core.turn_content import TurnContent
from server.knowledge_base.local_catalog import LocalCatalogKnowledgeBase
from server.tools.knowledge_base_source import KnowledgeBaseToolSource
from server.voice_session.context import (
    BudgetedConversationContextProjector,
    ConservativeTokenCounter,
    ContextPolicy,
    InMemorySummaryCheckpointStore,
    SummaryCheckpointValidator,
)

OWNER = "demo#alice"
ROLE = "role-demo-shop"
DOCUMENT = "knowledge-demo-shop"


def write_json(file: Path, value: object) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


async def run_demo(root: Path) -> dict[str, object]:
    source = Path(__file__).resolve().parents[1] / "docs/demos/shop-knowledge.md"
    knowledge_root, memory_root, role_root = (
        root / "knowledge", root / "memory", root / "roles"
    )
    catalog = {
        "documents": [{
            "document_id": DOCUMENT, "owner_id": OWNER,
            "title": "星河商店售后说明 v1", "content": source.read_text(encoding="utf-8"),
        }],
        "bindings": [],
    }
    write_json(knowledge_root / "catalog.json", catalog)
    knowledge = LocalCatalogKnowledgeBase(OWNER, root=knowledge_root)
    knowledge.select_role(ROLE)
    before_binding = await knowledge.search("退货期限")
    if before_binding:
        raise RuntimeError("Unbound knowledge was exposed")
    catalog["bindings"] = [{"owner_id": OWNER, "role_id": ROLE, "document_ids": [DOCUMENT]}]
    write_json(knowledge_root / "catalog.json", catalog)
    tool = KnowledgeBaseToolSource(knowledge).list_tools()[0]
    tool_result = await tool.handler({"query": "退货期限"})
    if "签收后 7 天" not in tool_result:
        raise RuntimeError("Bound knowledge was not retrieved")
    other_user = LocalCatalogKnowledgeBase("demo#bob", root=knowledge_root)
    other_user.select_role(ROLE)
    if await other_user.search("退货期限"):
        raise RuntimeError("Knowledge crossed the user boundary")

    # Seed a persisted record; automatic extraction is a separate Next.js path.
    write_json(memory_root / "memories.json", [{
        "owner_id": OWNER, "role_id": ROLE, "kind": "preference",
        "content": "我喜欢简洁回答",
    }])
    write_json(role_root / "roles.json", [{"role_id": ROLE, "memory_enabled": True}])
    memory = SessionMemory(OWNER, root=memory_root, role_root=role_root)
    memory.select_role(ROLE)
    system_prompt = memory.apply("你是商店助手，请依据资料回答。")
    if "我喜欢简洁回答" not in system_prompt:
        raise RuntimeError("Enabled Memory was not injected")
    fresh_memory = SessionMemory(OWNER, root=memory_root, role_root=role_root)
    fresh_memory.select_role(ROLE)
    if fresh_memory.apply("系统提示") == "系统提示":
        raise RuntimeError("A fresh session could not read persisted Memory")
    other_memory = SessionMemory("demo#bob", root=memory_root, role_root=role_root)
    other_memory.select_role(ROLE)
    if other_memory.apply("系统提示") != "系统提示":
        raise RuntimeError("Memory crossed the user boundary")
    write_json(role_root / "roles.json", [{"role_id": ROLE, "memory_enabled": False}])
    if memory.apply("系统提示") != "系统提示":
        raise RuntimeError("Disabled Memory was injected")

    journal = InMemoryConversationJournal()
    context = InteractionContext(
        tenant_id="demo", user_id=OWNER, device_id="demo-browser",
        voice_session_id="voice-demo-one", thread_id="thread-demo-shop",
        turn_id="turn-demo-one", generation=1,
    )
    for item_id, kind, text in (
        ("demo-user", ConversationItemKind.USER_INPUT, "我刚签收了星河商店的商品，想退货。"),
        ("demo-assistant", ConversationItemKind.ASSISTANT_OUTPUT,
         "资料规定签收后 7 天内可以退货，商品需未使用且包装完整。"),
    ):
        await journal.append(ConversationItemDraft(
            item_id=item_id, context=context, kind=kind,
            status=ConversationItemStatus.COMPLETED,
            producer="knowledge-memory-demo", content=(TextContent(text),),
        ))
    projection = await journal.project_for_model(JournalScope.from_context(context))
    validator = SummaryCheckpointValidator()
    projector = BudgetedConversationContextProjector(
        policy=ContextPolicy(
            policy_version="demo-v1", context_window_tokens=4096,
            max_output_tokens=256, tool_schema_tokens=256,
            governing_instruction_tokens=256, current_input_tokens=256,
            safety_margin_tokens=256,
        ),
        token_counter=ConservativeTokenCounter(),
        checkpoint_store=InMemorySummaryCheckpointStore(validator),
        checkpoint_validator=validator, compressor=None,
    )
    prior_text = await projector.project_text(projection.items)
    turn = TurnContent(text="那运费谁承担？", generation=2, conversation_context=prior_text)
    if "刚签收" not in turn.model_text:
        raise RuntimeError("Prior turns did not reach the model input")
    fresh_thread = await journal.project_for_model(JournalScope("demo", OWNER, "thread-demo-new"))
    if fresh_thread.items:
        raise RuntimeError("An unrelated new thread inherited old conversation context")

    return {
        "说明": "运行真实检索、Memory 读取和上下文投影；没有调用模型，没有生成新答案。",
        "验证": {
            "未绑定资料不命中": True, "绑定后检索成功": True,
            "资料与Memory按用户隔离": True, "新Session能读取持久化Memory": True,
            "关闭Memory停止注入": True, "同一thread可投影前两轮": True,
            "新thread没有自动继承旧历史": True,
        },
        "模型输入示例": {"system_prompt": system_prompt, "user_text": turn.model_text,
                     "knowledge_tool_result": tool_result},
        "边界": "示例助手历史是预置文本；不证明UI续聊、自动提取、断线恢复或模型回答效果。",
    }


if __name__ == "__main__":
    with TemporaryDirectory(prefix="openrealtime-knowledge-memory-demo-") as directory:
        print(json.dumps(asyncio.run(run_demo(Path(directory))), ensure_ascii=False, indent=2))
