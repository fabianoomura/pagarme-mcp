"""Formatação de valores monetários."""


def fmt(valor) -> str:
    """Formata valor em reais."""
    if valor is None:
        return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_centavos(centavos) -> str:
    """Formata centavos em reais."""
    if centavos is None:
        return "R$ 0,00"
    return fmt(centavos / 100)
