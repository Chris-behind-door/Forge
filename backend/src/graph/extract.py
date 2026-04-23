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
from pathlib import Path

from ..llm.client import call_llm
from ..rag.embeddings import embed_texts
from ..rag.scoring import rank_candidates
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

BATCH_LINK_PROMPT = """\
你是一个专业的工程决议关联分析助手。请逐一判断每组中"新决议"与"候选已有决议"之间是否存在关联。

## 关联类型
- SUPERSEDES（替代）：新决议完全替代旧决议，旧决议不再有效
- AMENDS（修改）：新决议在旧决议基础上做了部分修改
- SUPPLEMENTS（补充）：新决议对旧决议进行补充说明
- NONE：无直接关联

## 判断标准
- 两决议必须有实质性语义关联，不能仅因为关键词相似就建关联
- 同一主题的不同独立决定 → NONE

## 输出格式
严格的 JSON（不要包含其他文字）：
{{
  "groups": [
    {{
      "new_id": "新决议ID",
      "relations": [
        {{
          "existing_id": "已有决议ID",
          "type": "SUPERSEDES | AMENDS | SUPPLEMENTS | NONE",
          "reason": "判断依据（简短）"
        }}
      ]
    }}
  ]
}}

## 待判断的决议组：

{groups_text}"""


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
        lines = [line for line in lines if not line.strip().startswith("```")]
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
    batch_size: int = 5,
) -> list[dict]:
    """
    Batch-aware cross-meeting resolution linking.

    For each new resolution, find similar existing ones via embedding search.
    Then batch LLM calls (batch_size per call) with isolated candidate pools
    using BATCH_LINK_PROMPT.

    Returns list of dicts with keys: new_id, existing_id, type, reason
    Only returns confirmed relations (type != NONE).
    """
    confirmed_relations: list[dict] = []

    # Load meeting dates for temporal filtering
    from ..resolution_store import load_resolutions as _load_res
    _all_res = _load_res()
    _meeting_dates: dict[str, str] = {}
    for r in _all_res.values():
        mid = r.get("meeting_id", "")
        if mid and mid not in _meeting_dates:
            # Store meeting_id -> date mapping from resolution metadata
            _meeting_dates[mid] = r.get("meeting_date", "")
    # Also try to load from meetings.json
    try:
        _meetings_path = Path.home() / ".engineer_assistant" / "data" / "meetings.json"
        if _meetings_path.exists():
            _meetings = json.loads(_meetings_path.read_text(encoding="utf-8"))
            for mid, m in _meetings.items():
                if mid not in _meeting_dates or not _meeting_dates[mid]:
                    _meeting_dates[mid] = m.get("date", "")
    except Exception:
        pass

    current_meeting_date = _meeting_dates.get(meeting_id, "")

    # Phase 1: compute per-resolution candidates (isolated pools)
    res_candidates: list[tuple[dict, list[dict]]] = []
    for new_res in new_resolutions:
        new_id = new_res["id"]
        content = new_res["content"]

        # Generate embedding
        try:
            embedding = embed_texts([content])[0]
        except Exception as e:
            logger.warning("Embedding failed for resolution %s: %s", new_id, e)
            continue

        # Update embedding in Kùzu
        try:
            await gq.update_resolution(new_id, embedding=embedding)
        except Exception as e:
            logger.warning("Failed to update embedding for %s: %s", new_id, e)

        # Vector search for similar resolutions
        try:
            candidates = await gq.search_similar_resolutions(
                project_id, embedding, top_k=10
            )
        except Exception as e:
            logger.warning("Vector search failed for %s: %s", new_id, e)
            continue

        # Exclude own meeting
        candidates = [c for c in candidates if c.get("meeting_id") != meeting_id]

        # Temporal filter: only keep candidates from earlier or same-date meetings
        if current_meeting_date:
            candidates = [
                c for c in candidates
                if _meeting_dates.get(c.get("meeting_id", ""), "") <= current_meeting_date
            ]

        if not candidates:
            continue

        # Hybrid scoring
        scored = rank_candidates(
            candidates,
            content,
            vector_weight=0.7,
            keyword_weight=0.3,
            score_key="score",
            text_key="content",
        )
        scored = [c for c in scored if c.get("score", 0) >= 0.3]
        top_candidates = scored[:5]
        if top_candidates:
            res_candidates.append((new_res, top_candidates))

    if not res_candidates:
        return confirmed_relations

    # Phase 2: batch LLM calls (batch_size groups per call)
    from ..resolution_store import load_resolutions, save_resolutions

    for batch_start in range(0, len(res_candidates), batch_size):
        batch = res_candidates[batch_start : batch_start + batch_size]

        # Build groups_text with isolated candidate pools
        groups_text_parts: list[str] = []
        for new_res, top_candidates in batch:
            group_str = f"### 新决议 [ID: {new_res['id']}]\n{new_res['content']}\n\n候选已有决议：\n"
            for j, c in enumerate(top_candidates, 1):
                group_str += f"{j}. [ID: {c['id']}] {c['content']}\n"
            groups_text_parts.append(group_str)

        groups_text = "\n---\n\n".join(groups_text_parts)

        messages = [
            {
                "role": "system",
                "content": "你是工程决议关联分析助手，输出严格的JSON格式。",
            },
            {
                "role": "user",
                "content": BATCH_LINK_PROMPT.format(groups_text=groups_text),
            },
        ]

        try:
            result = await _call_llm_json(messages)
            groups_result = result.get("groups", [])
        except Exception as e:
            logger.warning("Batch LLM relation classification failed: %s", e)
            continue

        # Build lookup: new_id -> its top_candidates for verification
        candidate_lookup = {
            new_res["id"]: top_candidates for new_res, top_candidates in batch
        }

        for group in groups_result:
            new_id = group.get("new_id", "")
            top_candidates = candidate_lookup.get(new_id, [])
            if not top_candidates:
                continue

            for rel in group.get("relations", []):
                rel_type = rel.get("type", "NONE")
                if rel_type == "NONE":
                    continue

                existing_id = rel.get("existing_id", "")
                reason = rel.get("reason", "")

                # Verify existing_id is in this group's isolated candidates
                if not any(c["id"] == existing_id for c in top_candidates):
                    logger.warning(
                        "LLM returned unknown existing_id %s, skipping", existing_id
                    )
                    continue

                try:
                    await gq.create_relation(
                        new_id,
                        existing_id,
                        rel_type,
                        meeting_id=meeting_id,
                        reason=reason,
                        change_summary=reason,
                        supplement_content=reason,
                    )
                except Exception as e:
                    logger.error(
                        "Failed to create relation %s->%s (%s): %s",
                        new_id,
                        existing_id,
                        rel_type,
                        e,
                    )
                    continue

                # Update status for SUPERSEDES
                if rel_type == "SUPERSEDES":
                    resolutions = load_resolutions()
                    if existing_id in resolutions:
                        resolutions[existing_id]["status"] = "superseded"
                        save_resolutions(resolutions)
                    await gq.update_resolution(existing_id, status="superseded")

                confirmed_relations.append(
                    {
                        "new_id": new_id,
                        "existing_id": existing_id,
                        "type": rel_type,
                        "reason": reason,
                    }
                )

    logger.info("Created %d cross-meeting relations", len(confirmed_relations))
    return confirmed_relations
