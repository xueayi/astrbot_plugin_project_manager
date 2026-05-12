"""LLM Step 1: Extract structured information from group chat messages."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from .prompts import SUMMARY_SYSTEM, SUMMARY_USER

if TYPE_CHECKING:
    from astrbot.api.star import Context

    from ..core.config import ConfigManager, ProjectConfig

logger = logging.getLogger(__name__)


class Summarizer:
    """Calls LLM to turn raw chat messages into structured project data."""

    def __init__(self, context: Context, config: ConfigManager) -> None:
        self._ctx = context
        self._cfg = config

    async def summarize(
        self,
        project: ProjectConfig,
        messages: list[dict],
    ) -> dict | None:
        """Run LLM summarization on a batch of messages.

        Returns parsed JSON dict or None on failure.
        """
        if not messages:
            return None

        formatted = self._format_messages(messages)
        prompt = SUMMARY_USER.format(
            project_name=project.name,
            messages=formatted,
        )

        provider_id = self._cfg.global_config.llm_provider_id
        if not provider_id:
            providers = self._ctx.provider_manager.provider_insts
            if providers:
                provider_id = providers[0].meta().id
            else:
                logger.error("No LLM provider available for summarization")
                return None

        try:
            resp = await self._ctx.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
                system_prompt=SUMMARY_SYSTEM,
            )
            return self._parse_json_response(resp.completion_text)
        except Exception:
            logger.exception("LLM summarization failed for project %s", project.name)
            return None

    @staticmethod
    def _format_messages(messages: list[dict]) -> str:
        lines: list[str] = []
        for msg in messages:
            name = msg.get("sender_name") or msg.get("sender_id", "unknown")
            lines.append(f"[{name}] {msg['content']}")
        return "\n".join(lines)

    @staticmethod
    def _parse_json_response(text: str) -> dict | None:
        if not text:
            return None
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM JSON output: %s", cleaned[:300])
            return None
