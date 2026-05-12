"""LLM Step 3: Generate human-readable project reports for QQ groups."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from .prompts import REPORT_SYSTEM, REPORT_USER, URGE_SYSTEM, URGE_USER

if TYPE_CHECKING:
    from astrbot.api.star import Context

    from ..core.config import ConfigManager, ProjectConfig
    from ..core.lark_bridge import LarkBridge

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates project status reports and deadline urge messages via LLM."""

    def __init__(
        self, context: Context, config: ConfigManager, lark: LarkBridge
    ) -> None:
        self._ctx = context
        self._cfg = config
        self._lark = lark

    async def generate_report(
        self,
        project: ProjectConfig,
        handbook_content: str,
        bulletin_content: str,
    ) -> str | None:
        """Generate a full project status report text."""
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = REPORT_USER.format(
            project_name=project.name,
            current_date=today,
            handbook_content=handbook_content[:3000],
            bulletin_content=bulletin_content[:3000],
            handbook_url=project.lark_handbook_url,
            bulletin_url=project.lark_bulletin_url,
        )

        provider_id = await self._resolve_provider()
        if not provider_id:
            return None

        try:
            resp = await self._ctx.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=REPORT_SYSTEM,
            )
            return resp.completion_text
        except Exception:
            logger.exception("Report generation failed for %s", project.name)
            return None

    async def generate_urge_tasks(
        self,
        project: ProjectConfig,
        doc_content: str,
    ) -> list[dict]:
        """Identify tasks approaching deadlines. Returns list of urgent task dicts."""
        today = datetime.now().strftime("%Y-%m-%d")
        mapping_str = "\n".join(
            f"  {name}: {qq}" for name, qq in project.member_mapping.items()
        )
        prompt = URGE_USER.format(
            project_name=project.name,
            current_date=today,
            threshold_days=project.schedule.urge_threshold_days,
            doc_content=doc_content[:4000],
            member_mapping=mapping_str or "(no mapping configured)",
        )

        provider_id = await self._resolve_provider()
        if not provider_id:
            return []

        try:
            resp = await self._ctx.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=URGE_SYSTEM,
            )
            parsed = self._parse_json_response(resp.completion_text)
            if parsed and "urgent_tasks" in parsed:
                return parsed["urgent_tasks"]
            return []
        except Exception:
            logger.exception("Urge task generation failed for %s", project.name)
            return []

    async def _resolve_provider(self) -> str | None:
        provider_id = self._cfg.global_config.llm_provider_id
        if not provider_id:
            providers = self._ctx.provider_manager.provider_insts
            if providers:
                return providers[0].meta().id
            logger.error("No LLM provider available")
            return None
        return provider_id

    @staticmethod
    def _parse_json_response(text: str) -> dict | None:
        if not text:
            return None
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Failed to parse urge JSON: %s", cleaned[:300])
            return None
