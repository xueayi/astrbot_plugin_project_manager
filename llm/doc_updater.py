"""LLM Step 2: Generate Feishu document update instructions from structured data."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from .prompts import DOC_UPDATE_SYSTEM, DOC_UPDATE_USER

if TYPE_CHECKING:
    from core.config import ConfigManager, ProjectConfig
    from core.lark_bridge import LarkBridge

    from astrbot.api.star import Context

logger = logging.getLogger(__name__)


class DocUpdater:
    """Uses LLM to decide how to update Feishu docs based on extracted info."""

    def __init__(
        self, context: Context, config: ConfigManager, lark: LarkBridge
    ) -> None:
        self._ctx = context
        self._cfg = config
        self._lark = lark

    async def generate_updates(
        self,
        project: ProjectConfig,
        summary: dict,
        handbook_content: str,
        bulletin_content: str,
    ) -> dict | None:
        """Ask LLM what document updates to make.

        Returns dict with "updates" list and "summary_for_report" string,
        or None on failure.
        """
        combined_content = (
            f"=== Handbook ===\n{handbook_content}\n\n"
            f"=== Bulletin ===\n{bulletin_content}"
        )
        today = datetime.now().strftime("%Y-%m-%d")
        prompt = DOC_UPDATE_USER.format(
            project_name=project.name,
            current_date=today,
            summary_json=json.dumps(summary, ensure_ascii=False, indent=2),
            doc_type="handbook + bulletin",
            doc_content=combined_content,
        )

        provider_id = await self._resolve_provider()
        if not provider_id:
            return None

        try:
            resp = await self._ctx.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=DOC_UPDATE_SYSTEM,
            )
            return self._parse_json_response(resp.completion_text)
        except Exception:
            logger.exception(
                "LLM doc update generation failed for project %s", project.name
            )
            return None

    async def apply_updates(
        self, project: ProjectConfig, updates: list[dict]
    ) -> list[str]:
        """Execute the LLM-generated update instructions via lark-cli.

        Returns list of result descriptions.
        """
        results: list[str] = []
        for upd in updates:
            target = upd.get("target", "bulletin")
            doc_url = (
                project.lark_handbook_url
                if target == "handbook"
                else project.lark_bulletin_url
            )
            if not doc_url:
                results.append(f"Skipped {target}: no URL configured")
                continue

            command = upd.get("command", "append")
            content = upd.get("content", "")
            if not content:
                continue

            ok = await self._lark.update_doc(doc_url, command=command, content=content)
            status = "ok" if ok else "failed"
            results.append(f"{target}/{command}: {status}")

        return results

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
            logger.error("Failed to parse doc update JSON: %s", cleaned[:300])
            return None
