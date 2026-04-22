"""
LLM-based resolution extraction and cross-meeting linking.

Flow:
1. Extract resolutions from meeting notes text via LLM
2. Generate embeddings for each resolution
3. For each new resolution, find similar existing ones via vector search
4. Ask LLM to classify the relationship (SUPERSEDES/AMENDS/SUPPLEMENTS/NONE)
5. Create edges in Kùzu for confirmed relations
"""

import json
import logging
from typing import Any

from ..llm.client import call_llm
from ..rag.embeddings import embed_texts
from ..rag.scoring import rank_candidates, cosine_to_score
from . import queries as gq

logger = logging.getLogger(__name__)

# --------------- Prompts ---------------

EXTRACT_PROMPT = """\
你是一个专业的会议纪要分析助手。请从以下会议纪要中提取所有**决议**（决定、共识、通过的方案）。

要求：
- 每个独立的决定/共识提取为一条决议
- 保留关键数据（数值、标准、人名、日期）
- 忽略纯讨论过程，只提取最终决定
- 如果纪要中没有明确的决议，返回空列表
- 不要编造内容，只提取纪要中明确提到的决定

输出严格的 JSON 格式（不要包含其他文字）：
{{
  "resolutions": [
    {{
      "index": 1,
      "content": "决议内容的简洁准确描述",
      "context": "该决议的简要上下文（谁提出、关键讨论点）"
    }}
  ]
}}

会议纪要：
---
{raw_text}
---"""

LINK_PROMPT = """\
你是一个专业的工程决议关联分析助手。请判断新决议与已有决议之间是否存在以下关联之一：

- SUPERSEDES（替代）：新决议完全替代旧决议，旧决议不再有效
  例如："改为XX"、"不用XX了"、"调整为YY"
- AMENDS（修改）：新决议在旧决议基础上做了部分修改
  例如："在原方案基础上增加XX"、"将YY调整为ZZ"
- SUPPLEMENTS（补充）：新决议对旧决议进行补充说明
  例如："上次那个决议，补充说明如下"、"关于XX决议，进一步明确..."
- NONE：无直接关联

判断标准：
- 必须保守判断！只有明确存在关联才标注，不确定则标 NONE
- 两决议必须有实质性语义关联，不能仅因为关键词相似就建关联
- 同一主题的不同独立决定 → NONE

新决议：{new_content}

已有决议列表：
{existing_list}

输出严格的 JSON 格式（不要包含其他文字）：
{{
  "relations": [
    {{
      "existing_id": "决议ID",
      "type": "SUPERSEDES | AMENDS | SUPPLEMENTS | NONE",
      "reason": "判断依据（简短）"
    }}
  ]
}}"""


# --------------- Helper ---------------

async def _call_llm_json(messages: list[dict]) -> dict:
    """Call LLM and parse JSON from response."""
    resp = await call_llm(messages)
    text = resp["choices"][0]["message"]["content"]
    # Try to extract JSON from markdown code block or raw text
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last line (```json ... ```)
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)
    return json.loads(text)


# --------------- Main API ---------------

async def extract_resolutions(raw_text: str, meeting_date: str) -> list[dict]:
    """
    Step 1: Extract structured resolutions from meeting notes via LLM.

    Returns list of dicts with keys: index, content, context
    """
    if not raw_text.strip():
        return []

    messages = [
        {"role": "system", "content": "你是会议纪要分析助手，输出严格的JSON格式。"},
        {"role": "user", "content": EXTRACT_PROMPT.format(raw_text=raw_text)},
    ]

    try:
        result = await _call_llm_json(messages)
        resolutions = result.get("resolutions", [])
        logger.info("LLM extracted %d resolutions from meeting notes", len(resolutions))
        return resolutions
    except Exception as e:
        logger.error("Resolution extraction failed: %s", e)
        return []


async def find_and_create_links(
    new_resolutions: list[dict],
    project_id: str,
    meeting_id: str,
) -> list[dict]:
    """
    Step 2: For each new resolution, find similar existing ones via embedding
    search, then ask LLM to classify the relationship.

    Returns list of dicts with keys: new_id, existing_id, type, reason
    Only returns confirmed relations (type != NONE).
    """
    confirmed_relations = []

    for new_res in new_resolutions:
        new_id = new_res["id"]
        content = new_res["content"]

        # Generate embedding
        try:
            embeddings = embed_texts([content])
            embedding = embeddings[0]
        except Exception as e:
            logger.warning("Embedding failed for resolution %s: %s", new_id, e)
            continue

        # Update embedding in Kùzu
        try:
            await gq.update_resolution(new_id, embedding=embedding)
        except Exception as e:
            logger.warning("Failed to update embedding for %s: %s", new_id, e)

        # Vector search for similar resolutions (exclude own meeting)
        try:
            candidates = await gq.search_similar_resolutions(
                project_id, embedding, top_k=10
            )
            logger.info("[DEBUG] Resolution %s: vector search returned %d candidates", new_id, len(candidates))
        except Exception as e:
            logger.warning("Vector search failed for %s: %s", new_id, e)
            continue

        # Exclude own meeting
        candidates = [c for c in candidates if c.get('meeting_id') != meeting_id]
        if not candidates:
            continue

        # Hybrid scoring (vector + keyword)
        scored = rank_candidates(
            candidates, content,
            vector_weight=0.7, keyword_weight=0.3,
            score_key="score", text_key="content",
        )

        # Filter: keep candidates with score >= 0.3
        scored = [c for c in scored if c.get("score", 0) >= 0.3]
        if not scored:
            continue

        # Build context for LLM (use top 5)
        top_candidates = scored[:5]
        existing_list = ""
        for i, c in enumerate(top_candidates, 1):
            existing_list += f"{i}. [ID: {c['id']}] {c['content']}\n"

        messages = [
            {"role": "system", "content": "你是工程决议关联分析助手，输出严格的JSON格式。判断必须保守，不确定则标NONE。"},
            {"role": "user", "content": LINK_PROMPT.format(
                new_content=content, existing_list=existing_list
            )},
        ]

        try:
            result = await _call_llm_json(messages)
            relations = result.get("relations", [])
        except Exception as e:
            logger.warning("LLM relation classification failed for %s: %s", new_id, e)
            continue

        for rel in relations:
            rel_type = rel.get("type", "NONE")
            if rel_type == "NONE":
                continue

            existing_id = rel.get("existing_id", "")
            reason = rel.get("reason", "")

            # Verify existing_id is in top_candidates (safety check)
            if not any(c["id"] == existing_id for c in top_candidates):
                logger.warning("LLM returned unknown existing_id %s, skipping", existing_id)
                continue

            try:
                await gq.create_relation(
                    new_id, existing_id, rel_type,
                    meeting_id=meeting_id,
                    reason=reason,
                    change_summary=reason,
                    supplement_content=reason,
                )
            except Exception as e:
                logger.error("Failed to create relation %s->%s (%s): %s",
                             new_id, existing_id, rel_type, e)
                continue

            # Update status for SUPERSEDES
            if rel_type == "SUPERSEDES":
                # Update JSON
                from ..routers.meetings import _load_resolutions, _save_resolutions
                resolutions = _load_resolutions()
                if existing_id in resolutions:
                    resolutions[existing_id]["status"] = "superseded"
                    _save_resolutions(resolutions)
                await gq.update_resolution(existing_id, status="superseded")

            confirmed_relations.append({
                "new_id": new_id,
                "existing_id": existing_id,
                "type": rel_type,
                "reason": reason,
            })

    logger.info("Created %d cross-meeting relations", len(confirmed_relations))
    return confirmed_relations
