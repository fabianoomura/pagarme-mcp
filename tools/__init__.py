"""Tools package — registra todas as tools do MCP server."""

from tools.recebiveis import TOOLS as RECEBIVEIS_TOOLS, dispatch as recebiveis_dispatch
from tools.pedidos import TOOLS as PEDIDOS_TOOLS, dispatch as pedidos_dispatch
from tools.fluxo_caixa import TOOLS as FLUXO_TOOLS, dispatch as fluxo_dispatch
from tools.conciliacao import TOOLS as CONCILIACAO_TOOLS, dispatch as conciliacao_dispatch
from tools.sync import TOOLS as SYNC_TOOLS, dispatch as sync_dispatch

ALL_TOOLS = [
    *RECEBIVEIS_TOOLS,
    *PEDIDOS_TOOLS,
    *FLUXO_TOOLS,
    *CONCILIACAO_TOOLS,
    *SYNC_TOOLS,
]

_DISPATCH_MAP: dict[str, object] = {}
for _tools, _fn in [
    (RECEBIVEIS_TOOLS, recebiveis_dispatch),
    (PEDIDOS_TOOLS, pedidos_dispatch),
    (FLUXO_TOOLS, fluxo_dispatch),
    (CONCILIACAO_TOOLS, conciliacao_dispatch),
    (SYNC_TOOLS, sync_dispatch),
]:
    for _t in _tools:
        _DISPATCH_MAP[_t.name] = _fn


async def dispatch(name: str, arguments: dict) -> str:
    fn = _DISPATCH_MAP.get(name)
    if fn is None:
        return f"Tool '{name}' nao encontrada."
    return await fn(name, arguments)
