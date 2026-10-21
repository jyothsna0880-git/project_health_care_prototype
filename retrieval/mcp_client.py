"""MCP client: launches the tools server over stdio and calls its tools.
Knows nothing about the LLM."""

import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp import Client, MCPError, StdioServerParameters

from core.config import PROJECT_ROOT, get_settings

SERVER_PARAMS = StdioServerParameters(
    command=sys.executable,
    args=["-m", "tools.server"],
    cwd=PROJECT_ROOT,
)


class ToolError(RuntimeError):
    """An MCP tool call failed (bad arguments or upstream API error)."""


class Toolbox:
    def __init__(self, client: Client):
        self._client = client

    async def call_text(self, name: str, arguments: dict) -> str:
        try:
            result = await self._client.call_tool(name, arguments)
        except (MCPError, TimeoutError) as exc:  # request timeout, server crash, closed connection
            raise ToolError(f"{name} failed: {exc or type(exc).__name__}") from exc
        text = "\n".join(block.text for block in result.content if block.type == "text")
        if result.is_error:
            raise ToolError(f"{name} failed: {text}")
        return text

    async def call_json(self, name: str, arguments: dict) -> dict:
        return json.loads(await self.call_text(name, arguments))


@asynccontextmanager
async def connect() -> AsyncIterator[Toolbox]:
    async with Client(SERVER_PARAMS, read_timeout_seconds=get_settings().mcp_timeout) as client:
        yield Toolbox(client)
