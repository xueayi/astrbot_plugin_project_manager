"""AstrBot plugin: Feishu + QQ bidirectional project management.

Implements four core capabilities:
- Listen: collect QQ group messages, periodically summarize via LLM
- Record: push structured updates to Feishu docs
- Report: send project status reports to QQ groups
- Urge: remind assignees about approaching deadlines
"""

from __future__ import annotations

import logging
from pathlib import Path

from astrbot.api import star
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .core.config import ConfigManager
from .core.lark_bridge import LarkBridge
from .core.storage import MessageStore
from .listener.collector import MessageCollector
from .llm.doc_updater import DocUpdater
from .llm.report_generator import ReportGenerator
from .llm.summarizer import Summarizer
from .recorder.recorder import Recorder
from .reporter.reporter import Reporter

logger = logging.getLogger(__name__)

PLUGIN_NAME = "astrbot_plugin_project_manager"


class Main(star.Star):
    def __init__(self, context: star.Context) -> None:
        super().__init__(context)

        data_dir = Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME
        data_dir.mkdir(parents=True, exist_ok=True)

        self.cfg = ConfigManager(data_dir)
        self.cfg.load()

        self.store = MessageStore(data_dir)
        self.lark = LarkBridge(self.cfg.global_config.lark_cli_path)

        self.collector = MessageCollector(self.cfg, self.store)
        self.summarizer = Summarizer(context, self.cfg)
        self.doc_updater = DocUpdater(context, self.cfg, self.lark)
        self.report_gen = ReportGenerator(context, self.cfg, self.lark)
        self.recorder = Recorder(
            context,
            self.cfg,
            self.store,
            self.lark,
            self.summarizer,
            self.doc_updater,
        )
        self.reporter = Reporter(
            context,
            self.cfg,
            self.store,
            self.lark,
            self.report_gen,
        )

        self._lark_available = False
        self._cron_job_ids: list[str] = []

        self._register_web_apis()

    # ---- lifecycle ----

    @filter.on_astrbot_loaded()
    async def on_loaded(self, *args, **kwargs) -> None:
        await self.store.init()
        self._lark_available = await self.lark.check_available()
        if not self._lark_available:
            logger.warning(
                "lark-cli is not available. Feishu features are disabled; "
                "message collection will still work."
            )
        await self._register_cron_jobs()

    async def terminate(self) -> None:
        for job_id in self._cron_job_ids:
            try:
                await self.context.cron_manager.delete_job(job_id)
            except Exception:
                pass
        await self.store.close()

    # ---- message collection (听 - 收集) ----

    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    @filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP)
    async def on_group_msg(self, event: AstrMessageEvent) -> None:
        await self.collector.on_group_message(event)

    # ---- command group: pm ----

    @filter.command_group("pm")
    def pm_group(self):
        pass

    @pm_group.command("status")
    async def cmd_status(self, event: AstrMessageEvent) -> None:
        """View current project status summary."""
        group_id = event.get_group_id()
        projects = self.cfg.find_project_by_group(group_id) if group_id else []
        if not projects:
            yield event.plain_result("当前群未绑定任何项目。")
            return
        for proj in projects:
            report = await self.reporter.generate_brief_status(proj)
            yield event.plain_result(report)

    @pm_group.command("report")
    async def cmd_report(self, event: AstrMessageEvent) -> None:
        """Manually trigger a full project report (admin only)."""
        group_id = event.get_group_id()
        projects = self.cfg.find_project_by_group(group_id) if group_id else []
        if not projects:
            yield event.plain_result("当前群未绑定任何项目。")
            return
        if not self._is_admin(event, projects):
            yield event.plain_result("仅项目管理员可执行此操作。")
            return
        for proj in projects:
            await self.reporter.send_full_report(proj)
        yield event.plain_result("报告已发送。")

    @pm_group.command("sync")
    async def cmd_sync(self, event: AstrMessageEvent) -> None:
        """Manually trigger message summary + Feishu doc update (admin only)."""
        group_id = event.get_group_id()
        projects = self.cfg.find_project_by_group(group_id) if group_id else []
        if not projects:
            yield event.plain_result("当前群未绑定任何项目。")
            return
        if not self._is_admin(event, projects):
            yield event.plain_result("仅项目管理员可执行此操作。")
            return
        yield event.plain_result("开始同步，请稍候...")
        for proj in projects:
            result = await self.recorder.run_pipeline(proj)
            yield event.plain_result(f"[{proj.name}] 同步完成：{result}")

    @pm_group.command("update")
    async def cmd_update(self, event: AstrMessageEvent, content: str = "") -> None:
        """Directly append content to the Feishu bulletin (admin only)."""
        group_id = event.get_group_id()
        projects = self.cfg.find_project_by_group(group_id) if group_id else []
        if not projects:
            yield event.plain_result("当前群未绑定任何项目。")
            return
        if not self._is_admin(event, projects):
            yield event.plain_result("仅项目管理员可执行此操作。")
            return
        if not content.strip():
            yield event.plain_result("请提供要更新的内容。用法: pm update <内容>")
            return
        if not self._lark_available:
            yield event.plain_result("lark-cli 不可用，无法更新飞书文档。")
            return
        for proj in projects:
            ok = await self.lark.update_doc(
                proj.lark_bulletin_url,
                command="append",
                content=content.strip(),
            )
            status = "成功" if ok else "失败"
            yield event.plain_result(f"[{proj.name}] 公告板更新{status}。")

    @pm_group.command("urge")
    async def cmd_urge(self, event: AstrMessageEvent) -> None:
        """Manually trigger deadline urge check (admin only)."""
        group_id = event.get_group_id()
        projects = self.cfg.find_project_by_group(group_id) if group_id else []
        if not projects:
            yield event.plain_result("当前群未绑定任何项目。")
            return
        if not self._is_admin(event, projects):
            yield event.plain_result("仅项目管理员可执行此操作。")
            return
        for proj in projects:
            await self.reporter.check_and_urge(proj)
        yield event.plain_result("催促检查完成。")

    # ---- cron jobs ----

    async def _register_cron_jobs(self) -> None:
        for proj in self.cfg.get_enabled_projects().values():
            await self._register_project_crons(proj)
        await self._register_cleanup_cron()

    async def _register_project_crons(self, proj) -> None:
        try:
            summary_job = await self.context.cron_manager.add_basic_job(
                name=f"pm_summary_{proj.id}",
                cron_expression=proj.schedule.summary_cron,
                handler=self._make_summary_handler(proj.id),
                description=f"Project {proj.name}: message summary",
            )
            self._cron_job_ids.append(summary_job.id)

            report_job = await self.context.cron_manager.add_basic_job(
                name=f"pm_report_{proj.id}",
                cron_expression=proj.schedule.report_cron,
                handler=self._make_report_handler(proj.id),
                description=f"Project {proj.name}: morning report",
            )
            self._cron_job_ids.append(report_job.id)
        except Exception:
            logger.exception("Failed to register cron jobs for project %s", proj.id)

    async def _register_cleanup_cron(self) -> None:
        """Register a daily job to clean up old processed messages."""
        try:
            job = await self.context.cron_manager.add_basic_job(
                name="pm_message_cleanup",
                cron_expression="0 3 * * *",
                handler=self._cleanup_handler,
                description="Project Manager: message cleanup",
            )
            self._cron_job_ids.append(job.id)
        except Exception:
            logger.exception("Failed to register cleanup cron job")

    async def _cleanup_handler(self, **kwargs) -> None:
        retention = self.cfg.global_config.message_retention_days
        deleted = await self.store.cleanup_old_messages(retention)
        if deleted:
            logger.info(
                "Cleaned up %d old messages (retention: %d days)", deleted, retention
            )

    def _make_summary_handler(self, project_id: str):
        async def _handler(**kwargs):
            proj = self.cfg.get_project(project_id)
            if not proj or not proj.enabled:
                return
            result = await self.recorder.run_pipeline(proj)
            logger.info("[%s] Scheduled summary: %s", proj.name, result)

            # If notable progress was found, also send a notification
            summaries = await self.store.get_recent_summaries(proj.id, limit=1)
            if summaries:
                import json

                try:
                    data = json.loads(summaries[0]["summary_json"])
                    if data.get("has_notable_progress"):
                        report_text = data.get("summary_for_report") or result
                        await self.reporter.send_progress_notification(
                            proj, report_text
                        )
                except (json.JSONDecodeError, KeyError):
                    pass

        return _handler

    def _make_report_handler(self, project_id: str):
        async def _handler(**kwargs):
            proj = self.cfg.get_project(project_id)
            if not proj or not proj.enabled:
                return
            await self.reporter.send_full_report(proj)
            await self.reporter.check_and_urge(proj)
            logger.info("[%s] Scheduled report + urge done", proj.name)

        return _handler

    # ---- helpers ----

    def _is_admin(self, event: AstrMessageEvent, projects: list) -> bool:
        sender = event.get_sender_id()
        return any(sender in p.admins for p in projects)

    # ---- web API registration ----

    def _register_web_apis(self) -> None:
        from .web_api import register_all_apis

        register_all_apis(self.context, self)
