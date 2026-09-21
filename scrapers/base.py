"""Contrato común de los adaptadores de tienda.

Agregar una tienda = un módulo en `scrapers/stores/` que implemente `StoreAdapter`
+ un fixture en `tests/fixtures/` + una fila en la tabla `stores`. Nada más se toca.

Todo lo específico de una tienda vive en su adaptador; el runner, la persistencia
y el detector solo conocen `RawProduct`.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable


#: Techo de plausibilidad para un precio en CLP. Falabella publica productos sin
#: precio real con el centinela $99.999.999.999; un valor así desborda la columna
#: y, peor, envenenaría la baseline del SKU de forma permanente. Cualquier cosa
#: por encima de este techo NO es un precio: es un placeholder de la tienda.
MAX_PLAUSIBLE_CLP = Decimal("100000000")


@dataclass(frozen=True)
class CategoryRef:
    """Categoría de una tienda, tal como la tienda la identifica.

    `slug` es nuestra taxonomía interna (la que mapea a canales VIP); `store_key`
    es lo que la tienda entiende (un categoryId, un término de búsqueda, un path).
    """

    slug: str
    store_key: str
    label: str | None = None


@dataclass(frozen=True)
class ListingRef:
    """Puntero a un SKU dentro de una tienda."""

    store_sku: str
    url: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawProduct:
    """Producto normalizado, listo para persistir.

    Los tres precios chilenos se guardan por separado a propósito. La regla del
    sistema (§Decisión de precio efectivo) es:

        price_effective  → el que paga cualquiera, SIN plástico de la tienda
        price_card       → precio con tarjeta propia; se MUESTRA, no se compara
        price_normal     → el "antes" tachado que declara la tienda; NO se cree

    El detector solo mira `price_effective`. `price_normal` se guarda para poder
    medir a posteriori cuánto miente cada tienda, no para calcular descuentos.
    """

    store_slug: str
    store_sku: str
    url: str
    name: str
    price_effective: Decimal
    scraped_at: datetime
    in_stock: bool = True
    brand: str | None = None
    model: str | None = None
    gtin: str | None = None
    category_path: str | None = None
    price_normal: Decimal | None = None
    price_card: Decimal | None = None
    image_url: str | None = None
    #: Descuento que la tienda declara ("-22%"). Se guarda solo como evidencia
    #: para contrastarlo contra el descuento real; nunca alimenta el detector.
    claimed_discount: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0 < self.price_effective <= MAX_PLAUSIBLE_CLP:
            raise ValueError(
                f"{self.store_slug}/{self.store_sku}: price_effective fuera del rango "
                f"(0, {MAX_PLAUSIBLE_CLP}], llegó {self.price_effective!r}"
            )


@runtime_checkable
class StoreAdapter(Protocol):
    """Lo que cada tienda debe implementar."""

    slug: str
    #: Techo de requests por segundo. Conservador por diseño: el sistema hace dos
    #: pasadas diarias, no necesita velocidad, necesita no ser bloqueado.
    rate_limit_rps: float

    def categories(self) -> Sequence[CategoryRef]:
        """Categorías que esta tienda alimenta, en la taxonomía interna."""
        ...

    async def discover(self, category: CategoryRef) -> AsyncIterator[RawProduct]:
        """Enumera los productos de una categoría, paginando internamente.

        Las tiendas que renderizan el listado server-side (Falabella, Sodimac)
        devuelven el producto completo acá y no necesitan `fetch`. Las que solo
        exponen un índice devuelven productos parciales y se completan con `fetch`.
        """
        ...


@runtime_checkable
class DetailAdapter(Protocol):
    """Opcional: tiendas cuyo listado no trae precio y hay que abrir la ficha."""

    async def fetch(self, refs: Sequence[ListingRef]) -> list[RawProduct]:
        ...


@runtime_checkable
class CountingAdapter(Protocol):
    """Opcional: tiendas cuya API declara cuántos productos tiene la categoría.

    Cuando existe, el runner reemplaza el canario estadístico por una
    verificación **exacta** de completitud. Si la tienda dice 74 y la paginación
    enumeró 74, la corrida está completa por definición y ninguna mediana puede
    decir lo contrario — que es justo el falso positivo que SP Digital produjo
    durante días cuando su stock cayó de golpe el 28 de agosto.

    Cuenta entradas **enumeradas por la paginación**, no productos emitidos: un
    ítem que el parser descarta por no traer precio es una decisión nuestra, no
    una página que se perdió. Mezclarlos convertiría esta guarda exacta en otra
    heurística.
    """

    def completeness(self, category: CategoryRef) -> tuple[int, int] | None:
        """`(enumerados, declarados)` de la última corrida, o `None` si no se sabe."""
        ...
