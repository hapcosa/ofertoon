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


#: Largo máximo de la etiqueta del `pum`. Es el ancho de `price_points.pum_label`
#: (VARCHAR(16)): las etiquetas observadas son de 2 a 5 caracteres (`KG`, `LT`,
#: `10GR`, `100UN`), así que algo más largo que esto no es una unidad de medida y
#: no vale la pena arriesgar un error de inserción por él.
PUM_LABEL_MAX_CHARS = 16


@dataclass(frozen=True)
class Pum:
    """Precio por unidad de medida, con su unidad. Los dos juntos o ninguno.

    Es el dato que vuelve comparable una oferta de supermercado: "$3.242 el KG"
    dice algo que "−30%" no dice, y es lo que convierte un descuento en una
    decisión de comprar varias unidades (PLAN_SUPERMERCADO §2).

    **La unidad es parte del dato, no un adorno.** La tienda elige la base para
    que el número sea legible, así que `10GR` y `100UN` no son errores: son la
    base de ese producto. De ahí que label y precio vivan en el mismo objeto —
    un `pum` sin su etiqueta es un número sin significado, y dos `pum` de bases
    distintas **no se comparan entre sí** sin normalizar a una unidad común.

    No se le aplica `MAX_PLAUSIBLE_CLP` a propósito: el `pum` no es un precio que
    alguien pague, es una normalización a una base que puede ser más grande que el
    envase (un producto de una unidad con base `100UN` da un `pum` cien veces su
    precio), así que el techo de plausibilidad de un precio real no significa nada
    acá. El centinela igual queda afuera: `price_effective` se descarta antes.
    """

    label: str
    price: Decimal

    def __post_init__(self) -> None:
        if not self.label or len(self.label) > PUM_LABEL_MAX_CHARS:
            raise ValueError(f"pum_label inválido: {self.label!r}")
        if self.price <= 0:
            raise ValueError(f"pum_price fuera de rango: {self.price!r}")


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
    #: Precio por unidad de medida (`$3.242 el KG`), cuando la tienda lo declara.
    #: Opcional de verdad: lo trae el 95% del catálogo de supermercado de Tottus y
    #: ~nadie más, y **que falte no puede frenar una oferta**. No alimenta al
    #: detector —la señal sigue siendo `1 − price_today / p50_60d` y nada más—:
    #: existe para el copy.
    pum: Pum | None = None
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
