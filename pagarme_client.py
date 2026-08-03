"""
Client para APIs Pagar.me v5 e Shopify Admin.
"""

import base64
import asyncio
from datetime import datetime, timedelta

import httpx

from db import Database, _fmt


class PagarmeClient:
    def __init__(self, secret_key: str, shopify_token: str = "",
                 shopify_url: str = "", shopify_version: str = "2024-01"):
        self.api_url = "https://api.pagar.me/core/v5"
        token = base64.b64encode(f"{secret_key}:".encode()).decode()
        self.pm_headers = {
            "accept": "application/json",
            "authorization": f"Basic {token}",
        }
        self.shopify_token = shopify_token
        self.shopify_url = shopify_url
        self.shopify_version = shopify_version
        self.shopify_headers = {
            "X-Shopify-Access-Token": shopify_token,
            "Content-Type": "application/json",
        }

    async def fluxo_pedido(self, nome_pedido: str, db: Database) -> str:
        """Busca fluxo de recebimento via API quando nao tem no banco."""
        conn = db._conn()
        order = conn.execute(
            "SELECT * FROM shopify_orders WHERE name = ?", (nome_pedido,)
        ).fetchone()
        conn.close()

        if not order:
            return f"Pedido {nome_pedido} nao encontrado no banco."

        pid = order["payment_id"]
        if not pid:
            return f"Pedido {nome_pedido} sem payment_id (gateway alternativo)."

        async with httpx.AsyncClient(timeout=30) as client:
            # Buscar order na Pagar.me pelo code
            r = await client.get(
                f"{self.api_url}/orders",
                headers=self.pm_headers,
                params={"code": pid}
            )
            r.raise_for_status()
            orders_pm = r.json().get("data", [])

            if not orders_pm:
                return f"Order nao encontrada na Pagar.me para payment_id {pid}"

            # Buscar detalhes com charges
            r2 = await client.get(
                f"{self.api_url}/orders/{orders_pm[0]['id']}",
                headers=self.pm_headers,
            )
            r2.raise_for_status()
            charges = r2.json().get("charges", [])

            if not charges:
                return "Nenhuma charge encontrada para este pedido."

            # Buscar payables de cada charge
            lines = [
                f"Fluxo de Recebimento - Pedido {order['name']}",
                f"Cliente: {order['customer_name']}",
                f"Total Shopify: {_fmt(order['total_price'])}",
                "",
            ]

            for c in charges:
                metodo = {"credit_card": "Cartao", "pix": "Pix", "boleto": "Boleto"}.get(
                    c.get("payment_method", ""), c.get("payment_method", "")
                )
                total_pm = c["amount"] / 100
                juros = max(total_pm - order["total_price"], 0)

                lines.append(f"Metodo: {metodo} | Cobrado: {_fmt(total_pm)}" +
                             (f" (juros: {_fmt(juros)})" if juros > 0 else ""))

                r3 = await client.get(
                    f"{self.api_url}/payables",
                    headers=self.pm_headers,
                    params={"charge_id": c["id"], "size": 100}
                )
                pays = r3.json().get("data", [])

                if pays:
                    lines.append("")
                    lines.append(f"{'Parc':<5} {'Bruto':>10} {'Taxa':>10} {'Liquido':>10} {'Status':<14} {'Recebimento'}")
                    lines.append("-" * 65)

                    total_b = total_t = total_l = 0
                    for p in sorted(pays, key=lambda x: x.get("installment", 0)):
                        b = p["amount"] / 100
                        t = p["fee"] / 100
                        a = (p.get("anticipation_fee") or 0) / 100
                        l = b - t - a
                        total_b += b; total_t += t; total_l += l
                        dt = (p.get("payment_date") or "")[:10]
                        inst = p.get("installment", "-")
                        lines.append(f"{inst:<5} {_fmt(b):>10} {_fmt(t):>10} {_fmt(l):>10} {p['status']:<14} {dt}")

                    lines.append("-" * 65)
                    lines.append(f"{'TOTAL':<5} {_fmt(total_b):>10} {_fmt(total_t):>10} {_fmt(total_l):>10}")
                lines.append("")

            # Salvar charge_id no banco para proximas consultas
            charge_ids = ",".join(c["id"] for c in charges)
            conn = db._conn()
            conn.execute(
                "UPDATE shopify_orders SET charge_id = ? WHERE order_id = ?",
                (charge_ids, order["order_id"])
            )
            conn.commit()
            conn.close()

            return "\n".join(lines)

    async def conciliar_dia(self, data: str, db: Database) -> str:
        """Concilia pedidos Shopify x Pagar.me de um dia."""
        async with httpx.AsyncClient(timeout=30) as client:
            # Buscar pedidos Shopify do dia
            base = f"https://{self.shopify_url}/admin/api/{self.shopify_version}"
            r = await client.get(
                f"{base}/orders.json",
                headers=self.shopify_headers,
                params={
                    "created_at_min": f"{data}T00:00:00-03:00",
                    "created_at_max": f"{data}T23:59:59-03:00",
                    "status": "any",
                    "financial_status": "paid",
                    "limit": 250,
                }
            )
            r.raise_for_status()
            orders = r.json().get("orders", [])

            # Buscar charges Pagar.me do dia
            charges_por_pid = {}
            page = 1
            while True:
                rc = await client.get(
                    f"{self.api_url}/charges",
                    headers=self.pm_headers,
                    params={
                        "created_since": f"{data}T00:00:00Z",
                        "created_until": f"{data}T23:59:59-03:00",
                        "status": "paid",
                        "size": 100,
                        "page": page,
                    }
                )
                rc.raise_for_status()
                dados = rc.json().get("data", [])
                if not dados:
                    break
                for c in dados:
                    pid = (c.get("metadata") or {}).get("id", "")
                    if pid:
                        charges_por_pid[pid] = c
                page += 1
                await asyncio.sleep(0.3)

            # Cruzar
            conciliados = 0
            outros = 0
            total_shop = 0
            total_pm = 0
            resultados = []

            for o in orders:
                # Buscar payment_id
                rt = await client.get(
                    f"{base}/orders/{o['id']}/transactions.json",
                    headers=self.shopify_headers,
                )
                txns = rt.json().get("transactions", [])
                await asyncio.sleep(0.3)

                payment_ids = []
                for t in txns:
                    pid = (t.get("receipt") or {}).get("payment_id", "")
                    if pid and t.get("status") == "success":
                        payment_ids.append(pid)

                customer = o.get("customer", {}) or {}
                cliente = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
                total_s = float(o.get("total_price", 0))
                total_shop += total_s

                matched = [charges_por_pid[pid] for pid in payment_ids if pid in charges_por_pid]
                if matched:
                    t_pm = sum(c["amount"] for c in matched) / 100
                    total_pm += t_pm
                    conciliados += 1
                    status = "OK"
                else:
                    t_pm = 0
                    gw = [g for g in o.get("payment_gateway_names", []) if "Pagar.me" not in g]
                    status = f"OUTRO GATEWAY ({', '.join(gw)})" if gw else "SEM MATCH"
                    outros += 1

                resultados.append(f"  {o.get('name', ''):<9} {cliente:<25} {_fmt(total_s):>10} {_fmt(t_pm):>10} {status}")

            lines = [
                f"Conciliacao Shopify x Pagar.me - {data}\n",
                f"Pedidos: {len(orders)} | Conciliados: {conciliados} | Nao conciliados: {outros}",
                f"Total Shopify: {_fmt(total_shop)} | Total Pagar.me: {_fmt(total_pm)}",
                "",
                f"{'Pedido':<11} {'Cliente':<25} {'Shopify':>10} {'Pagar.me':>10} {'Status'}",
                "-" * 75,
            ]
            lines.extend(resultados)

            return "\n".join(lines)

    async def sincronizar(self, dias: int, db: Database) -> str:
        """Sincroniza payables e pedidos Shopify."""
        hoje = datetime.now().strftime("%Y-%m-%d")
        inicio = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")

        lines = [f"Sincronizando dados de {inicio} a {hoje}...\n"]

        async with httpx.AsyncClient(timeout=30) as client:
            # Sync payables
            payables = []
            page = 1
            while True:
                r = await client.get(
                    f"{self.api_url}/payables",
                    headers=self.pm_headers,
                    params={
                        "created_since": f"{inicio}T00:00:00Z",
                        "created_until": f"{hoje}T23:59:59Z",
                        "size": 1000,
                        "page": page,
                    }
                )
                r.raise_for_status()
                dados = r.json().get("data", [])
                if not dados:
                    break
                payables.extend(dados)
                page += 1
                await asyncio.sleep(0.3)

            # Salvar payables
            if payables:
                conn = db._conn()
                for p in payables:
                    conn.execute("""
                        INSERT OR REPLACE INTO payables (
                            id, status, type, amount, fee, anticipation_fee,
                            payment_date, accrual_date, original_payment_date,
                            installment, payment_method, fraud_coverage_fee,
                            gateway_id, charge_id, recipient_id,
                            split_id, created_at, updated_at, synced_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """, (
                        str(p.get("id", "")), p.get("status"), p.get("type"),
                        p.get("amount", 0), p.get("fee", 0), p.get("anticipation_fee", 0),
                        p.get("payment_date"), p.get("accrual_at"), p.get("original_payment_date"),
                        p.get("installment"), p.get("payment_method"), p.get("fraud_coverage_fee", 0),
                        p.get("gateway_id"), p.get("charge_id"), p.get("recipient_id"),
                        p.get("split_id"), p.get("created_at"), p.get("updated_at"),
                    ))
                conn.commit()
                conn.close()

            lines.append(f"Payables: {len(payables)} registros sincronizados")

        lines.append("\nSincronizacao concluida.")
        return "\n".join(lines)
