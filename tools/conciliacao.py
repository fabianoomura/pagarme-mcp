"""Tools de conciliação Shopify x Pagar.me."""

import asyncio

import httpx
import mcp.types as types

from banco import get_connection
from tools._fmt import fmt
import pagarme_api
import shopify_api

TOOLS = [
    types.Tool(
        name="conciliar_dia",
        description="Concilia pedidos Shopify com charges Pagar.me de um dia. "
                    "Mostra pedidos conciliados, juros de parcelamento, taxas, "
                    "liquido e pedidos sem match. Tambem cruza charges sem pedido "
                    "do dia com o banco local.",
        inputSchema={
            "type": "object",
            "properties": {
                "data": {"type": "string", "description": "Data para conciliar (YYYY-MM-DD)"},
            },
            "required": ["data"],
        },
    ),
]


def _buscar_taxas_payables(charge_ids: list[str]) -> tuple[float, float, float]:
    """Busca taxas dos payables no banco local."""
    if not charge_ids:
        return 0, 0, 0
    conn = get_connection()
    placeholders = ",".join("?" * len(charge_ids))
    row = conn.execute(f"""
        SELECT
            COALESCE(SUM(fee), 0) AS taxas,
            COALESCE(SUM(anticipation_fee), 0) AS antecip,
            COALESCE(SUM(amount) - SUM(fee) - SUM(anticipation_fee), 0) AS liquido
        FROM payables WHERE charge_id IN ({placeholders})
    """, charge_ids).fetchone()
    conn.close()
    return row["taxas"] / 100, row["antecip"] / 100, row["liquido"] / 100


async def _conciliar_dia(data: str) -> str:
    # Buscar pedidos Shopify do dia
    pedidos_raw = await shopify_api.buscar_pedidos({
        "created_at_min": f"{data}T00:00:00-03:00",
        "created_at_max": f"{data}T23:59:59-03:00",
        "status": "any",
        "financial_status": "paid",
    })

    # Buscar transactions de cada pedido para pegar payment_id
    pedidos = []
    async with httpx.AsyncClient(timeout=30) as client:
        for o in pedidos_raw:
            txns = await shopify_api.buscar_transactions(o["id"])
            payment_ids = []
            for t in txns:
                pid = (t.get("receipt") or {}).get("payment_id", "")
                if pid and t.get("status") == "success":
                    payment_ids.append(pid)

            customer = o.get("customer", {}) or {}
            cliente = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()

            pedidos.append({
                "order_id": o["id"],
                "name": o.get("name"),
                "cliente": cliente,
                "total_shopify": float(o.get("total_price", 0)),
                "gateways": o.get("payment_gateway_names", []),
                "payment_ids": payment_ids,
                "created_at": o.get("created_at", "")[:19],
            })

    # Buscar charges Pagar.me do dia
    charges, charges_por_pid = await pagarme_api.buscar_charges(data)

    # Cruzar
    resultados = []
    pids_usados = set()

    for p in sorted(pedidos, key=lambda x: x["created_at"]):
        matched_charges = []
        for pid in p["payment_ids"]:
            if pid in charges_por_pid:
                matched_charges.append(charges_por_pid[pid])
                pids_usados.add(pid)

        if matched_charges:
            total_pm = sum(c["amount"] for c in matched_charges) / 100
            charge_ids = [c["id"] for c in matched_charges]
            taxas, antecip, liquido = _buscar_taxas_payables(charge_ids)
            juros = max(total_pm - p["total_shopify"], 0)
            metodo = matched_charges[0].get("payment_method", "")
            status = "OK"
        else:
            total_pm = taxas = antecip = liquido = juros = 0
            metodo = ""
            gw_alt = [g for g in p["gateways"] if "Pagar.me" not in g]
            status = f"OUTRO GATEWAY ({', '.join(gw_alt)})" if gw_alt else "SEM MATCH"

        resultados.append({
            "pedido": p["name"], "cliente": p["cliente"],
            "total_shopify": p["total_shopify"], "total_pagarme": total_pm,
            "juros": juros, "taxas": taxas, "antecipacao": antecip,
            "liquido": liquido, "metodo": metodo, "status": status,
        })

    # Charges sem pedido do dia — cruzar com banco local
    conn = get_connection()
    for c in charges:
        pid = (c.get("metadata") or {}).get("id", "")
        if pid and pid not in pids_usados:
            row = conn.execute(
                "SELECT name, customer_name, total_price, gateways "
                "FROM shopify_orders WHERE payment_id = ?", (pid,)
            ).fetchone()
            if row:
                total_pm = c["amount"] / 100
                charge_ids = [c["id"]]
                taxas, antecip, liquido = _buscar_taxas_payables(charge_ids)
                juros = max(total_pm - row["total_price"], 0)
                resultados.append({
                    "pedido": row["name"], "cliente": row["customer_name"],
                    "total_shopify": row["total_price"], "total_pagarme": total_pm,
                    "juros": juros, "taxas": taxas, "antecipacao": antecip,
                    "liquido": liquido, "metodo": c.get("payment_method", ""),
                    "status": "OK (outro dia)",
                })
    conn.close()

    # Formatar saída
    conciliados = [r for r in resultados if r["status"].startswith("OK")]
    total_shop = sum(r["total_shopify"] for r in resultados)
    total_pm = sum(r["total_pagarme"] for r in resultados)
    total_juros = sum(r["juros"] for r in resultados)
    total_taxas = sum(r["taxas"] for r in resultados)
    total_liq = sum(r["liquido"] for r in resultados)

    lines = [
        f"Conciliacao Shopify x Pagar.me — {data}\n",
        f"Pedidos: {len(resultados)}  |  Conciliados: {len(conciliados)}  |  "
        f"Nao conciliados: {len(resultados) - len(conciliados)}",
        f"Total Shopify: {fmt(total_shop)}  |  Total Pagar.me: {fmt(total_pm)}",
        "",
        f"{'Pedido':<9} {'Cliente':<28} {'Shopify':>12} {'Pagar.me':>12} "
        f"{'Juros':>10} {'Taxas':>10} {'Liquido':>12} {'Status'}",
        "-" * 110,
    ]

    metodo_labels = {"credit_card": "Cartao", "pix": "Pix", "boleto": "Boleto"}
    for r in resultados:
        lines.append(
            f"{r['pedido']:<9} {r['cliente']:<28} "
            f"{fmt(r['total_shopify']):>12} {fmt(r['total_pagarme']):>12} "
            f"{fmt(r['juros']):>10} {fmt(r['taxas']):>10} "
            f"{fmt(r['liquido']):>12} {r['status']}"
        )

    lines.append("-" * 110)
    lines.append(
        f"{'TOTAL':<9} {'':<28} {fmt(total_shop):>12} {fmt(total_pm):>12} "
        f"{fmt(total_juros):>10} {fmt(total_taxas):>10} {fmt(total_liq):>12}"
    )
    return "\n".join(lines)


async def dispatch(name: str, args: dict) -> str:
    if name == "conciliar_dia":
        return await _conciliar_dia(args["data"])
    return f"Tool '{name}' nao encontrada neste modulo."
