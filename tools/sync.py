"""Tools de sincronização de dados (Pagar.me payables + Shopify orders)."""

import asyncio
from datetime import datetime, timedelta

import mcp.types as types

from banco import (
    criar_tabelas, upsert_payables, upsert_shopify_orders,
    upsert_shopify_refunds, registrar_sync,
)
import pagarme_api
import shopify_api

TOOLS = [
    types.Tool(
        name="sincronizar_payables",
        description="Sincroniza payables da Pagar.me para o banco local. "
                    "Puxa todos os payables de um periodo e salva no SQLite.",
        inputSchema={
            "type": "object",
            "properties": {
                "dias": {
                    "type": "integer",
                    "description": "Quantidade de dias para sincronizar (padrao: 30)",
                    "default": 30,
                },
            },
        },
    ),
    types.Tool(
        name="sincronizar_shopify",
        description="Sincroniza pedidos Shopify para o banco local. "
                    "Pode sincronizar por periodo ou atualizar pedidos modificados recentemente. "
                    "Inclui transactions, reembolsos e status financeiro.",
        inputSchema={
            "type": "object",
            "properties": {
                "inicio": {"type": "string", "description": "Data inicio (YYYY-MM-DD). Se omitido, usa ultimos 7 dias atualizados."},
                "fim": {"type": "string", "description": "Data fim (YYYY-MM-DD). Obrigatorio se inicio fornecido."},
            },
        },
    ),
    types.Tool(
        name="sincronizar_tudo",
        description="Sincroniza payables Pagar.me (30 dias) e pedidos Shopify (atualizados 7 dias) "
                    "de uma vez. Equivalente a rodar ambas sincronizacoes.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


async def _sync_payables(dias: int) -> str:
    hoje = datetime.now().strftime("%Y-%m-%d")
    inicio = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")

    criar_tabelas()

    try:
        payables_raw = await pagarme_api.buscar_payables(inicio, hoje)
        if payables_raw:
            normalizados = [pagarme_api.normalizar_payable(p) for p in payables_raw]
            upsert_payables(normalizados)

        registrar_sync("payables", inicio, hoje, len(payables_raw), "sucesso")
        return f"Payables sincronizados: {len(payables_raw)} registros ({inicio} a {hoje})"
    except Exception as e:
        registrar_sync("payables", inicio, hoje, 0, "erro", str(e))
        raise


async def _sync_shopify_periodo(inicio: str, fim: str) -> str:
    criar_tabelas()

    orders = await shopify_api.buscar_pedidos({
        "created_at_min": f"{inicio}T00:00:00-03:00",
        "created_at_max": f"{fim}T23:59:59-03:00",
        "status": "any",
    })

    pedidos_norm, refunds_todos = await _processar_pedidos(orders)

    registrar_sync("shopify_orders", inicio, fim, len(pedidos_norm), "sucesso")

    lines = [f"Shopify sincronizado: {len(pedidos_norm)} pedidos ({inicio} a {fim})"]
    if refunds_todos:
        lines.append(f"Reembolsos: {len(refunds_todos)}")

    # Resumo de status
    status_count: dict[str, int] = {}
    for p in pedidos_norm:
        st = p["financial_status"]
        status_count[st] = status_count.get(st, 0) + 1
    if status_count:
        lines.append("Status: " + ", ".join(f"{k}: {v}" for k, v in sorted(status_count.items(), key=lambda x: -x[1])))

    return "\n".join(lines)


async def _sync_shopify_atualizacoes(dias: int = 7) -> str:
    criar_tabelas()
    desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")

    orders = await shopify_api.buscar_pedidos({
        "updated_at_min": f"{desde}T00:00:00-03:00",
        "status": "any",
    })

    pedidos_norm, refunds_todos = await _processar_pedidos(orders)

    registrar_sync("shopify_orders", "atualizar", f"{dias}d", len(pedidos_norm), "sucesso")

    lines = [f"Shopify atualizado: {len(pedidos_norm)} pedidos (modificados ultimos {dias} dias)"]
    if refunds_todos:
        lines.append(f"Reembolsos: {len(refunds_todos)}")

    refund_count = sum(1 for p in pedidos_norm if p["refund_total"] > 0)
    if refund_count:
        from tools._fmt import fmt
        total_r = sum(p["refund_total"] for p in pedidos_norm if p["refund_total"] > 0)
        lines.append(f"Pedidos com reembolso: {refund_count} (total: {fmt(total_r)})")

    return "\n".join(lines)


async def _processar_pedidos(orders: list[dict]) -> tuple[list[dict], list[dict]]:
    """Processa lista de pedidos: busca transactions, normaliza, salva."""
    pedidos_norm = []
    refunds_todos = []

    for order in orders:
        txns = await shopify_api.buscar_transactions(order["id"])
        payment_id = shopify_api.extrair_payment_id(txns)
        pedidos_norm.append(shopify_api.normalizar_pedido(order, payment_id))

        refunds = shopify_api.extrair_refunds(order)
        if refunds:
            refunds_todos.extend(refunds)

    if pedidos_norm:
        upsert_shopify_orders(pedidos_norm)
    if refunds_todos:
        upsert_shopify_refunds(refunds_todos)

    return pedidos_norm, refunds_todos


async def dispatch(name: str, args: dict) -> str:
    if name == "sincronizar_payables":
        dias = args.get("dias", 30)
        return await _sync_payables(dias)
    elif name == "sincronizar_shopify":
        inicio = args.get("inicio")
        fim = args.get("fim")
        if inicio and fim:
            return await _sync_shopify_periodo(inicio, fim)
        return await _sync_shopify_atualizacoes()
    elif name == "sincronizar_tudo":
        r1 = await _sync_payables(30)
        r2 = await _sync_shopify_atualizacoes()
        return f"{r1}\n\n{r2}"
    return f"Tool '{name}' nao encontrada neste modulo."
