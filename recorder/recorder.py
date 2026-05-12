"""Recorder: orchestrates the summarize -> fetch doc -> generate updates -> apply pipeline."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from astrbot.api.star import Context

    from ..core.config import ConfigManager, ProjectConfig
    from ..core.lark_bridge import LarkBridge
    from ..core.storage import MessageStore
    from ..llm.doc_updater import DocUpdater
    from ..llm.summarizer import Summarizer

logger = logging.getLogger(__name__)


class Recorder:
    """Runs the full listen-summarize-record pipeline for a project."""

    def __init__(
        self,
        context: Context,
        config: ConfigManager,
        store: MessageStore,
        lark: LarkBridge,
        summarizer: Summarizer,
        doc_updater: DocUpdater,
    ) -> None:
        self._ctx = context
        self._cfg = config
        self._store = store
        self._lark = lark
        self._summarizer = summarizer
        self._doc_updater = doc_updater

    async def run_pipeline(self, project: ProjectConfig) -> str:
        """Execute the full pipeline for one project.

        Returns a human-readable result string.
        """
        messages = await self._store.get_unprocessed_messages(project.id)
        if not messages:
            await self._store.log_operation(
                project_id=project.id,
                operation="summary",
                detail="No unprocessed messages",
            )
            return "没有新消息需要处理。"

        # Step 1: LLM summarization
        summary = await self._summarizer.summarize(project, messages)
        if summary is None:
            await self._store.log_operation(
                project_id=project.id,
                operation="summary",
                detail="LLM summarization returned None, will retry next cycle",
                success=False,
            )
            return "LLM 摘要失败，消息保留待下次处理。"

        # Persist summary
        msg_ids = [m["id"] for m in messages]
        timestamps = [m["timestamp"] for m in messages if m.get("timestamp")]
        await self._store.insert_summary(
            project_id=project.id,
            summary_json=json.dumps(summary, ensure_ascii=False),
            raw_text=summary.get("summary_for_report"),
            message_count=len(messages),
            time_range_start=min(timestamps) if timestamps else 0,
            time_range_end=max(timestamps) if timestamps else 0,
        )
        await self._store.mark_messages_processed(msg_ids)

        # Check if there's anything worth updating
        has_updates = (
            summary.get("progress_updates")
            or summary.get("new_issues")
            or summary.get("decisions")
            or summary.get("new_requirements")
        )
        if not has_updates:
            await self._store.log_operation(
                project_id=project.id,
                operation="summary",
                detail=f"Processed {len(messages)} messages, no project-relevant content found",
            )
            return f"处理了 {len(messages)} 条消息，未发现项目相关内容。"

        # Step 2: Fetch current doc content + generate updates
        doc_result = await self._update_docs(project, summary)

        await self._store.log_operation(
            project_id=project.id,
            operation="sync",
            detail=f"Messages: {len(messages)}, Doc updates: {doc_result}",
        )
        return f"处理了 {len(messages)} 条消息。文档更新: {doc_result}"

    async def _update_docs(self, project: ProjectConfig, summary: dict) -> str:
        handbook_content = ""
        bulletin_content = ""

        if project.lark_handbook_url:
            handbook_content = (
                await self._lark.fetch_doc(project.lark_handbook_url) or ""
            )
        if project.lark_bulletin_url:
            bulletin_content = (
                await self._lark.fetch_doc(project.lark_bulletin_url) or ""
            )

        if not handbook_content and not bulletin_content:
            return "无法读取飞书文档"

        update_plan = await self._doc_updater.generate_updates(
            project, summary, handbook_content, bulletin_content
        )
        if not update_plan or not update_plan.get("updates"):
            return "LLM 未生成更新指令"

        results = await self._doc_updater.apply_updates(project, update_plan["updates"])
        return "; ".join(results) if results else "无更新"
