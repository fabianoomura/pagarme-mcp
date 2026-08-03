"""Tools de recebíveis, resumo financeiro e reembolsos."""

import mcp.types as types

from banco import get_connection
from tools._fmt import fmt_centavos, fmt

TOOLS = [
    types.Tool(
        name="recebiveis_periodo",
        description="Mostra recebiveis (payables) agrupados por dia num periodo. "
                    "Retorna bruto, taxas, liquido e quantidade por data de recebimento.",
        inputSchema={
            "type": "object",
            "properties": {
                "inicio": {"type": "string", "description": "Data inicio (YYYY-MM-DD)"},
                "fim": {"type": "string", "description": "Data fim (YYYY-MM-DD)"},
                "status": {
                    "type": "string",
                    "description": "Filtro: waiting_funds, paid, prepaid, all (padrao: waiting_funds)",
                    "default": "waiting_funds",
                },
            },
            "required": ["inicio", "fim"],
        },
    ),
    types.Tool(
        name="recebiveis_futuros",
        description="Mostra recebiveis com status waiting_funds agrupados por dia. "
                    "Util para ver o que esta programado para cair na conta.",
        inputSchema={"type": "object", "properties": {}},
    ),
    types.Tool(
        name="resumo_financeiro",
        description="Resumo financeiro completo de um periodo: entradas, saidas, taxas, "
                    "antecipacoes, liquido, operacoes, dias com movimento, e quebra por "
                    "metodo de pagamento e tipo de operacao.",
        inputSchema={
            "type": "object",
            "properties": {
                "inicio": {"type": "string", "description": "Data inicio (YYYY-MM-DD)"},
                "fim": {"type": "string", "description": "Data fim (YYYY-MM-DD)"},
            },
            "required": ["inicio", "fim"],
        },
    ),
    types.Tool(
        name="resumo_antecipacoes",
        description="Resumo de antecipacoes: parcelas antecipadas, taxas, media de dias "
                    "antecipados, detalhamento por dia de recebimento.",
        inputSchema={
            "type": "object",
            "properties": {
                "inicio": {"type": "string", "description": "Data inicio (YYYY-MM-DD)"},
                "fim": {"type": "string", "description": "Data fim (YYYY-MM-DD)"},
            },
            "required": ["inicio", "fim"],
        },
    ),
    types.Tool(
        name="listar_reembolsos",
        description="Lista pedidos reembolsados (total ou parcial) num periodo.",
        inputSchema={
            "type": "object",
            "properties": {
                "inicio": {"type": "string", "description": "Data inicio (YYYY-MM-DD)"},
                "fim": {"type": "string", "description": "Data fim (YYYY-MM-DD)"},
            },
            "required": ["inicio", "fim"],
        },
    ),
]


def _recebiveis_periodo(inicio: str, fim: str, status: str) -> str:
    conn = get_connection()
    params = [inicio, fim]
    where_status = ""
    if status != "all":
        where_status = "AND status = ?"
        params.append(status)

    rows = conn.execute(f"""
        SELECT date(payment_date) as dt,
               SUM(amount) as bruto, SUM(fee) as taxa,
               SUM(anticipation_fee) as antecip,
               SUM(amount) - SUM(fee) - SUM(anticipation_fee) as liquido,
               COUNT(*) as qtd
        FROM payables
        WHERE date(payment_date) >= ? AND date(payment_date) <= ?
          {where_status}
        GROUP BY dt ORDER BY dt
    """, params).fetchall()
    conn.close()

    if not rows:
        return f"Nenhum recebivel encontrado de {inicio} a {fim} (status: {status})."

    lines = [f"Recebiveis de {inicio} a {fim} (status: {status}):\n"]
    lines.append(f"{'Data':<12} {'Bruto':>12} {'Taxas':>10} {'Liquido':>12} {'Qtd':>5}")
    lines.append("-" * 55)

    total_b = total_t = total_l = total_q = 0
    for r in rows:
        b, t, l = r["bruto"] / 100, r["taxa"] / 100, r["liquido"] / 100
        total_b += b; total_t += t; total_l += l; total_q += r["qtd"]
        lines.append(f"{r['dt']:<12} {fmt(b):>12} {fmt(t):>10} {fmt(l):>12} {r['qtd']:>5}")

    lines.append("-" * 55)
    lines.append(f"{'TOTAL':<12} {fmt(total_b):>12} {fmt(total_t):>10} {fmt(total_l):>12} {total_q:>5}")
    return "\n".join(lines)


def _recebiveis_futuros() -> str:
    conn = get_connection()
    rows = conn.execute("""
        SELECT date(payment_date) AS dia,
               SUM(amount) AS bruto, SUM(fee) AS taxas,
               SUM(anticipation_fee) AS antecipacao,
               SUM(amount) - SUM(fee) - SUM(anticipation_fee) AS liquido,
               COUNT(*) AS qtd
        FROM payables
        WHERE status = 'waiting_funds'
        GROUP BY date(payment_date) ORDER BY dia
    """).fetchall()
    conn.close()

    if not rows:
        return "Nenhum recebivel futuro encontrado."

    total_liq = sum((r["liquido"] or 0) / 100 for r in rows)
    lines = [f"Recebiveis Futuros (waiting_funds) — Total liquido: {fmt(total_liq)}\n"]
    lines.append(f"{'Data':<12} {'Bruto':>15} {'Taxas':>15} {'Liquido':>15} {'Qtd':>6}")
    lines.append("-" * 67)
    for r in rows:
        lines.append(f"{r['dia']:<12} {fmt_centavos(r['bruto']):>15} "
                     f"{fmt_centavos(r['taxas']):>15} {fmt_centavos(r['liquido']):>15} {r['qtd']:>6}")
    return "\n".join(lines)


def _resumo_financeiro(inicio: str, fim: str) -> str:
    conn = get_connection()

    geral = conn.execute("""
        SELECT
            SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END) AS total_entradas,
            SUM(CASE WHEN type IN ('refund','chargeback','chargeback_refund')
                     THEN amount ELSE 0 END) AS total_saidas,
            SUM(fee) AS total_taxas,
            SUM(anticipation_fee) AS total_antecipacao,
            COUNT(*) AS total_operacoes,
            COUNT(DISTINCT date(payment_date)) AS dias_com_movimento
        FROM payables
        WHERE date(payment_date) BETWEEN ? AND ?
    """, (inicio, fim)).fetchone()

    if not geral or not geral["total_operacoes"]:
        conn.close()
        return f"Nenhum dado financeiro de {inicio} a {fim}."

    entradas = geral["total_entradas"] or 0
    saidas = geral["total_saidas"] or 0
    taxas = geral["total_taxas"] or 0
    antecip = geral["total_antecipacao"] or 0
    liquido = entradas - saidas - taxas - antecip

    lines = [
        f"Resumo Financeiro — {inicio} a {fim}\n",
        f"Entradas (vendas):     {fmt_centavos(entradas)}",
        f"Saidas (estornos):     {fmt_centavos(saidas)}",
        f"Taxas Pagar.me:        {fmt_centavos(taxas)}",
        f"Taxas antecipacao:     {fmt_centavos(antecip)}",
        f"{'—' * 35}",
        f"LIQUIDO:               {fmt_centavos(liquido)}",
        f"\nOperacoes: {geral['total_operacoes']}  |  Dias com movimento: {geral['dias_com_movimento']}",
    ]

    # Por tipo
    tipos = conn.execute("""
        SELECT type AS tipo, COUNT(*) AS qtd,
               SUM(amount) AS total_bruto,
               SUM(amount) - SUM(fee) - SUM(anticipation_fee) AS total_liquido
        FROM payables
        WHERE date(payment_date) BETWEEN ? AND ?
        GROUP BY type ORDER BY total_bruto DESC
    """, (inicio, fim)).fetchall()

    if tipos:
        tipo_labels = {"credit": "Venda", "refund": "Estorno",
                       "chargeback": "Chargeback", "chargeback_refund": "Estorno CB"}
        lines.append("\nPor tipo:")
        for t in tipos:
            label = tipo_labels.get(t["tipo"], t["tipo"])
            lines.append(f"  {label:<20} Qtd: {t['qtd']:<6} "
                         f"Bruto: {fmt_centavos(t['total_bruto']):>15}  "
                         f"Liquido: {fmt_centavos(t['total_liquido']):>15}")

    # Por metodo
    metodos = conn.execute("""
        SELECT payment_method AS metodo, COUNT(*) AS qtd,
               SUM(amount) AS total_bruto, SUM(fee) AS total_taxas,
               SUM(anticipation_fee) AS total_antecipacao,
               SUM(fraud_coverage_fee) AS total_antifraude,
               SUM(amount) - SUM(fee) - SUM(anticipation_fee) AS total_liquido
        FROM payables
        WHERE date(payment_date) BETWEEN ? AND ? AND type = 'credit'
        GROUP BY payment_method ORDER BY total_bruto DESC
    """, (inicio, fim)).fetchall()
    conn.close()

    if metodos:
        metodo_labels = {"credit_card": "Cartao de Credito", "debit_card": "Cartao de Debito",
                         "pix": "Pix", "boleto": "Boleto", "voucher": "Voucher"}
        lines.append("\nPor metodo de pagamento:")
        for m in metodos:
            label = metodo_labels.get(m["metodo"], m["metodo"] or "Outros")
            bruto = m["total_bruto"] or 0
            tax = (m["total_taxas"] or 0) + (m["total_antecipacao"] or 0)
            pct = tax / bruto * 100 if bruto > 0 else 0
            lines.append(f"  {label:<20} Qtd: {m['qtd']:<6} "
                         f"Bruto: {fmt_centavos(bruto):>15}  "
                         f"Taxas: {fmt_centavos(tax):>12} ({pct:.2f}%)  "
                         f"Liquido: {fmt_centavos(m['total_liquido']):>15}")

    return "\n".join(lines)


def _resumo_antecipacoes(inicio: str, fim: str) -> str:
    conn = get_connection()
    resumo = conn.execute("""
        SELECT COUNT(*) AS qtd, SUM(amount) AS total_bruto,
               SUM(fee) AS total_taxas, SUM(anticipation_fee) AS total_antecipacao,
               SUM(amount) - SUM(fee) - SUM(anticipation_fee) AS total_liquido,
               ROUND(AVG(julianday(original_payment_date) - julianday(payment_date)), 0) AS media_dias
        FROM payables
        WHERE anticipation_fee > 0 AND date(payment_date) BETWEEN ? AND ?
    """, (inicio, fim)).fetchone()

    if not resumo or not resumo["qtd"]:
        conn.close()
        return f"Nenhuma antecipacao encontrada de {inicio} a {fim}."

    bruto = resumo["total_bruto"] or 0
    taxa_gw = resumo["total_taxas"] or 0
    taxa_ant = resumo["total_antecipacao"] or 0
    liquido = resumo["total_liquido"] or 0
    pct = taxa_ant / bruto * 100 if bruto > 0 else 0

    lines = [
        f"Antecipacoes — {inicio} a {fim}\n",
        f"Parcelas antecipadas:  {resumo['qtd']}",
        f"Bruto antecipado:      {fmt_centavos(bruto)}",
        f"Taxa gateway:          {fmt_centavos(taxa_gw)}",
        f"Taxa antecipacao:      {fmt_centavos(taxa_ant)}  ({pct:.2f}% do bruto)",
        f"Liquido recebido:      {fmt_centavos(liquido)}",
        f"Media de dias antecip: {int(resumo['media_dias'] or 0)} dias",
    ]

    detalhe = conn.execute("""
        SELECT date(payment_date) AS dia_recebido, COUNT(*) AS qtd,
               SUM(amount) AS bruto, SUM(fee) AS taxa_gateway,
               SUM(anticipation_fee) AS taxa_antecip,
               SUM(amount) - SUM(fee) - SUM(anticipation_fee) AS liquido,
               ROUND(AVG(julianday(original_payment_date) - julianday(payment_date)), 0) AS media_dias
        FROM payables
        WHERE anticipation_fee > 0 AND date(payment_date) BETWEEN ? AND ?
        GROUP BY date(payment_date) ORDER BY dia_recebido
    """, (inicio, fim)).fetchall()
    conn.close()

    if detalhe:
        lines.append(f"\n{'Data':.<12} {'Bruto':>15} {'Taxa Antecip':>15} {'Liquido':>15} {'Dias':>6} {'Qtd':>6}")
        lines.append("-" * 75)
        for r in detalhe:
            lines.append(f"{r['dia_recebido']:<12} {fmt_centavos(r['bruto']):>15} "
                         f"{fmt_centavos(r['taxa_antecip']):>15} {fmt_centavos(r['liquido']):>15} "
                         f"{int(r['media_dias'] or 0):>6} {r['qtd']:>6}")

    return "\n".join(lines)


def _listar_reembolsos(inicio: str, fim: str) -> str:
    conn = get_connection()
    rows = conn.execute("""
        SELECT o.name, o.customer_name, o.total_price, o.refund_total,
               o.financial_status, o.created_at
        FROM shopify_orders o
        WHERE o.refund_total > 0
          AND substr(o.created_at, 1, 10) >= ? AND substr(o.created_at, 1, 10) <= ?
        ORDER BY o.created_at DESC
    """, (inicio, fim)).fetchall()
    conn.close()

    if not rows:
        return f"Nenhum reembolso encontrado de {inicio} a {fim}."

    total_reembolsado = sum(r["refund_total"] for r in rows)
    lines = [
        f"Reembolsos de {inicio} a {fim}: {len(rows)} pedidos\n",
        f"{'Pedido':<9} {'Cliente':<25} {'Total':>10} {'Reembolso':>10} {'Status'}",
        "-" * 70,
    ]
    for r in rows:
        lines.append(f"{r['name']:<9} {r['customer_name']:<25} "
                     f"{fmt(r['total_price']):>10} {fmt(r['refund_total']):>10} "
                     f"{r['financial_status']}")
    lines.append("-" * 70)
    lines.append(f"Total reembolsado: {fmt(total_reembolsado)}")
    return "\n".join(lines)


async def dispatch(name: str, args: dict) -> str:
    if name == "recebiveis_periodo":
        return _recebiveis_periodo(args["inicio"], args["fim"], args.get("status", "waiting_funds"))
    elif name == "recebiveis_futuros":
        return _recebiveis_futuros()
    elif name == "resumo_financeiro":
        return _resumo_financeiro(args["inicio"], args["fim"])
    elif name == "resumo_antecipacoes":
        return _resumo_antecipacoes(args["inicio"], args["fim"])
    elif name == "listar_reembolsos":
        return _listar_reembolsos(args["inicio"], args["fim"])
    return f"Tool '{name}' nao encontrada neste modulo."
