"""
Pagar.me MCP Server v2.0.0
===========================
MCP server para financeiro Pagar.me v5 + Shopify.
Recebiveis, conciliacao, fluxo de caixa, antecipacoes, pedidos, sync.

Author: Fabiano Omura
"""

import asyncio
import logging
import sys

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from tools import ALL_TOOLS, dispatch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("pagarme-mcp")

server = Server("pagarme-mcp")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return ALL_TOOLS


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    try:
        result = await dispatch(name, arguments)
        return [types.TextContent(type="text", text=result)]
    except Exception as e:
        logger.exception(f"Erro na tool {name}")
        return [types.TextContent(type="text", text=f"Erro: {e}")]


async def main():
    logger.info("Iniciando Pagar.me MCP Server v2.0.0")
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
