"""Tools de fluxo de caixa diário."""

import mcp.types as types

from banco import get_connection
from tools._fmt import fmt_centavos

TOOLS = [
    types.Tool(
        name="fluxo_caixa",
        description="Fluxo de caixa diario: entradas brutas, saidas (estornos/chargebacks), "
                    "taxas, antecipacoes e liquido, agrupado por dia de pagamento.",
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


def _fluxo_caixa(inicio: str, fim: str) -> str:
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            date(payment_date) AS dia,
            SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END) AS entradas_bruto,
            SUM(CASE WHEN type IN ('refund','chargeback','chargeback_refund')
                     THEN amount ELSE 0 END) AS saidas,
            SUM(fee) AS taxas,
            SUM(anticipation_fee) AS antecipacao,
            SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END)
                - SUM(CASE WHEN type IN ('refund','chargeback','chargeback_refund')
                           THEN amount ELSE 0 END)
                - SUM(fee) - SUM(anticipation_fee) AS liquido,
            COUNT(*) AS qtd_operacoes
        FROM payables
        WHERE date(payment_date) BETWEEN ? AND ?
        GROUP BY date(payment_date)
        ORDER BY dia
    """, (inicio, fim)).fetchall()
    conn.close()

    if not rows:
        return f"Nenhum movimento de {inicio} a {fim}."

    lines = [f"Fluxo de Caixa — {inicio} a {fim}\n"]
    lines.append(f"{'Data':<12} {'Entradas':>15} {'Saidas':>15} {'Taxas':>15} {'Antecip.':>15} {'Liquido':>15}")
    lines.append("-" * 90)

    t_ent = t_sai = t_tax = t_ant = t_liq = 0
    for r in rows:
        ent = (r["entradas_bruto"] or 0) / 100
        sai = (r["saidas"] or 0) / 100
        tax = (r["taxas"] or 0) / 100
        ant = (r["antecipacao"] or 0) / 100
        liq = (r["liquido"] or 0) / 100
        t_ent += ent; t_sai += sai; t_tax += tax; t_ant += ant; t_liq += liq
        from tools._fmt import fmt
        lines.append(f"{r['dia']:<12} {fmt(ent):>15} {fmt(sai):>15} "
                     f"{fmt(tax):>15} {fmt(ant):>15} {fmt(liq):>15}")

    from tools._fmt import fmt
    lines.append("-" * 90)
    lines.append(f"{'TOTAL':<12} {fmt(t_ent):>15} {fmt(t_sai):>15} "
                 f"{fmt(t_tax):>15} {fmt(t_ant):>15} {fmt(t_liq):>15}")
    return "\n".join(lines)


async def dispatch(name: str, args: dict) -> str:
    if name == "fluxo_caixa":
        return _fluxo_caixa(args["inicio"], args["fim"])
    return f"Tool '{name}' nao encontrada neste modulo."
