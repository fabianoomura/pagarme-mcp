"""
Database module — consultas ao SQLite local.
"""

import sqlite3
from pathlib import Path


def _fmt(valor):
    """Formata valor em reais."""
    if valor is None:
        return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


class Database:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def recebiveis_periodo(self, inicio: str, fim: str, status: str = "waiting_funds") -> str:
        conn = self._conn()
        params = [inicio, fim]
        if status == "all":
            where_status = ""
        else:
            where_status = "AND status = ?"
            params.append(status)

        rows = conn.execute(f"""
            SELECT substr(payment_date, 1, 10) as dt,
                   SUM(amount) as bruto,
                   SUM(fee) as taxa,
                   SUM(anticipation_fee) as antecip,
                   SUM(amount) - SUM(fee) - SUM(anticipation_fee) as liquido,
                   COUNT(*) as qtd
            FROM payables
            WHERE substr(payment_date, 1, 10) >= ? AND substr(payment_date, 1, 10) <= ?
              {where_status}
            GROUP BY dt
            ORDER BY dt
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
            lines.append(f"{r['dt']:<12} {_fmt(b):>12} {_fmt(t):>10} {_fmt(l):>12} {r['qtd']:>5}")

        lines.append("-" * 55)
        lines.append(f"{'TOTAL':<12} {_fmt(total_b):>12} {_fmt(total_t):>10} {_fmt(total_l):>12} {total_q:>5}")

        return "\n".join(lines)

    def fluxo_pedido_local(self, nome_pedido: str) -> str | None:
        """Tenta retornar fluxo do pedido usando dados locais."""
        conn = self._conn()
        order = conn.execute(
            "SELECT * FROM shopify_orders WHERE name = ?", (nome_pedido,)
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
            f"Fluxo de Recebimento - Pedido {order['name']}",
            f"Cliente: {order['customer_name']}",
            f"Total Shopify: {_fmt(order['total_price'])}",
            f"Metodo: {metodo_label} | Cobrado: {_fmt(total_cobrado)}",
        ]
        if juros > 0:
            lines.append(f"Juros parcelamento: {_fmt(juros)}")
        lines.append("")
        lines.append(f"{'Parc':<5} {'Bruto':>10} {'Taxa':>10} {'Liquido':>10} {'Status':<14} {'Recebimento'}")
        lines.append("-" * 65)

        total_b = total_t = total_l = 0
        for p in payables:
            b = p["amount"] / 100
            t = p["fee"] / 100
            a = (p["anticipation_fee"] or 0) / 100
            l = b - t - a
            total_b += b; total_t += t; total_l += l
            dt = (p["payment_date"] or "")[:10]
            inst = p["installment"] if p["installment"] else "-"
            lines.append(f"{inst:<5} {_fmt(b):>10} {_fmt(t):>10} {_fmt(l):>10} {p['status']:<14} {dt}")

        lines.append("-" * 65)
        lines.append(f"{'TOTAL':<5} {_fmt(total_b):>10} {_fmt(total_t):>10} {_fmt(total_l):>10}")

        return "\n".join(lines)

    def fluxo_caixa(self, inicio: str, fim: str) -> str:
        conn = self._conn()
        rows = conn.execute("""
            SELECT substr(payment_date, 1, 10) as dt,
                   SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END) as entradas,
                   SUM(CASE WHEN type != 'credit' THEN amount ELSE 0 END) as saidas,
                   SUM(fee) as taxas,
                   SUM(anticipation_fee) as antecip,
                   SUM(amount) - SUM(fee) - SUM(anticipation_fee) as liquido,
                   COUNT(*) as qtd
            FROM payables
            WHERE substr(payment_date, 1, 10) >= ? AND substr(payment_date, 1, 10) <= ?
              AND status IN ('paid', 'prepaid')
            GROUP BY dt
            ORDER BY dt
        """, (inicio, fim)).fetchall()
        conn.close()

        if not rows:
            return f"Nenhum movimento de {inicio} a {fim}."

        lines = [f"Fluxo de Caixa - {inicio} a {fim}\n"]
        lines.append(f"{'Data':<12} {'Entradas':>12} {'Saidas':>12} {'Taxas':>10} {'Liquido':>12}")
        lines.append("-" * 62)

        t_ent = t_sai = t_tax = t_liq = 0
        for r in rows:
            ent = r["entradas"] / 100
            sai = r["saidas"] / 100
            tax = r["taxas"] / 100
            liq = r["liquido"] / 100
            t_ent += ent; t_sai += sai; t_tax += tax; t_liq += liq
            lines.append(f"{r['dt']:<12} {_fmt(ent):>12} {_fmt(sai):>12} {_fmt(tax):>10} {_fmt(liq):>12}")

        lines.append("-" * 62)
        lines.append(f"{'TOTAL':<12} {_fmt(t_ent):>12} {_fmt(t_sai):>12} {_fmt(t_tax):>10} {_fmt(t_liq):>12}")

        return "\n".join(lines)

    def resumo_financeiro(self, inicio: str, fim: str) -> str:
        conn = self._conn()

        # Resumo geral
        geral = conn.execute("""
            SELECT
                SUM(CASE WHEN type = 'credit' THEN amount ELSE 0 END) as entradas,
                SUM(CASE WHEN type != 'credit' THEN amount ELSE 0 END) as saidas,
                SUM(fee) as taxas,
                SUM(anticipation_fee) as antecip,
                SUM(amount) - SUM(fee) - SUM(anticipation_fee) as liquido,
                COUNT(*) as qtd
            FROM payables
            WHERE substr(payment_date, 1, 10) >= ? AND substr(payment_date, 1, 10) <= ?
              AND status IN ('paid', 'prepaid')
        """, (inicio, fim)).fetchone()

        # Por metodo
        metodos = conn.execute("""
            SELECT payment_method,
                   SUM(amount) as bruto,
                   SUM(fee) as taxa,
                   COUNT(*) as qtd
            FROM payables
            WHERE substr(payment_date, 1, 10) >= ? AND substr(payment_date, 1, 10) <= ?
              AND status IN ('paid', 'prepaid')
            GROUP BY payment_method
            ORDER BY bruto DESC
        """, (inicio, fim)).fetchall()
        conn.close()

        if not geral or geral["qtd"] == 0:
            return f"Nenhum dado financeiro de {inicio} a {fim}."

        lines = [
            f"Resumo Financeiro - {inicio} a {fim}\n",
            f"Entradas (vendas):  {_fmt(geral['entradas'] / 100)}",
            f"Saidas (estornos):  {_fmt(geral['saidas'] / 100)}",
            f"Taxas Pagar.me:     {_fmt(geral['taxas'] / 100)}",
            f"Antecipacoes:       {_fmt(geral['antecip'] / 100)}",
            f"Liquido:            {_fmt(geral['liquido'] / 100)}",
            f"Operacoes:          {geral['qtd']}",
            "",
            "Por metodo de pagamento:",
        ]

        metodo_labels = {"credit_card": "Cartao", "pix": "Pix", "boleto": "Boleto"}
        for m in metodos:
            label = metodo_labels.get(m["payment_method"], m["payment_method"] or "Outro")
            bruto = m["bruto"] / 100
            taxa = m["taxa"] / 100
            pct = (taxa / bruto * 100) if bruto > 0 else 0
            lines.append(f"  {label:<15} {_fmt(bruto):>12}  taxa: {_fmt(taxa):>10} ({pct:.2f}%)  qtd: {m['qtd']}")

        return "\n".join(lines)

    def buscar_pedido(self, nome_pedido: str) -> str:
        conn = self._conn()
        order = conn.execute(
            "SELECT * FROM shopify_orders WHERE name = ?", (nome_pedido,)
        ).fetchone()

        if not order:
            conn.close()
            return f"Pedido {nome_pedido} nao encontrado no banco."

        # Buscar reembolsos
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
            f"Subtotal:   {_fmt(order['subtotal'])}",
            f"Desconto:   {_fmt(order['desconto'])}",
            f"Frete:      {_fmt(order['frete'])}",
            f"Total:      {_fmt(order['total_price'])}",
            "",
            f"Status financeiro: {order['financial_status']}",
            f"Gateway: {order['gateways']}",
            f"Tags: {order['tags'] or '-'}",
        ]

        if order["refund_total"] and order["refund_total"] > 0:
            lines.append(f"\nReembolso total: {_fmt(order['refund_total'])}")
            for r in refunds:
                lines.append(f"  {r['created_at'][:10]}: {_fmt(r['amount'])} ({r['reason'] or 'sem motivo'})")

        if order["cancelled_at"]:
            lines.append(f"\nCancelado em: {order['cancelled_at'][:10]}")
            lines.append(f"Motivo: {order['cancel_reason'] or '-'}")

        return "\n".join(lines)

    def listar_reembolsos(self, inicio: str, fim: str) -> str:
        conn = self._conn()
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
            lines.append(
                f"{r['name']:<9} {r['customer_name']:<25} "
                f"{_fmt(r['total_price']):>10} {_fmt(r['refund_total']):>10} "
                f"{r['financial_status']}"
            )

        lines.append("-" * 70)
        lines.append(f"Total reembolsado: {_fmt(total_reembolsado)}")

        return "\n".join(lines)
