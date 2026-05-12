"""Web API routes for the project management plugin.

Registered via context.register_web_api() and served under /api/plug/<plugin_name>/.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from quart import jsonify, request

if TYPE_CHECKING:
    from astrbot.api.star import Context

    from .main import Main

logger = logging.getLogger(__name__)

PLUGIN_NAME = "astrbot_plugin_project_manager"


def register_all_apis(context: Context, plugin: Main) -> None:
    """Register all web API endpoints for the plugin management panel."""

    # ---- projects CRUD ----

    async def get_projects():
        projects = plugin.cfg.get_all_projects()
        return jsonify({"projects": [_project_to_dict(p) for p in projects.values()]})

    async def save_project():
        data = await request.get_json() or {}
        proj = plugin.cfg.upsert_project(data)
        return jsonify({"project": _project_to_dict(proj)})

    async def delete_project():
        data = await request.get_json() or {}
        pid = data.get("id", "")
        ok = plugin.cfg.delete_project(pid)
        return jsonify({"success": ok})

    # ---- global settings ----

    async def get_settings():
        g = plugin.cfg.global_config
        providers = []
        for p in context.provider_manager.provider_insts:
            meta = p.meta()
            providers.append({"id": meta.id, "name": meta.name or meta.id})
        return jsonify(
            {
                "settings": {
                    "llm_provider_id": g.llm_provider_id,
                    "lark_cli_path": g.lark_cli_path,
                    "message_retention_days": g.message_retention_days,
                },
                "available_providers": providers,
                "lark_available": plugin._lark_available,
            }
        )

    async def save_settings():
        data = await request.get_json() or {}
        plugin.cfg.update_global(data)
        plugin.lark._cli = plugin.cfg.global_config.lark_cli_path
        return jsonify({"success": True})

    # ---- status / logs ----

    async def get_status(project_id: str):
        proj = plugin.cfg.get_project(project_id)
        if not proj:
            return jsonify({"error": "Project not found"}), 404
        import time

        msg_count = await plugin.store.get_message_count(
            project_id, since=int(time.time()) - 86400
        )
        summaries = await plugin.store.get_recent_summaries(project_id, limit=1)
        return jsonify(
            {
                "project_id": project_id,
                "name": proj.name,
                "enabled": proj.enabled,
                "messages_24h": msg_count,
                "last_summary": summaries[0] if summaries else None,
                "lark_available": plugin._lark_available,
            }
        )

    async def get_logs(project_id: str):
        logs = await plugin.store.get_recent_logs(project_id, limit=30)
        return jsonify({"logs": logs})

    # ---- available QQ groups ----

    async def get_groups():
        groups: list[dict] = []
        for platform in context.platform_manager.platform_insts:
            meta = platform.meta()
            if meta.name == "aiocqhttp":
                try:
                    group_list = await platform.bot.api.call_action("get_group_list")
                    for g in group_list:
                        groups.append(
                            {
                                "group_id": str(g.get("group_id", "")),
                                "group_name": g.get("group_name", ""),
                            }
                        )
                except Exception:
                    logger.exception("Failed to fetch QQ group list")
        return jsonify({"groups": groups})

    # ---- cron refresh ----

    async def refresh_crons():
        """Re-register cron jobs after project config changes."""
        try:
            for job_id in list(plugin._cron_job_ids):
                try:
                    await context.cron_manager.delete_job(job_id)
                except Exception:
                    pass
            plugin._cron_job_ids.clear()
            await plugin._register_cron_jobs()
            return jsonify({"success": True})
        except Exception as e:
            logger.exception("Failed to refresh cron jobs")
            return jsonify({"success": False, "error": str(e)})

    # ---- register routes ----

    prefix = f"/{PLUGIN_NAME}"
    context.register_web_api(
        f"{prefix}/projects", get_projects, ["GET"], "List projects"
    )
    context.register_web_api(
        f"{prefix}/projects", save_project, ["POST"], "Save project"
    )
    context.register_web_api(
        f"{prefix}/projects/delete", delete_project, ["POST"], "Delete project"
    )
    context.register_web_api(
        f"{prefix}/cron/refresh", refresh_crons, ["POST"], "Refresh cron jobs"
    )
    context.register_web_api(
        f"{prefix}/settings", get_settings, ["GET"], "Get global settings"
    )
    context.register_web_api(
        f"{prefix}/settings", save_settings, ["POST"], "Save global settings"
    )
    context.register_web_api(
        f"{prefix}/status/<project_id>", get_status, ["GET"], "Project status"
    )
    context.register_web_api(
        f"{prefix}/logs/<project_id>", get_logs, ["GET"], "Project logs"
    )
    context.register_web_api(
        f"{prefix}/groups", get_groups, ["GET"], "Available QQ groups"
    )


def _project_to_dict(p) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "lark_handbook_url": p.lark_handbook_url,
        "lark_bulletin_url": p.lark_bulletin_url,
        "qq_groups": p.qq_groups,
        "admins": p.admins,
        "filtered_members": p.filtered_members,
        "member_mapping": p.member_mapping,
        "schedule": {
            "summary_cron": p.schedule.summary_cron,
            "report_cron": p.schedule.report_cron,
            "urge_threshold_days": p.schedule.urge_threshold_days,
        },
        "enabled": p.enabled,
    }
