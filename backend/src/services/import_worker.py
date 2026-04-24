"""Async import worker: serial queue for meeting file processing."""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .meeting_service import _load_meetings, _save_meetings, _extract_text_from_file

logger = logging.getLogger(__name__)


@dataclass
class ImportTask:
    meeting_id: str
    project_id: str
    tmp_path: Path
    suffix: str


@dataclass
class ImportQueue:
    queue: asyncio.Queue[ImportTask] = field(default_factory=asyncio.Queue)
    _current: str | None = field(default=None, repr=False)
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    def enqueue(self, task: ImportTask) -> None:
        self.queue.put_nowait(task)

    def cancel_current(self) -> None:
        """Signal the current processing task to abort."""
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def clear_cancel(self) -> None:
        self._cancel_event.clear()

    def remove_from_queue(self, meeting_id: str) -> bool:
        """Remove a queued (not yet processing) task. Returns True if found."""
        new_items = []
        found = False
        while not self.queue.empty():
            item = self.queue.get_nowait()
            if item.meeting_id == meeting_id:
                found = True
                item.tmp_path.unlink(missing_ok=True)
            else:
                new_items.append(item)
        for item in new_items:
            self.queue.put_nowait(item)
        return found

    @property
    def current(self) -> str | None:
        return self._current

    def queued_ids(self) -> list[str]:
        return [t.meeting_id for t in self.queue._queue]  # noqa: SLF001

    def failed_ids(self) -> list[str]:
        meetings = _load_meetings()
        return [mid for mid, m in meetings.items() if m.get("status") == "failed"]


# Module-level singleton
_import_queue = ImportQueue()


def get_import_queue() -> ImportQueue:
    return _import_queue


def _set_meeting_status(meeting_id: str, status: str, error: str | None = None) -> None:
    meetings = _load_meetings()
    if meeting_id in meetings:
        meetings[meeting_id]["status"] = status
        meetings[meeting_id]["error"] = error
        _save_meetings(meetings)


async def _process_task(task: ImportTask) -> None:
    """Process a single import task: extract text → LLM → embeddings → links."""
    from ..graph.extract import extract_resolutions
    from .resolution_service import batch_create_and_link

    _set_meeting_status(task.meeting_id, "processing")
    _import_queue._current = task.meeting_id  # noqa: SLF001
    _import_queue.clear_cancel()

    def _cancelled() -> bool:
        return _import_queue.is_cancelled()

    try:
        raw_text = _extract_text_from_file(task.tmp_path, task.suffix)

        if not raw_text.strip():
            _set_meeting_status(task.meeting_id, "failed", "文件中未提取到有效文本")
            return

        if _cancelled():
            logger.info("Import cancelled for %s after text extraction", task.meeting_id)
            return

        # Update raw_text in meeting record
        meetings = _load_meetings()
        meetings[task.meeting_id]["raw_text"] = raw_text
        _save_meetings(meetings)

        # Extract resolutions via LLM
        meeting = meetings[task.meeting_id]
        extracted = await extract_resolutions(raw_text, meeting.get("date", ""))

        if _cancelled():
            logger.info("Import cancelled for %s after LLM extraction", task.meeting_id)
            return

        if extracted:
            await batch_create_and_link(extracted, task.meeting_id, task.project_id)

        if _cancelled():
            logger.info("Import cancelled for %s after linking", task.meeting_id)
            return

        _set_meeting_status(task.meeting_id, "active")
        logger.info("Import completed for meeting %s", task.meeting_id)

    except Exception as e:
        if _cancelled():
            logger.info("Import was cancelled for %s", task.meeting_id)
        else:
            logger.exception("Import failed for meeting %s", task.meeting_id)
            _set_meeting_status(task.meeting_id, "failed", str(e))

    finally:
        task.tmp_path.unlink(missing_ok=True)
        _import_queue._current = None  # noqa: SLF001
        _import_queue.clear_cancel()


async def worker_loop() -> None:
    """Background worker: serially processes import tasks from the queue."""
    logger.info("Import worker started")
    while True:
        task = await _import_queue.queue.get()
        try:
            await _process_task(task)
        except Exception:
            logger.exception("Unexpected error processing import task %s", task.meeting_id)
        finally:
            _import_queue.queue.task_done()


def get_import_status() -> dict[str, Any]:
    q = get_import_queue()
    return {
        "processing": q.current,
        "queued": q.queued_ids(),
        "failed": q.failed_ids(),
    }
