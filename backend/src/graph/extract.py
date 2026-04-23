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
你是一个专业的工程决议关联分析助手。请逐一判断每组中"当前决议"与"候选已有决议"之间是否存在关联。

当前决议来自最近的会议，候选已有决议来自**更早**的会议。

## 关联类型
- SUPERSEDES（替代）：当前决议完全替代候选决议，候选决议不再有效
- AMENDS（修改）：当前决议在候选决议基础上做了部分修改
- SUPPLEMENTS（补充）：当前决议对候选决议进行补充说明
- NONE：无直接关联

## 判断标准
- 两决议必须有实质性语义关联，不能仅因为关键词相似就建关联
- 同一主题的不同独立决定 → NONE

## 输出格式
严格的 JSON（不要包含其他文字）：
{{
  "groups": [
    {{
      "new_id": "当前决议ID",
      "relations": [
        {{
          "existing_id": "候选决议ID",
          "type": "SUPERSEDES | AMENDS | SUPPLEMENTS | NONE",
          "reason": "判断依据（简短）"
        }}
      ]
    }}
  ]
}}

## 待判断的决议组：

{groups_text}"""

REVERSE_LINK_PROMPT = """\
你是一个专业的工程决议关联分析助手。请逐一判断每组中"候选决议"是否替代、修改或补充了"当前决议"。

当前决议来自较早的会议，候选决议来自**更晚**的会议。请判断候选决议是否对当前决议产生了影响。

## 关联类型
- SUPERSEDES（替代）：候选决议完全替代了当前决议，当前决议不再有效
- AMENDS（修改）：候选决议在当前决议基础上做了部分修改
- SUPPLEMENTS（补充）：候选决议对当前决议进行补充说明
- NONE：无直接关联

## 判断标准
- 两决议必须有实质性语义关联，不能仅因为关键词相似就建关联
- 同一主题的不同独立决定 → NONE

## 输出格式
严格的 JSON（不要包含其他文字）：
{{
  "groups": [
    {{
      "current_id": "当前决议ID",
      "relations": [
        {{
          "candidate_id": "候选决议ID",
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


async def extract_resolutions(raw_text: str, _meeting_date: str = "") -> list[dict]:
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
    Bidirectional cross-meeting resolution linking with temporal awareness.

    Phase 1: For each new resolution, find similar existing ones via embedding search.
    Split candidates into PAST (date <= current) and FUTURE (date > current).

    Phase 2a (past): Ask LLM if new resolution supersedes/amends/supplements older ones.
    Phase 2b (future): Ask LLM if newer resolutions
    supersedes/amends/supplements the current one.

    Returns list of confirmed relations.
    """
    confirmed_relations: list[dict] = []

    # Load meeting dates for temporal filtering
    _meeting_dates = _load_meeting_dates()
    current_meeting_date = _meeting_dates.get(meeting_id, "")

    # Phase 1: compute per-resolution candidates, split by time
    past_candidates: list[tuple[dict, list[dict]]] = []
    future_candidates: list[tuple[dict, list[dict]]] = []

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

        # Split by temporal direction
        past = []
        future = []
        for c in candidates:
            c_date = _meeting_dates.get(c.get("meeting_id", ""), "")
            if not current_meeting_date or not c_date:
                past.append(c)  # Unknown date, default to past
            elif c_date <= current_meeting_date:
                past.append(c)
            else:
                future.append(c)

        for group, bucket in [(past, past_candidates), (future, future_candidates)]:
            scored = rank_candidates(
                group, content,
                vector_weight=0.7, keyword_weight=0.3,
                score_key="score", text_key="content",
            )
            scored = [c for c in scored if c.get("score", 0) >= 0.3]
            top = scored[:5]
            if top:
                bucket.append((new_res, top))

    # Phase 2a: past candidates (new -> old)
    past_relations = await _batch_link(
        past_candidates, meeting_id, batch_size,
        prompt=BATCH_LINK_PROMPT,
        direction="forward",
    )
    confirmed_relations.extend(past_relations)

    # Phase 2b: future candidates (future -> new)
    future_relations = await _batch_link(
        future_candidates, meeting_id, batch_size,
        prompt=REVERSE_LINK_PROMPT,
        direction="reverse",
    )
    confirmed_relations.extend(future_relations)

    logger.info("Created %d cross-meeting relations (past: %d, future: %d)",
                len(confirmed_relations), len(past_relations), len(future_relations))
    return confirmed_relations


def _load_meeting_dates() -> dict[str, str]:
    """Load meeting_id -> date mapping from meetings.json."""
    meeting_dates: dict[str, str] = {}
    try:
        meetings_path = Path.home() / ".engineer_assistant" / "data" / "meetings.json"
        if meetings_path.exists():
            meetings = json.loads(meetings_path.read_text(encoding="utf-8"))
            for mid, m in meetings.items():
                meeting_dates[mid] = m.get("date", "")
    except Exception:
        logger.debug("Failed to load meeting dates from file")
    return meeting_dates


async def _batch_link(
    res_candidates: list[tuple[dict, list[dict]]],
    meeting_id: str,
    batch_size: int,
    prompt: str,
    direction: str,  # "forward" (new->old) or "reverse" (future->new)
) -> list[dict]:
    """Batch LLM linking for one temporal direction."""
    if not res_candidates:
        return []

    confirmed: list[dict] = []

    from ..resolution_store import load_resolutions, save_resolutions

    for batch_start in range(0, len(res_candidates), batch_size):
        batch = res_candidates[batch_start : batch_start + batch_size]

        # Build groups_text with isolated candidate pools
        groups_text_parts: list[str] = []
        for new_res, top_candidates in batch:
            if direction == "forward":
                label = "候选已有决议（来自更早的会议）："
            else:
                label = "候选决议（来自更晚的会议）："
            group_str = (
                f"### 当前决议 [ID: {new_res['id']}]"
                f"\n{new_res['content']}\n\n{label}\n"
            )
            for j, c in enumerate(top_candidates, 1):
                group_str += f"{j}. [ID: {c['id']}] {c['content']}\n"
            groups_text_parts.append(group_str)

        groups_text = "\n---\n\n".join(groups_text_parts)

        messages = [
            {"role": "system", "content": (
                "你是工程决议关联分析助手，"
                "输出严格的JSON格式。"
            )},
            {"role": "user", "content": prompt.format(groups_text=groups_text)},
        ]

        try:
            result = await _call_llm_json(messages)
            groups_result = result.get("groups", [])
        except Exception as e:
            logger.warning("Batch LLM relation classification failed: %s", e)
            continue

        candidate_lookup = {
            new_res["id"]: top_candidates for new_res, top_candidates in batch
        }

        for group in groups_result:
            if direction == "forward":
                new_id = group.get("new_id", "")
            else:
                new_id = group.get("current_id", "")
            top_candidates = candidate_lookup.get(new_id, [])
            if not top_candidates:
                continue

            for rel in group.get("relations", []):
                rel_type = rel.get("type", "NONE")
                if rel_type == "NONE":
                    continue

                if direction == "forward":
                    existing_id = rel.get("existing_id", "")
                else:
                    existing_id = rel.get("candidate_id", "")
                reason = rel.get("reason", "")

                if not any(c["id"] == existing_id for c in top_candidates):
                    logger.warning("LLM returned unknown id %s, skipping", existing_id)
                    continue

                # Determine edge direction
                if direction == "forward":
                    from_id, to_id = new_id, existing_id
                else:
                    from_id, to_id = existing_id, new_id

                try:
                    await gq.create_relation(
                        from_id, to_id, rel_type,
                        meeting_id=meeting_id,
                        reason=reason,
                        change_summary=reason,
                        supplement_content=reason,
                    )
                except Exception as e:
                    logger.error("Failed to create relation %s->%s (%s): %s",
                                 from_id, to_id, rel_type, e)
                    continue

                # Update status for SUPERSEDES
                if rel_type == "SUPERSEDES":
                    # The superseded resolution is always the 'to_id'
                    resolutions = load_resolutions()
                    if to_id in resolutions:
                        resolutions[to_id]["status"] = "superseded"
                        save_resolutions(resolutions)
                    await gq.update_resolution(to_id, status="superseded")

                confirmed.append({
                    "new_id": from_id,
                    "existing_id": to_id,
                    "type": rel_type,
                    "reason": reason,
                })

    return confirmed
