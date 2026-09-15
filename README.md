# Pagar.me MCP Server

MCP Server para financeiro Pagar.me v5 + Shopify. Consulta recebiveis, fluxo de caixa, conciliacao e dados de pedidos.

## Escopo definido para o Brain

**Pagar.me é somente consulta.** Reembolsos e antecipações são informações consultadas,
não operações executadas pelo conector. A conciliação analisa dados; as rotinas de
sincronização atualizam apenas o SQLite local com dados das APIs. Não adicionar
movimentações financeiras a este escopo. Limites de escrita financeira do Brain
se aplicam aos conectores que efetivamente executam essas operações.

## Tools Disponiveis

| Tool | Descricao |
|------|-----------|
| `recebiveis_periodo` | Recebiveis agrupados por dia (bruto, taxas, liquido) |
| `fluxo_pedido` | Parcelas de um pedido especifico com datas de recebimento |
| `fluxo_caixa` | Entradas, saidas, taxas e liquido por dia |
| `conciliar_dia` | Conciliacao Shopify x Pagar.me de um dia |
| `resumo_financeiro` | Resumo com quebra por metodo de pagamento |
| `buscar_pedido` | Info do pedido: cliente, valores, status, reembolsos |
| `sincronizar` | Atualiza banco local com dados das APIs |
| `listar_reembolsos` | Pedidos reembolsados num periodo |

## Instalacao

```bash
cd C:/Users/mooui/mcp-servers/pagarme-mcp
pip install mcp httpx python-dotenv
```

## Configuracao

Copiar `.env.example` para `.env` e preencher:

```
PAGARME_SECRET_KEY=sk_xxx
SHOPIFY_ACCESS_TOKEN=shpat_xxx
SHOPIFY_SHOP_URL=sua-loja.myshopify.com
PAGARME_DB_PATH=c:/projetos_code/pagar.me/pagarme.db
```

## Registrar no Claude Desktop/Code

Adicionar ao `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "pagarme": {
      "command": "python",
      "args": ["C:/Users/mooui/mcp-servers/pagarme-mcp/server.py"]
    }
  }
}
```

## Uso

Uma vez registrado, o Claude pode responder perguntas como:

- "O que tenho pra receber essa semana?"
- "Qual o fluxo do pedido #14328?"
- "Concilia as vendas de ontem"
- "Quanto paguei de taxa esse mes?"
- "Lista os reembolsos de maio"

## Arquitetura

```
server.py          → Servidor MCP (stdio)
db.py              → Consultas ao SQLite local (offline)
pagarme_client.py  → Chamadas a API Pagar.me e Shopify (quando necessario)
```

O servidor prioriza consultas locais (banco SQLite). So acessa as APIs quando:
- Dados nao estao no banco (fallback)
- Conciliacao em tempo real (precisa do Shopify)
- Sincronizacao solicitada
