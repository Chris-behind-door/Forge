"""LlamaIndex Workflow -- Agent query pipeline.

Replaces the manual agent loop with a structured Workflow for clarity
and extensibility.

Flow:
  StartEvent -> ToolCallStep (LLM + tool execution loop)
             -> ExpandContextStep (adjacent chunk expansion)
             -> GenerateStep (final answer with citations)
             -> StopEvent
"""

import json
import logging
import re
from typing import Any

from llama_index.core.workflow import (
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)

from src.llm.client import call_llm
from src.llm.prompts import SYSTEM_PROMPT
from src.llm.tools import ALL_TOOLS, execute_tool
from src.llm.tools import _resolve_doc_name as _lookup_doc_name
from src.rag.vector_store import get_adjacent_chunks

logger = logging.getLogger(__name__)

# Adjacent chunk expansion: how many chunks before/after to include.
EXPAND_BEFORE = 1
EXPAND_AFTER = 1

# Maximum tool-call rounds before forcing generation.
MAX_TOOL_ROUNDS = 3

# Cap expanded context to avoid blowing up the prompt.
MAX_CONTEXT_CHARS = 15000


# ---- Helpers ----


def _parse_chunk_id(chunk_id: str) -> tuple[str, int] | None:
    """Extract ``(doc_id, index)`` from a chunk id string.

    Format: ``{doc_id}_{numeric_suffix}``.  Because *doc_id* itself may
    contain underscores (e.g. a UUID), we ``rsplit`` on the last ``_``.
    """
    parts = chunk_id.rsplit("_", 1)
    if len(parts) != 2:
        return None
    try:
        return parts[0], int(parts[1])
    except ValueError:
        return None


def _resolve_doc_name(doc_id: str) -> str:
    """Look up a human-readable document name from *doc_id*."""
    return _lookup_doc_name(doc_id)


def _expand_single_doc(
    doc_id: str,
    indices: list[int],
) -> list[dict]:
    """Expand chunks for one document by fetching adjacent context."""
    return get_adjacent_chunks(
        doc_id,
        indices,
        before=EXPAND_BEFORE,
        after=EXPAND_AFTER,
    )


def _deduplicate_chunks(chunks: list[dict]) -> list[dict]:
    """Sort by ``(doc_id, index)`` and remove duplicate chunk_ids."""
    seen: set[str] = set()
    unique: list[dict] = []
    for c in sorted(chunks, key=lambda x: (x["doc_id"], x["index"])):
        cid = c["chunk_id"]
        if cid not in seen:
            seen.add(cid)
            unique.append(c)
    return unique


def _format_source_label(chunk: dict) -> str:
    """Build a human-readable source label like ``doc.pdf#page 5``."""
    source = ""
    if chunk.get("location"):
        source = chunk["location"]
    elif chunk.get("page") is not None:
        source = f"page {chunk['page']}"

    doc_name = _resolve_doc_name(chunk["doc_id"])
    return f"{doc_name}#{source}" if source else doc_name


def _build_expanded_context(retrieved_chunks: list[dict]) -> tuple[str, list[dict]]:
    """Expand retrieved chunks with adjacent context.

    Returns ``(joined_text, expanded_chunk_metadata_list)``.

    Strategy:
    1. Group chunks by *doc_id*.
    2. Fetch adjacent chunks for each group.
    3. Deduplicate and sort.
    4. Join into a single text block.
    """
    if not retrieved_chunks:
        return "", []

    # Group chunk indices by document.
    doc_chunks: dict[str, set[int]] = {}
    for c in retrieved_chunks:
        parsed = _parse_chunk_id(c.get("chunk_id", ""))
        if parsed:
            doc_id, idx = parsed
            doc_chunks.setdefault(doc_id, set()).add(idx)

    # Expand each document's chunks independently.
    all_expanded: list[dict] = []
    for doc_id, indices in doc_chunks.items():
        all_expanded.extend(_expand_single_doc(doc_id, list(indices)))

    unique = _deduplicate_chunks(all_expanded)
    if not unique:
        return "", []

    # Join into context text.
    parts = [f"[来源:{_format_source_label(c)}]\n{c['text']}" for c in unique]
    return "\n\n---\n\n".join(parts), unique


def _extract_citations(text: str) -> list[str]:
    """Extract ``[来源:xxx]`` style citations from *text*."""
    results: list[str] = []
    i = 0
    while i < len(text):
        match = re.search(r"\[来源[：:]", text[i:])
        if not match:
            break
        start = i + match.end()
        end_match = re.search(r"\](?=[\s,，。；;）)）\n]|$)", text[start:])
        if end_match:
            results.append(text[start : start + end_match.start()])
            i = start + end_match.end()
        else:
            break
    return results


# ---- Custom Events ----


class ExpandContextEvent(Event):
    """Carries tool-call results into the context expansion stage."""

    messages: list[dict]
    rounds: int
    retrieved_chunks: list[dict]


class GenerateEvent(Event):
    """Triggers the final answer generation."""

    messages: list[dict]
    rounds: int
    expanded_text: str
    expanded_chunks: list[dict]


# ---- Workflow ----


class QueryWorkflow(Workflow):
    """RAG query workflow with tool-calling agent loop."""

    @step
    async def tool_call_step(
        self,
        ctx: Context,  # noqa: ARG002
        ev: StartEvent,
    ) -> ExpandContextEvent:
        """LLM tool-call loop: call LLM -> execute tool_calls -> repeat.

        Exits after *MAX_TOOL_ROUNDS* rounds or when the LLM stops
        requesting tools.
        """
        question: str = ev.get("question", "")
        context_messages: list[dict] = ev.get("context_messages", [])
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        # Inject session history context after system prompt
        if context_messages:
            messages.extend(context_messages)
        messages.append({"role": "user", "content": question})
        retrieved_chunks: list[dict] = []
        rounds = 0

        for round_num in range(MAX_TOOL_ROUNDS):
            rounds = round_num + 1

            response = await call_llm(messages=messages, tools=ALL_TOOLS)

            choices = response.get("choices", [])
            if not choices:
                logger.warning("Round %d: API returned empty choices", rounds)
                continue

            message = choices[0].get("message", {})
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                logger.info("Tool-call loop finished after %d rounds", rounds)
                return ExpandContextEvent(
                    messages=messages,
                    rounds=rounds,
                    retrieved_chunks=retrieved_chunks,
                )

            # Ensure content is not None (some providers return null).
            msg = dict(message)
            if msg.get("content") is None:
                msg["content"] = ""
            messages.append(msg)

            # Execute each tool_call returned by the LLM.
            for tc in tool_calls:
                function = tc["function"]
                tool_name = function["name"]
                try:
                    arguments = json.loads(function["arguments"])
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Tool %s argument parse failed: %s",
                        tool_name,
                        exc,
                    )
                    arguments = {}

                logger.info("Tool call: %s(%s)", tool_name, arguments)
                result, chunks = await execute_tool(tool_name, arguments)

                if chunks:
                    retrieved_chunks.extend(chunks)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    },
                )

        logger.warning("Reached max tool-call rounds: %d", MAX_TOOL_ROUNDS)
        return ExpandContextEvent(
            messages=messages,
            rounds=rounds,
            retrieved_chunks=retrieved_chunks,
        )

    @step
    async def expand_context_step(
        self,
        ctx: Context,  # noqa: ARG002
        ev: ExpandContextEvent,
    ) -> GenerateEvent:
        """Expand retrieved chunks with adjacent context."""
        expanded_text, expanded_chunks = _build_expanded_context(
            ev.retrieved_chunks,
        )
        return GenerateEvent(
            messages=ev.messages,
            rounds=ev.rounds,
            expanded_text=expanded_text,
            expanded_chunks=expanded_chunks,
        )

    @step
    async def generate_step(
        self,
        ctx: Context,  # noqa: ARG002
        ev: GenerateEvent,
    ) -> StopEvent:
        """Inject expanded context and call LLM for the final answer."""
        messages = ev.messages
        rounds = ev.rounds
        expanded_text = ev.expanded_text
        expanded_chunks = ev.expanded_chunks

        if expanded_text:
            if len(expanded_text) > MAX_CONTEXT_CHARS:
                logger.warning(
                    "Expanded context too long (%d chars), truncating to %d",
                    len(expanded_text),
                    MAX_CONTEXT_CHARS,
                )
                expanded_text = expanded_text[:MAX_CONTEXT_CHARS] + "\n\n[...truncated]"
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Below is the expanded retrieval context (with adjacent "
                        "chunks). Please answer the user's question based on it:\n\n"
                        f"{expanded_text}"
                    ),
                },
            )
        else:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Please answer the user's question based on the results "
                        "above. If insufficient, say so."
                    ),
                },
            )

        response = await call_llm(messages=messages)
        choices = response.get("choices", [])
        if not choices:
            return StopEvent(
                result={
                    "answer": "Sorry, no valid response received.",
                    "citations": [],
                    "rounds": rounds,
                    "retrieved_chunks": [],
                },
            )

        answer = choices[0].get("message", {}).get("content", "")
        citations = _extract_citations(answer)
        logger.info(
            "Agent done: %d rounds, %d expanded chunks",
            rounds,
            len(expanded_chunks),
        )

        return StopEvent(
            result={
                "answer": answer,
                "citations": citations,
                "rounds": rounds,
                "retrieved_chunks": expanded_chunks,
            },
        )
