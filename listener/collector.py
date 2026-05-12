"""Message collector: filters and stores QQ group messages by project."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.config import ConfigManager
    from core.storage import MessageStore

    from astrbot.core.platform import AstrMessageEvent

logger = logging.getLogger(__name__)


class MessageCollector:
    """Filters group messages by project and persists them."""

    def __init__(self, config: ConfigManager, store: MessageStore) -> None:
        self._config = config
        self._store = store

    async def on_group_message(self, event: AstrMessageEvent) -> None:
        group_id = event.get_group_id()
        if not group_id:
            return

        sender_id = event.get_sender_id()
        text = event.message_str.strip()
        if not text:
            return

        projects = self._config.find_project_by_group(group_id)
        if not projects:
            return

        for proj in projects:
            if sender_id in proj.filtered_members:
                continue
            sender_name = (
                event.message_obj.sender.nickname
                if event.message_obj and event.message_obj.sender
                else None
            )
            await self._store.insert_message(
                project_id=proj.id,
                group_id=group_id,
                sender_id=sender_id,
                sender_name=sender_name,
                content=text,
                timestamp=event.message_obj.timestamp if event.message_obj else None,
            )
