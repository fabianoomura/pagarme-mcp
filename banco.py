"""Database module — SQLite local com payables, pedidos Shopify e reembolsos."""

import sqlite3
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def criar_tabelas():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS payables (
            id                    TEXT PRIMARY KEY,
            status                TEXT,
            type                  TEXT,
            amount                INTEGER,
            fee                   INTEGER,
            anticipation_fee      INTEGER,
            payment_date          TEXT,
            accrual_date          TEXT,
            original_payment_date TEXT,
            installment           INTEGER,
            payment_method        TEXT,
            fraud_coverage_fee    INTEGER,
            gateway_id            TEXT,
            charge_id             TEXT,
            recipient_id          TEXT,
            split_id              TEXT,
            created_at            TEXT,
            updated_at            TEXT,
            synced_at             TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_payables_payment_date ON payables(payment_date);
        CREATE INDEX IF NOT EXISTS idx_payables_status ON payables(status);
        CREATE INDEX IF NOT EXISTS idx_payables_type ON payables(type);
        CREATE INDEX IF NOT EXISTS idx_payables_created_at ON payables(created_at);
        CREATE INDEX IF NOT EXISTS idx_payables_payment_method ON payables(payment_method);

        CREATE TABLE IF NOT EXISTS shopify_orders (
            order_id              INTEGER PRIMARY KEY,
            name                  TEXT,
            customer_name         TEXT,
            email                 TEXT,
            subtotal              REAL,
            desconto              REAL,
            frete                 REAL,
            total_price           REAL,
            financial_status      TEXT,
            fulfillment_status    TEXT,
            gateways              TEXT,
            payment_id            TEXT,
            charge_id             TEXT,
            cancel_reason         TEXT,
            cancelled_at          TEXT,
            refund_total          REAL DEFAULT 0,
            tags                  TEXT,
            note                  TEXT,
            created_at            TEXT,
            updated_at            TEXT,
            synced_at             TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_shopify_orders_created ON shopify_orders(created_at);
        CREATE INDEX IF NOT EXISTS idx_shopify_orders_financial ON shopify_orders(financial_status);
        CREATE INDEX IF NOT EXISTS idx_shopify_orders_payment_id ON shopify_orders(payment_id);

        CREATE TABLE IF NOT EXISTS shopify_refunds (
            refund_id             INTEGER PRIMARY KEY,
            order_id              INTEGER,
            amount                REAL,
            reason                TEXT,
            note                  TEXT,
            created_at            TEXT,
            FOREIGN KEY (order_id) REFERENCES shopify_orders(order_id)
        );

        CREATE INDEX IF NOT EXISTS idx_shopify_refunds_order ON shopify_refunds(order_id);

        CREATE TABLE IF NOT EXISTS sync_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo        TEXT,
            data_inicio TEXT,
            data_fim    TEXT,
            registros   INTEGER,
            status      TEXT,
            mensagem    TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()


def upsert_payables(payables_list):
    conn = get_connection()
    conn.executemany("""
        INSERT INTO payables (
            id, status, type, amount, fee, anticipation_fee,
            payment_date, accrual_date, original_payment_date,
            installment, payment_method, fraud_coverage_fee,
            gateway_id, charge_id, recipient_id,
            split_id, created_at, updated_at, synced_at
        ) VALUES (
            :id, :status, :type, :amount, :fee, :anticipation_fee,
            :payment_date, :accrual_date, :original_payment_date,
            :installment, :payment_method, :fraud_coverage_fee,
            :gateway_id, :charge_id, :recipient_id,
            :split_id, :created_at, :updated_at, datetime('now')
        )
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status, type = excluded.type,
            amount = excluded.amount, fee = excluded.fee,
            anticipation_fee = excluded.anticipation_fee,
            payment_date = excluded.payment_date,
            accrual_date = excluded.accrual_date,
            original_payment_date = excluded.original_payment_date,
            installment = excluded.installment,
            payment_method = excluded.payment_method,
            fraud_coverage_fee = excluded.fraud_coverage_fee,
            gateway_id = excluded.gateway_id,
            charge_id = excluded.charge_id,
            recipient_id = excluded.recipient_id,
            split_id = excluded.split_id,
            updated_at = excluded.updated_at,
            synced_at = datetime('now')
    """, payables_list)
    conn.commit()
    total = len(payables_list)
    conn.close()
    return total


def upsert_shopify_orders(orders_list):
    conn = get_connection()
    conn.executemany("""
        INSERT INTO shopify_orders (
            order_id, name, customer_name, email,
            subtotal, desconto, frete, total_price,
            financial_status, fulfillment_status, gateways,
            payment_id, charge_id, cancel_reason, cancelled_at,
            refund_total, tags, note, created_at, updated_at, synced_at
        ) VALUES (
            :order_id, :name, :customer_name, :email,
            :subtotal, :desconto, :frete, :total_price,
            :financial_status, :fulfillment_status, :gateways,
            :payment_id, :charge_id, :cancel_reason, :cancelled_at,
            :refund_total, :tags, :note, :created_at, :updated_at, datetime('now')
        )
        ON CONFLICT(order_id) DO UPDATE SET
            financial_status = excluded.financial_status,
            fulfillment_status = excluded.fulfillment_status,
            cancel_reason = excluded.cancel_reason,
            cancelled_at = excluded.cancelled_at,
            refund_total = excluded.refund_total,
            tags = excluded.tags,
            note = excluded.note,
            updated_at = excluded.updated_at,
            synced_at = datetime('now')
    """, orders_list)
    conn.commit()
    total = len(orders_list)
    conn.close()
    return total


def upsert_shopify_refunds(refunds_list):
    if not refunds_list:
        return 0
    conn = get_connection()
    conn.executemany("""
        INSERT INTO shopify_refunds (
            refund_id, order_id, amount, reason, note, created_at
        ) VALUES (
            :refund_id, :order_id, :amount, :reason, :note, :created_at
        )
        ON CONFLICT(refund_id) DO UPDATE SET
            amount = excluded.amount,
            reason = excluded.reason,
            note = excluded.note
    """, refunds_list)
    conn.commit()
    total = len(refunds_list)
    conn.close()
    return total


def registrar_sync(tipo, data_inicio, data_fim, registros, status, mensagem=""):
    conn = get_connection()
    conn.execute("""
        INSERT INTO sync_log (tipo, data_inicio, data_fim, registros, status, mensagem)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tipo, data_inicio, data_fim, registros, status, mensagem))
    conn.commit()
    conn.close()
