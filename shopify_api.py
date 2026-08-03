"""Client async para Shopify Admin API."""

import asyncio

import httpx

from config import SHOPIFY_ACCESS_TOKEN, SHOPIFY_SHOP_URL, SHOPIFY_API_VERSION

BASE_URL = f"https://{SHOPIFY_SHOP_URL}/admin/api/{SHOPIFY_API_VERSION}"


def _headers() -> dict:
    return {
        "X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN,
        "Content-Type": "application/json",
    }


async def _get(client: httpx.AsyncClient, url: str, params: dict | None = None,
               max_retries: int = 3) -> httpx.Response:
    """GET com retry e rate limit."""
    for attempt in range(max_retries):
        try:
            r = await client.get(url, headers=_headers(), params=params)
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 2))
                await asyncio.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except (httpx.ConnectError, httpx.TimeoutException):
            if attempt < max_retries - 1:
                await asyncio.sleep(3)
            else:
                raise
    raise httpx.HTTPError("Max retries exceeded")


async def buscar_pedidos(params_base: dict) -> list[dict]:
    """Busca pedidos paginados usando Link header (cursor pagination)."""
    todos = []
    params = {**params_base, "limit": 250}
    url = f"{BASE_URL}/orders.json"

    async with httpx.AsyncClient(timeout=30) as client:
        while url:
            r = await _get(client, url, params)
            orders = r.json().get("orders", [])
            todos.extend(orders)

            link = r.headers.get("Link", "")
            url = None
            params = None
            if 'rel="next"' in link:
                for part in link.split(","):
                    if 'rel="next"' in part:
                        url = part.split("<")[1].split(">")[0]
                        break

            await asyncio.sleep(0.5)

    return todos


async def buscar_transactions(order_id: int) -> list[dict]:
    """Busca transactions de um pedido para pegar payment_id."""
    async with httpx.AsyncClient(timeout=30) as client:
        r = await _get(client, f"{BASE_URL}/orders/{order_id}/transactions.json")
        await asyncio.sleep(0.3)
        return r.json().get("transactions", [])


def extrair_payment_id(transactions: list[dict]) -> str:
    """Extrai o payment_id da transação de sucesso."""
    for t in transactions:
        pid = (t.get("receipt") or {}).get("payment_id", "")
        if pid and t.get("status") == "success":
            return pid
    return ""


def calcular_refund_total(order: dict) -> float:
    total = 0
    for refund in order.get("refunds", []):
        for txn in refund.get("transactions", []):
            if txn.get("kind") == "refund" and txn.get("status") == "success":
                total += float(txn.get("amount", 0))
    return total


def extrair_refunds(order: dict) -> list[dict]:
    refunds = []
    for refund in order.get("refunds", []):
        amount = 0
        for txn in refund.get("transactions", []):
            if txn.get("kind") == "refund" and txn.get("status") == "success":
                amount += float(txn.get("amount", 0))
        refunds.append({
            "refund_id": refund["id"],
            "order_id": order["id"],
            "amount": amount,
            "reason": refund.get("reason", ""),
            "note": refund.get("note", ""),
            "created_at": refund.get("created_at", ""),
        })
    return refunds


def normalizar_pedido(order: dict, payment_id: str = "") -> dict:
    customer = order.get("customer", {}) or {}
    nome = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
    frete = float(
        (order.get("total_shipping_price_set", {}).get("shop_money", {}) or {}).get("amount", 0)
    )
    return {
        "order_id": order["id"],
        "name": order.get("name", ""),
        "customer_name": nome,
        "email": customer.get("email", ""),
        "subtotal": float(order.get("subtotal_price", 0)),
        "desconto": float(order.get("total_discounts", 0)),
        "frete": frete,
        "total_price": float(order.get("total_price", 0)),
        "financial_status": order.get("financial_status", ""),
        "fulfillment_status": order.get("fulfillment_status", ""),
        "gateways": ", ".join(order.get("payment_gateway_names", [])),
        "payment_id": payment_id,
        "charge_id": "",
        "cancel_reason": order.get("cancel_reason", ""),
        "cancelled_at": order.get("cancelled_at", ""),
        "refund_total": calcular_refund_total(order),
        "tags": order.get("tags", ""),
        "note": order.get("note", ""),
        "created_at": order.get("created_at", ""),
        "updated_at": order.get("updated_at", ""),
    }
