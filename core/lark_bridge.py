"""Abstraction layer over lark-cli subprocess calls.

All Feishu document operations go through this module so the backend
can be swapped to native HTTP API later without touching callers.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 60


class LarkBridge:
    """Wraps lark-cli commands executed via asyncio subprocess."""

    def __init__(self, cli_path: str = "lark-cli") -> None:
        self._cli = cli_path

    # ---- availability check ----

    async def check_available(self) -> bool:
        if shutil.which(self._cli) is None:
            logger.warning("lark-cli not found in PATH: %s", self._cli)
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                self._cli,
                "auth",
                "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            return proc.returncode == 0
        except Exception:
            logger.exception("lark-cli availability check failed")
            return False

    # ---- document operations ----

    async def fetch_doc(
        self,
        doc_url: str,
        *,
        scope: str = "full",
        detail: str = "simple",
        doc_format: str = "markdown",
    ) -> str | None:
        """Read a Feishu document. Returns content string or None on failure."""
        args = [
            self._cli,
            "docs",
            "+fetch",
            "--api-version",
            "v2",
            "--doc",
            doc_url,
            "--scope",
            scope,
            "--detail",
            detail,
            "--doc-format",
            doc_format,
        ]
        return await self._run_text(args)

    async def update_doc(
        self,
        doc_url: str,
        *,
        command: str,
        content: str,
        doc_format: str = "markdown",
    ) -> bool:
        """Update a Feishu document. Returns True on success."""
        args = [
            self._cli,
            "docs",
            "+update",
            "--api-version",
            "v2",
            "--doc",
            doc_url,
            "--command",
            command,
            "--content",
            content,
            "--doc-format",
            doc_format,
        ]
        return await self._run_ok(args)

    async def create_doc(
        self,
        content: str,
        *,
        title: str | None = None,
        folder_token: str | None = None,
        doc_format: str = "markdown",
    ) -> str | None:
        """Create a new Feishu document. Returns doc URL/token or None."""
        args = [
            self._cli,
            "docs",
            "+create",
            "--api-version",
            "v2",
            "--content",
            content,
            "--doc-format",
            doc_format,
        ]
        if title:
            args.extend(["--title", title])
        if folder_token:
            args.extend(["--folder-token", folder_token])
        return await self._run_text(args)

    # ---- internal helpers ----

    async def _run_text(
        self, args: list[str], timeout: int = _DEFAULT_TIMEOUT
    ) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            if proc.returncode != 0:
                logger.error(
                    "lark-cli failed (rc=%d): %s\nstderr: %s",
                    proc.returncode,
                    " ".join(args[:6]),
                    stderr.decode(errors="replace")[:500],
                )
                return None
            return stdout.decode(errors="replace")
        except asyncio.TimeoutError:
            logger.error("lark-cli timed out: %s", " ".join(args[:6]))
            return None
        except Exception:
            logger.exception("lark-cli execution error")
            return None

    async def _run_ok(self, args: list[str], timeout: int = _DEFAULT_TIMEOUT) -> bool:
        result = await self._run_text(args, timeout=timeout)
        return result is not None

    async def _run_json(
        self, args: list[str], timeout: int = _DEFAULT_TIMEOUT
    ) -> dict | None:
        text = await self._run_text(args, timeout=timeout)
        if text is None:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.error("Failed to parse lark-cli JSON output")
            return None
