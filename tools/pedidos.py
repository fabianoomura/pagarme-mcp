"""Tools de pedidos Shopify e fluxo de recebimento por pedido."""

import mcp.types as types

from banco import get_connection
from tools._fmt import fmt, fmt_centavos
import pagarme_api

TOOLS = [
    types.Tool(
        name="buscar_pedido",
        description="Busca informacoes de um pedido Shopify no banco local: "
                    "cliente, valores, status financeiro, reembolsos, gateway.",
        inputSchema={
            "type": "object",
            "properties": {
                "pedido": {"type": "string", "description": "Numero do pedido (ex: #14328)"},
            },
            "required": ["pedido"],
        },
    ),
    types.Tool(
        name="fluxo_pedido",
        description="Mostra o fluxo de recebimento de um pedido especifico: parcelas, "
                    "taxas, datas de recebimento e status de cada parcela. "
                    "Usa banco local se disponivel, senao consulta API.",
        inputSchema={
            "type": "object",
            "properties": {
                "pedido": {"type": "string", "description": "Numero do pedido (ex: #14328)"},
            },
            "required": ["pedido"],
        },
    ),
]


def _norm(pedido: str) -> str:
    if not pedido.startswith("#"):
        return f"#{pedido}"
    return pedido


def _buscar_pedido(nome: str) -> str:
    conn = get_connection()
    order = conn.execute(
        "SELECT * FROM shopify_orders WHERE name = ?", (nome,)
    ).fetchone()

    if not order:
        conn.close()
        return f"Pedido {nome} nao encontrado no banco."

    refunds = conn.execute(
        "SELECT * FROM shopify_refunds WHERE order_id = ?", (order["order_id"],)
    ).fetchall()
    conn.close()

    lines = [
        f"Pedido {order['name']}",
        f"Cliente: {order['customer_name']}",
        f"Email: {order['email']}",
        f"Data: {order['created_at'][:10]}",
        "",
        f"Subtotal:   {fmt(order['subtotal'])}",
        f"Desconto:   {fmt(order['desconto'])}",
        f"Frete:      {fmt(order['frete'])}",
        f"Total:      {fmt(order['total_price'])}",
        "",
        f"Status financeiro: {order['financial_status']}",
        f"Gateway: {order['gateways']}",
        f"Tags: {order['tags'] or '-'}",
    ]

    if order["refund_total"] and order["refund_total"] > 0:
        lines.append(f"\nReembolso total: {fmt(order['refund_total'])}")
        for r in refunds:
            lines.append(f"  {r['created_at'][:10]}: {fmt(r['amount'])} ({r['reason'] or 'sem motivo'})")

    if order["cancelled_at"]:
        lines.append(f"\nCancelado em: {order['cancelled_at'][:10]}")
        lines.append(f"Motivo: {order['cancel_reason'] or '-'}")

    return "\n".join(lines)


def _fluxo_local(nome: str) -> str | None:
    """Tenta retornar fluxo usando dados do banco local."""
    conn = get_connection()
    order = conn.execute(
        "SELECT * FROM shopify_orders WHERE name = ?", (nome,)
    ).fetchone()

    if not order:
        conn.close()
        return None

    charge_id = order["charge_id"]
    if not charge_id:
        conn.close()
        return None

    charge_ids = [cid.strip() for cid in charge_id.split(",")]
    placeholders = ",".join("?" * len(charge_ids))
    payables = conn.execute(f"""
        SELECT * FROM payables
        WHERE charge_id IN ({placeholders})
        ORDER BY charge_id, installment
    """, charge_ids).fetchall()
    conn.close()

    if not payables:
        return None

    total_cobrado = sum(p["amount"] for p in payables) / 100
    juros = max(total_cobrado - order["total_price"], 0)
    metodos = set(p["payment_method"] for p in payables if p["payment_method"])
    metodo_label = ", ".join({
        "credit_card": "Cartao", "pix": "Pix", "boleto": "Boleto"
    }.get(m, m) for m in metodos)

    lines = [
        f"Fluxo de Recebimento — Pedido {order['name']}",
        f"Cliente: {order['customer_name']}",
        f"Total Shopify: {fmt(order['total_price'])}",
        f"Metodo: {metodo_label}  |  Cobrado: {fmt(total_cobrado)}",
    ]
    if juros > 0:
        lines.append(f"Juros parcelamento: {fmt(juros)}")

    lines.append("")
    lines.append(f"{'Parc':<8} {'Bruto':>10} {'Taxa':>10} {'Liquido':>10} {'Status':<14} {'Recebimento'}")
    lines.append("-" * 70)

    total_b = total_t = total_l = 0
    for p in payables:
        b = p["amount"] / 100
        t = p["fee"] / 100
        a = (p["anticipation_fee"] or 0) / 100
        l = b - t - a
        total_b += b; total_t += t; total_l += l
        dt = (p["payment_date"] or "")[:10]
        inst = p["installment"] if p["installment"] else "-"
        lines.append(f"{inst:<8} {fmt(b):>10} {fmt(t):>10} {fmt(l):>10} {p['status']:<14} {dt}")

    lines.append("-" * 70)
    lines.append(f"{'TOTAL':<8} {fmt(total_b):>10} {fmt(total_t):>10} {fmt(total_l):>10}")
    return "\n".join(lines)


async def _fluxo_api(nome: str) -> str:
    """Busca fluxo via API quando não tem no banco local."""
    conn = get_connection()
    order = conn.execute(
        "SELECT * FROM shopify_orders WHERE name = ?", (nome,)
    ).fetchone()
    conn.close()

    if not order:
        return f"Pedido {nome} nao encontrado no banco."

    pid = order["payment_id"]
    if not pid:
        return f"Pedido {nome} sem payment_id (gateway alternativo)."

    charges = await pagarme_api.buscar_order_charges(pid)
    if not charges:
        return f"Order nao encontrada na Pagar.me para payment_id {pid}"

    lines = [
        f"Fluxo de Recebimento — Pedido {order['name']}",
        f"Cliente: {order['customer_name']}",
        f"Total Shopify: {fmt(order['total_price'])}",
        "",
    ]

    for c in charges:
        metodo = {"credit_card": "Cartao", "pix": "Pix", "boleto": "Boleto"}.get(
            c.get("payment_method", ""), c.get("payment_method", ""))
        total_pm = c["amount"] / 100
        juros = max(total_pm - order["total_price"], 0)

        lines.append(f"Metodo: {metodo}  |  Cobrado: {fmt(total_pm)}" +
                     (f"  (juros: {fmt(juros)})" if juros > 0 else ""))

        pays = await pagarme_api.buscar_payables_por_charge(c["id"])

        if pays:
            lines.append("")
            lines.append(f"{'Parc':<8} {'Bruto':>10} {'Taxa':>10} {'Liquido':>10} {'Status':<14} {'Recebimento'}")
            lines.append("-" * 70)

            total_b = total_t = total_l = 0
            for p in sorted(pays, key=lambda x: x.get("installment", 0)):
                b = p["amount"] / 100
                t = p["fee"] / 100
                a = (p.get("anticipation_fee") or 0) / 100
                l = b - t - a
                total_b += b; total_t += t; total_l += l
                dt = (p.get("payment_date") or "")[:10]
                lines.append(f"{p.get('installment', '-'):<8} {fmt(b):>10} {fmt(t):>10} "
                             f"{fmt(l):>10} {p['status']:<14} {dt}")

            lines.append("-" * 70)
            lines.append(f"{'TOTAL':<8} {fmt(total_b):>10} {fmt(total_t):>10} {fmt(total_l):>10}")
        lines.append("")

    # Salvar charge_id no banco para próximas consultas
    charge_ids = ",".join(c["id"] for c in charges)
    conn = get_connection()
    conn.execute(
        "UPDATE shopify_orders SET charge_id = ? WHERE order_id = ?",
        (charge_ids, order["order_id"])
    )
    conn.commit()
    conn.close()

    return "\n".join(lines)


async def dispatch(name: str, args: dict) -> str:
    if name == "buscar_pedido":
        return _buscar_pedido(_norm(args["pedido"]))
    elif name == "fluxo_pedido":
        nome = _norm(args["pedido"])
        result = _fluxo_local(nome)
        if result:
            return result
        return await _fluxo_api(nome)
    return f"Tool '{name}' nao encontrada neste modulo."
