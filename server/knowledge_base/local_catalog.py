"""User- and role-scoped local text retrieval shared with the Next.js catalog."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_ROLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,159}$")
_SAMPLE_ID = "shared-openrealtime-guide"
_SAMPLE_TITLE = "共享示例 · OpenRealtime 使用说明"
_SAMPLE_TEXT = ("OpenRealtime 的角色可以使用对话、离线数字人、离线加口型和实时数字人模式。"
                "声音是角色必选配置，Persona 可选。知识库资料按用户隔离，并可为不同角色分别绑定。"
                "共享示例仅用于测试检索。")


class LocalCatalogKnowledgeBase:
    def __init__(self, user_id: str, *, root: Path | None = None) -> None:
        self._user_id = user_id
        self._root = root or Path(os.environ.get("KNOWLEDGE_CATALOG_DIR") or ".openrealtime/knowledge")
        self._role_id: str | None = None

    def select_role(self, role_id: str | None) -> bool:
        """A role ID is only a selector; ownership and bindings are checked on every read."""
        self._role_id = role_id if role_id and _ROLE_ID.fullmatch(role_id) else None
        return self._role_id is not None

    async def search(self, query: str, *, top_k: int = 3) -> list[str]:
        if not self._role_id or len(query) > 500:
            return []
        terms = set(re.findall(r"[\u3400-\u9fff]{1,2}|[a-zA-Z0-9]{2,}", query.lower()))
        if not terms:
            return []
        try:
            catalog = json.loads((self._root / "catalog.json").read_text(encoding="utf-8"))
            bindings = catalog["bindings"]
            documents = catalog["documents"]
            if not isinstance(bindings, list) or not isinstance(documents, list):
                return []
        except (OSError, ValueError, KeyError, TypeError):
            return []
        bound_ids: set[str] = set()
        for binding in bindings:
            if (isinstance(binding, dict) and binding.get("owner_id") == self._user_id
                    and binding.get("role_id") == self._role_id
                    and isinstance(binding.get("document_ids"), list)):
                bound_ids = set(value for value in binding["document_ids"] if isinstance(value, str))
                break
        if not bound_ids:
            return []
        available = [dict(document_id=_SAMPLE_ID, title=_SAMPLE_TITLE, content=_SAMPLE_TEXT, owner_id=None)]
        available.extend(doc for doc in documents if isinstance(doc, dict)
                         and doc.get("owner_id") == self._user_id)
        ranked: list[tuple[int, str]] = []
        for doc in available:
            if doc.get("document_id") not in bound_ids:
                continue
            title, content = doc.get("title"), doc.get("content")
            if not isinstance(title, str) or not isinstance(content, str) or len(content) > 32_000:
                continue
            for start in range(0, len(content), 480):
                excerpt = content[start:start + 560]
                score = sum(term in excerpt.lower() for term in terms)
                if score:
                    # Explicit source and data boundary: retrieved text is never an instruction.
                    metadata = {"title": title[:120], "document_id": doc["document_id"]}
                    if isinstance(doc.get("source_url"), str):
                        metadata["source_url"] = doc["source_url"]
                    source = json.dumps(metadata, ensure_ascii=False)
                    ranked.append((score, f"[资料来源: {source}]\n"
                                   f"<untrusted_knowledge>\n{excerpt}\n</untrusted_knowledge>"))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [passage for _, passage in ranked[:max(0, min(top_k, 5))]]
