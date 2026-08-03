"""Configuração centralizada — carrega .env e expõe constantes."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

BASE_DIR = Path(__file__).parent

# Banco de dados
DB_PATH = os.getenv("PAGARME_DB_PATH", str(BASE_DIR / "pagarme.db"))

# API Pagar.me v5
PAGARME_API_URL = "https://api.pagar.me/core/v5"
PAGARME_SECRET_KEY = os.getenv("PAGARME_SECRET_KEY", "")

# Shopify Admin API
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
SHOPIFY_SHOP_URL = os.getenv("SHOPIFY_SHOP_URL", "")
SHOPIFY_API_VERSION = os.getenv("SHOPIFY_API_VERSION", "2024-01")

# Paginação
PAGE_SIZE = 1000
