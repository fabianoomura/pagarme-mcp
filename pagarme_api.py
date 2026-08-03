"""Client async para API Pagar.me v5."""

import asyncio
import base64

import httpx

from config import PAGARME_API_URL, PAGARME_SECRET_KEY, PAGE_SIZE


def _auth_headers() -> dict:
    if not PAGARME_SECRET_KEY:
        raise ValueError("PAGARME_SECRET_KEY nao configurada.")
    token = base64.b64encode(f"{PAGARME_SECRET_KEY}:".encode()).decode()
    return {
        "accept": "application/json",
        "authorization": f"Basic {token}",
    }


async def buscar_payables(data_inicio: str, data_fim: str) -> list[dict]:
    """Busca todos os payables de um periodo, iterando todas as paginas."""
    headers = _auth_headers()
    todos = []
    page = 1

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            r = await client.get(
                f"{PAGARME_API_URL}/payables",
                headers=headers,
                params={
                    "created_since": f"{data_inicio}T00:00:00Z",
                    "created_until": f"{data_fim}T23:59:59Z",
                    "size": PAGE_SIZE,
                    "page": page,
                },
            )
            r.raise_for_status()
            dados = r.json().get("data", [])
            if not dados:
                break
            todos.extend(dados)
            if len(dados) < PAGE_SIZE:
                break
            page += 1
            await asyncio.sleep(0.3)

    return todos


async def buscar_charges(data: str) -> tuple[list[dict], dict[str, dict]]:
    """Busca charges pagas de um dia. Retorna (lista, dict por payment_id)."""
    headers = _auth_headers()
    charges = []
    page = 1

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            r = await client.get(
                f"{PAGARME_API_URL}/charges",
                headers=headers,
                params={
                    "created_since": f"{data}T00:00:00Z",
                    "created_until": f"{data}T23:59:59-03:00",
                    "status": "paid",
                    "size": 100,
                    "page": page,
                },
            )
            r.raise_for_status()
            dados = r.json().get("data", [])
            if not dados:
                break
            charges.extend(dados)
            page += 1
            await asyncio.sleep(0.3)

    por_pid = {}
    for c in charges:
        pid = (c.get("metadata") or {}).get("id", "")
        if pid:
            por_pid[pid] = c

    return charges, por_pid


async def buscar_order_charges(payment_id: str) -> list[dict]:
    """Busca order + charges na Pagar.me pelo code (payment_id)."""
    headers = _auth_headers()

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{PAGARME_API_URL}/orders",
            headers=headers,
            params={"code": payment_id},
        )
        r.raise_for_status()
        orders = r.json().get("data", [])
        if not orders:
            return []

        r2 = await client.get(
            f"{PAGARME_API_URL}/orders/{orders[0]['id']}",
            headers=headers,
        )
        r2.raise_for_status()
        return r2.json().get("charges", [])


async def buscar_payables_por_charge(charge_id: str) -> list[dict]:
    """Busca payables de uma charge específica."""
    headers = _auth_headers()

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(
            f"{PAGARME_API_URL}/payables",
            headers=headers,
            params={"charge_id": charge_id, "size": 100},
        )
        r.raise_for_status()
        return r.json().get("data", [])


def normalizar_payable(p: dict) -> dict:
    """Normaliza um payable da API para o formato do banco."""
    return {
        "id": str(p.get("id", "")),
        "status": p.get("status"),
        "type": p.get("type"),
        "amount": p.get("amount", 0),
        "fee": p.get("fee", 0),
        "anticipation_fee": p.get("anticipation_fee", 0),
        "payment_date": p.get("payment_date"),
        "accrual_date": p.get("accrual_at"),
        "original_payment_date": p.get("original_payment_date"),
        "installment": p.get("installment"),
        "payment_method": p.get("payment_method"),
        "fraud_coverage_fee": p.get("fraud_coverage_fee", 0),
        "gateway_id": p.get("gateway_id"),
        "charge_id": p.get("charge_id"),
        "recipient_id": p.get("recipient_id"),
        "split_id": p.get("split_id"),
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
    }
