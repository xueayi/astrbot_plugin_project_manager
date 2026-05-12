"""Reporter: sends project status reports to QQ groups and checks deadlines."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import astrbot.api.message_components as Comp
from astrbot.api.event import MessageChain

if TYPE_CHECKING:
    from astrbot.api.star import Context

    from ..core.config import ConfigManager, ProjectConfig
    from ..core.lark_bridge import LarkBridge
    from ..core.storage import MessageStore
    from ..llm.report_generator import ReportGenerator

logger = logging.getLogger(__name__)


class Reporter:
    """Generates and sends reports to QQ groups, plus deadline urge checks."""

    def __init__(
        self,
        context: Context,
        config: ConfigManager,
        store: MessageStore,
        lark: LarkBridge,
        report_gen: ReportGenerator,
    ) -> None:
        self._ctx = context
        self._cfg = config
        self._store = store
        self._lark = lark
        self._report_gen = report_gen

    async def generate_brief_status(self, project: ProjectConfig) -> str:
        """Generate a brief status string (for `pm status` command)."""
        msg_count = await self._store.get_message_count(
            project.id, since=int(time.time()) - 86400
        )
        summaries = await self._store.get_recent_summaries(project.id, limit=1)
        last_summary = (
            "无" if not summaries else _fmt_timestamp(summaries[0]["created_at"])
        )

        lines = [
            f"📋 {project.name}",
            f"  最近24h消息: {msg_count} 条",
            f"  最后摘要时间: {last_summary}",
        ]
        if project.lark_handbook_url:
            lines.append(f"  管理手册: {project.lark_handbook_url}")
        if project.lark_bulletin_url:
            lines.append(f"  公告板: {project.lark_bulletin_url}")
        return "\n".join(lines)

    async def send_full_report(self, project: ProjectConfig) -> None:
        """Fetch docs, generate LLM report, and send to all bound QQ groups."""
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
            report_text = (
                f"📋 {project.name} - 项目状态报告\n\n"
                "⚠️ 无法读取飞书文档，请检查 lark-cli 配置。"
            )
        else:
            report_text = await self._report_gen.generate_report(
                project, handbook_content, bulletin_content
            )
            if not report_text:
                report_text = (
                    f"📋 {project.name} - 项目状态报告\n\n⚠️ 报告生成失败，请稍后重试。"
                )

        await self._broadcast_to_groups(project, report_text)
        await self._store.log_operation(
            project_id=project.id,
            operation="report",
            detail=f"Report sent to {len(project.qq_groups)} group(s)",
        )

    async def send_progress_notification(
        self, project: ProjectConfig, summary_text: str
    ) -> None:
        """Send a brief progress notification after a summary with notable progress."""
        text = f"📢 {project.name} - 进度更新\n\n{summary_text}"
        if project.lark_bulletin_url:
            text += f"\n\n🔗 公告板: {project.lark_bulletin_url}"
        await self._broadcast_to_groups(project, text)

    async def check_and_urge(self, project: ProjectConfig) -> None:
        """Check for approaching deadlines and send urge messages."""
        combined_content = ""
        if project.lark_handbook_url:
            combined_content += (
                await self._lark.fetch_doc(project.lark_handbook_url) or ""
            )
        if project.lark_bulletin_url:
            combined_content += "\n\n" + (
                await self._lark.fetch_doc(project.lark_bulletin_url) or ""
            )

        if not combined_content.strip():
            return

        tasks = await self._report_gen.generate_urge_tasks(project, combined_content)
        if not tasks:
            return

        lines = [f"⏰ {project.name} - 任务提醒\n"]
        at_targets: list[str] = []

        for task in tasks:
            status_icon = {"approaching": "🟡", "overdue": "🔴", "unclear": "⚪"}.get(
                task.get("status", ""), "⚪"
            )
            assignee = task.get("assignee_name", "未分配")
            line = f"{status_icon} {task.get('task', '未知任务')} - {assignee}"
            if task.get("due_date"):
                line += f" (截止: {task['due_date']})"
            lines.append(line)

            qq_id = task.get("assignee_qq")
            if qq_id and qq_id not in at_targets:
                at_targets.append(qq_id)

        message_text = "\n".join(lines)

        for group_umo in self._get_group_umos(project):
            chain = MessageChain()
            for qq_id in at_targets:
                chain.chain.append(Comp.At(qq=qq_id))
            chain.message(message_text)
            try:
                await self._ctx.send_message(group_umo, chain)
            except Exception:
                logger.exception("Failed to send urge to %s", group_umo)

        await self._store.log_operation(
            project_id=project.id,
            operation="urge",
            detail=f"Found {len(tasks)} urgent task(s), notified {len(at_targets)} member(s)",
        )

    # ---- helpers ----

    async def _broadcast_to_groups(self, project: ProjectConfig, text: str) -> None:
        chain = MessageChain().message(text)
        for umo in self._get_group_umos(project):
            try:
                await self._ctx.send_message(umo, chain)
            except Exception:
                logger.exception("Failed to send message to %s", umo)

    def _get_group_umos(self, project: ProjectConfig) -> list[str]:
        """Build UMO strings for all bound QQ groups.

        UMO format for aiocqhttp groups: aiocqhttp:<adapter_id>:GroupMessage:<group_id>
        We try to find a matching platform adapter to build the correct UMO.
        """
        umos: list[str] = []
        for platform in self._ctx.platform_manager.platform_insts:
            meta = platform.meta()
            if meta.name != "aiocqhttp":
                continue
            for gid in project.qq_groups:
                umos.append(f"aiocqhttp:{meta.id}:GroupMessage:{gid}")
            break
        return umos


def _fmt_timestamp(ts: int) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
