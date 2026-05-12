"""Multi-project configuration management.

Stores project configs as JSON in the plugin data directory.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ScheduleConfig:
    summary_cron: str = "0 18 * * *"
    report_cron: str = "0 9 * * *"
    urge_threshold_days: int = 3


@dataclass
class ProjectConfig:
    id: str = ""
    name: str = ""
    lark_handbook_url: str = ""
    lark_bulletin_url: str = ""
    qq_groups: list[str] = field(default_factory=list)
    admins: list[str] = field(default_factory=list)
    filtered_members: list[str] = field(default_factory=list)
    member_mapping: dict[str, str] = field(default_factory=dict)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    enabled: bool = True


@dataclass
class GlobalConfig:
    llm_provider_id: str = ""
    lark_cli_path: str = "lark-cli"
    message_retention_days: int = 7


@dataclass
class PluginConfig:
    global_config: GlobalConfig = field(default_factory=GlobalConfig)
    projects: dict[str, ProjectConfig] = field(default_factory=dict)


class ConfigManager:
    """Manages multi-project configuration persisted as JSON."""

    def __init__(self, data_dir: Path) -> None:
        self._path = data_dir / "config.json"
        self._config = PluginConfig()

    @property
    def config(self) -> PluginConfig:
        return self._config

    @property
    def global_config(self) -> GlobalConfig:
        return self._config.global_config

    def get_project(self, project_id: str) -> ProjectConfig | None:
        return self._config.projects.get(project_id)

    def get_all_projects(self) -> dict[str, ProjectConfig]:
        return self._config.projects

    def get_enabled_projects(self) -> dict[str, ProjectConfig]:
        return {pid: p for pid, p in self._config.projects.items() if p.enabled}

    def find_project_by_group(self, group_id: str) -> list[ProjectConfig]:
        """Return all projects that monitor the given QQ group."""
        return [
            p
            for p in self._config.projects.values()
            if p.enabled and group_id in p.qq_groups
        ]

    # ---- persistence ----

    def load(self) -> None:
        if not self._path.exists():
            logger.info("No config file found, using defaults.")
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._config = self._deserialize(raw)
        except Exception:
            logger.exception("Failed to load config, using defaults.")

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._serialize(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ---- CRUD helpers for Web API ----

    def upsert_project(self, data: dict[str, Any]) -> ProjectConfig:
        pid = data.get("id") or str(uuid.uuid4())[:8]
        existing = self._config.projects.get(pid)
        proj = existing or ProjectConfig(id=pid)

        proj.name = data.get("name", proj.name)
        proj.lark_handbook_url = data.get("lark_handbook_url", proj.lark_handbook_url)
        proj.lark_bulletin_url = data.get("lark_bulletin_url", proj.lark_bulletin_url)
        proj.qq_groups = data.get("qq_groups", proj.qq_groups)
        proj.admins = data.get("admins", proj.admins)
        proj.filtered_members = data.get("filtered_members", proj.filtered_members)
        proj.member_mapping = data.get("member_mapping", proj.member_mapping)
        proj.enabled = data.get("enabled", proj.enabled)

        sched = data.get("schedule", {})
        if sched:
            proj.schedule.summary_cron = sched.get(
                "summary_cron", proj.schedule.summary_cron
            )
            proj.schedule.report_cron = sched.get(
                "report_cron", proj.schedule.report_cron
            )
            proj.schedule.urge_threshold_days = sched.get(
                "urge_threshold_days", proj.schedule.urge_threshold_days
            )

        self._config.projects[pid] = proj
        self.save()
        return proj

    def delete_project(self, project_id: str) -> bool:
        if project_id in self._config.projects:
            del self._config.projects[project_id]
            self.save()
            return True
        return False

    def update_global(self, data: dict[str, Any]) -> None:
        g = self._config.global_config
        g.llm_provider_id = data.get("llm_provider_id", g.llm_provider_id)
        g.lark_cli_path = data.get("lark_cli_path", g.lark_cli_path)
        g.message_retention_days = data.get(
            "message_retention_days", g.message_retention_days
        )
        self.save()

    # ---- (de)serialization ----

    def _serialize(self) -> dict:
        cfg = self._config
        return {
            "global": {
                "llm_provider_id": cfg.global_config.llm_provider_id,
                "lark_cli_path": cfg.global_config.lark_cli_path,
                "message_retention_days": cfg.global_config.message_retention_days,
            },
            "projects": {
                pid: {
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
                for pid, p in cfg.projects.items()
            },
        }

    @staticmethod
    def _deserialize(raw: dict) -> PluginConfig:
        g = raw.get("global", {})
        global_cfg = GlobalConfig(
            llm_provider_id=g.get("llm_provider_id", ""),
            lark_cli_path=g.get("lark_cli_path", "lark-cli"),
            message_retention_days=g.get("message_retention_days", 7),
        )
        projects: dict[str, ProjectConfig] = {}
        for pid, pdata in raw.get("projects", {}).items():
            sched = pdata.get("schedule", {})
            projects[pid] = ProjectConfig(
                id=pid,
                name=pdata.get("name", ""),
                lark_handbook_url=pdata.get("lark_handbook_url", ""),
                lark_bulletin_url=pdata.get("lark_bulletin_url", ""),
                qq_groups=pdata.get("qq_groups", []),
                admins=pdata.get("admins", []),
                filtered_members=pdata.get("filtered_members", []),
                member_mapping=pdata.get("member_mapping", {}),
                schedule=ScheduleConfig(
                    summary_cron=sched.get("summary_cron", "0 18 * * *"),
                    report_cron=sched.get("report_cron", "0 9 * * *"),
                    urge_threshold_days=sched.get("urge_threshold_days", 3),
                ),
                enabled=pdata.get("enabled", True),
            )
        return PluginConfig(global_config=global_cfg, projects=projects)
