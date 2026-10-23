"""Shared helpers: result envelope, network guard, MCP calls.

Standard library only. Nothing here imports buyer-agent at module level.
Credentials: the lab never reads any. ``run_demo.sh`` starts every run with
an empty environment (``env -i``) plus only the variables the lab needs.
"""

from __future__ import annotations

import json
import socket
import traceback
from typing import Any

NETWORK_ATTEMPTS: list[str] = []


def ok(raw: Any = None, reason: str = "", **extra: Any) -> dict[str, Any]:
    return {"status": "ok", "reason": reason, "raw": raw, **extra}


def not_available(reason: str, **extra: Any) -> dict[str, Any]:
    return {"status": "not_available", "reason": reason, "raw": None, **extra}


def error(exc: BaseException | str, **extra: Any) -> dict[str, Any]:
    if isinstance(exc, BaseException):
        tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
        tail = "".join(tb).splitlines()[-20:]
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}", "raw": None,
                "traceback": tail, **extra}
    return {"status": "error", "reason": str(exc), "raw": None, **extra}


def install_network_guard() -> None:
    """Refuse every outbound socket connection except local Unix sockets."""
    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex

    def _allowed(sock: socket.socket) -> bool:
        return getattr(socket, "AF_UNIX", None) is not None and sock.family == socket.AF_UNIX

    def connect(self, address):  # type: ignore[no-untyped-def]
        if _allowed(self):
            return orig_connect(self, address)
        NETWORK_ATTEMPTS.append(repr(address))
        raise OSError("demo-lab: network access is disabled")

    def connect_ex(self, address):  # type: ignore[no-untyped-def]
        if _allowed(self):
            return orig_connect_ex(self, address)
        NETWORK_ATTEMPTS.append(repr(address))
        return 111  # ECONNREFUSED-like

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]


def tool_text(result: Any) -> str:
    """Extract the text payload from FastMCP.call_tool's return value."""
    content = result
    if isinstance(result, tuple):
        content = result[0]
    if isinstance(content, dict) and "result" in content:
        return str(content["result"])
    if isinstance(content, (list, tuple)) and content:
        first = content[0]
        text = getattr(first, "text", None)
        if text is not None:
            return text
        return str(first)
    return str(content)


def parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return {"_unparsed_text": text}


async def list_tool_names(mcp: Any) -> set[str]:
    tools = await mcp.list_tools()
    return {getattr(t, "name", str(t)) for t in tools}


async def call_tool(mcp: Any, names: set[str], name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Call an MCP tool in-process; envelope the result."""
    if name not in names:
        return not_available(f"MCP tool '{name}' does not exist in this version")
    try:
        res = await mcp.call_tool(name, args)
    except Exception as exc:  # noqa: BLE001 - every failure is recorded, never raised
        return error(exc)
    return ok(parse_json(tool_text(res)))
