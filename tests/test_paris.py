"""Contract test del adaptador Paris contra un fixture real.

El fixture es la respuesta del microservicio de catálogo de producción
(2026-07-31) para `group_id=tecCelSmartphones`, recortada a 6 de los 40
productos: 3 con precio Tarjeta Cencosud y 3 sin él, que es la diferencia que
más importa clasificar bien.

Se podaron del payload los campos que el parser no lee (`description`,
`attributes`, `collections`, `variants`, `warranties`, y las imágenes más allá
de la primera). Los bloques `prices`, `name`, `slug`, `brand` y `masterVariant`
están tal cual los sirvió la tienda; `total` sigue siendo el real (1108), por
eso no coincide con los 6 productos del archivo.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef
from scrapers.stores.paris import (
    NotAListingPage,
    ParisAdapter,
    parse_listing,
    resolve_prices,
)

FIXTURE = Path(__file__).parent / "fixtures" / "paris_listing_smartphones.json"
CATEGORY = CategoryRef(slug="tecno-celulares", store_key="tecCelSmartphones", label="Celulares")
NOW = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def parsed():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return parse_listing(payload, store_slug="paris", category=CATEGORY, scraped_at=NOW)


def test_extrae_todos_los_productos(parsed):
    products, total = parsed
    assert len(products) == 6
    assert total == 1108


def test_campos_obligatorios_no_nulos(parsed):
    products, _ = parsed
    for p in products:
        assert p.store_sku.isdigit()
        assert p.url.startswith("https://www.paris.cl/") and p.url.endswith(".html")
        assert p.name
        assert p.price_effective > 0
        assert p.brand
        assert p.image_url
        assert p.scraped_at == NOW


def test_precio_efectivo_ignora_la_tarjeta_cencosud(parsed):
    """`paymentMethod` es el precio con Tarjeta Cencosud: se guarda, no se compara."""
    products, _ = parsed
    redmi = next(p for p in products if p.store_sku == "422530999")
    assert redmi.price_effective == Decimal("319990")  # offer
    assert redmi.price_normal == Decimal("399990")  # regular, el "antes"
    assert redmi.price_card == Decimal("299990")  # paymentMethod / cencosudCard
    assert redmi.price_card < redmi.price_effective


def test_sin_tarjeta_el_campo_queda_vacio(parsed):
    """No todos los productos tienen precio Cencosud; inventarlo sería peor."""
    products, _ = parsed
    honor = next(p for p in products if p.store_sku == "382373999")
    assert honor.price_card is None
    assert honor.price_effective == Decimal("189990")


def test_nombre_y_slug_se_leen_del_locale(parsed):
    """`name` y `slug` son diccionarios por idioma, no strings."""
    products, _ = parsed
    honor = next(p for p in products if p.store_sku == "382373999")
    assert honor.name.startswith("Smartphone Honor 400 Smart")
    assert honor.url.endswith("-382373999.html")


def test_descuento_declarado_es_el_del_precio_sin_tarjeta(parsed):
    """`offer.discountOnRegular` es lo que rebaja a cualquiera.

    El de `paymentMethod` es mayor (25% vs 20% en este SKU) porque exige tarjeta
    Cencosud; publicarlo sobreestimaría la oferta.
    """
    products, _ = parsed
    redmi = next(p for p in products if p.store_sku == "422530999")
    assert redmi.claimed_discount == "20%"


def test_marca_normalizada(parsed):
    products, _ = parsed
    assert next(p for p in products if p.store_sku == "382373999").brand == "Honor"


def test_ean_del_listado_se_persiste_como_gtin(parsed):
    """Paris publica el EAN real en el propio listado, sin request extra.

    OJO con generalizar desde este fixture: es la PÁGINA 1, y Paris solo enriquece
    con EAN a los primeros ~60 productos del ranking de cada categoría. De ahí en
    adelante el campo viene ausente (ver el comentario en el adaptador). Que acá
    lo tengan los 6 es propiedad de la página 1, no del catálogo.
    """
    products, _ = parsed
    assert next(p for p in products if p.store_sku == "422530999").gtin == "6932554471736"
    assert all(p.gtin and len(p.gtin) == 13 for p in products)


def test_ean_multiple_se_descarta():
    """Algunos SKU traen dos EAN separados por `;` — un pack, o dos variantes.

    Elegir uno al azar aparearía el producto con el que no es. Se descarta entero:
    el criterio de `normalize_gtin` es que ante la duda no hay GTIN.
    """
    from catalog.normalize import normalize_gtin

    assert normalize_gtin("197531616067;198154422004", "756792999") is None


def test_ean_ausente_no_revienta():
    """Si Paris deja de mandar el campo, el producto igual entra sin GTIN."""
    payload = {
        "total": 1,
        "results": [
            {
                "slug": {"es-CL": "algo"},
                "name": {"es-CL": "Algo"},
                "masterVariant": {
                    "sku": "1",
                    "prices": {
                        "offer": {
                            "value": {
                                "centAmount": 9990,
                                "currencyCode": "CLP",
                                "fractionDigits": 0,
                            }
                        }
                    },
                },
            }
        ],
    }
    products, _ = parse_listing(
        payload, store_slug="paris", category=CATEGORY, scraped_at=NOW
    )
    assert len(products) == 1 and products[0].gtin is None


# --- resolve_prices ----------------------------------------------------------


def _price(amount: int, digits: int = 0, **extra):
    return {
        "value": {"centAmount": amount, "currencyCode": "CLP", "fractionDigits": digits},
        **extra,
    }


def test_resolve_prices_bloque_vacio():
    assert resolve_prices({}) == (None, None, None)


def test_resolve_prices_respeta_fraction_digits():
    """Asumir `fractionDigits: 0` multiplicaría por cien un precio con decimales."""
    effective, _, _ = resolve_prices({"offer": _price(1999900, digits=2)})
    assert effective == Decimal("19999")


def test_resolve_prices_regular_igual_a_oferta_no_es_descuento():
    effective, claimed, _ = resolve_prices(
        {"regular": _price(19990), "offer": _price(19990)}
    )
    assert effective == Decimal("19990")
    assert claimed is None


def test_resolve_prices_toma_el_menor_aunque_la_oferta_sea_mas_cara():
    """Si `offer` viniera más caro que `regular`, publicarlo sería un precio falso."""
    effective, claimed, _ = resolve_prices(
        {"regular": _price(10000), "offer": _price(12000)}
    )
    assert effective == Decimal("10000")
    assert claimed is None


def test_resolve_prices_metodo_de_pago_desconocido_se_registra(caplog):
    """Un convenio nuevo no se asume tarjeta de la casa en silencio."""
    with caplog.at_level("INFO"):
        _, _, card = resolve_prices(
            {"offer": _price(10000), "paymentMethod": _price(9000, method="otroBanco")}
        )
    assert card == Decimal("9000")
    assert "paris_metodo_pago_desconocido" in caplog.text


def test_producto_sin_precio_se_descarta():
    payload = {
        "total": 1,
        "results": [
            {
                "name": {"es-CL": "Sin precio"},
                "slug": {"es-CL": "sin-precio-1"},
                "masterVariant": {"sku": "1", "prices": {}},
            }
        ],
    }
    products, _ = parse_listing(
        payload, store_slug="paris", category=CATEGORY, scraped_at=NOW
    )
    assert products == []


def test_respuesta_sin_results_falla_ruidosamente():
    with pytest.raises(NotAListingPage):
        parse_listing({"error": "boom"}, store_slug="paris", category=CATEGORY, scraped_at=NOW)


# --- paginación --------------------------------------------------------------


def test_body_filtra_por_group_id():
    """El filtro es `group_id`; con `categories` la API devuelve el catálogo entero."""
    adapter = ParisAdapter(None, [])
    body = adapter._body(CATEGORY, 3)
    assert body["filters"] == [
        {"key": "group_id", "stringValues": ["tecCelSmartphones"]}
    ]
    assert body["pagination"] == {"page": 3, "pageSize": 40}


@pytest.mark.asyncio
async def test_pagina_1_vacia_es_error_de_configuracion():
    """Un `group_id` inexistente devuelve `results: []` con HTTP 200.

    Sin este guard, una categoría mal escrita se vería idéntica a una categoría
    sin ofertas: cero productos y ningún error.
    """
    vacio = json.dumps({"total": 0, "results": []})

    class _Http:
        async def post_json(self, url, payload, **kw):
            return vacio

    adapter = ParisAdapter(_Http(), [])
    with pytest.raises(NotAListingPage):
        async for _ in adapter.discover(CATEGORY):
            pass


@pytest.mark.asyncio
async def test_lista_vacia_despues_de_la_pagina_1_es_fin_de_catalogo():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["total"] = 999  # fuerza a pedir la página 2
    primera = json.dumps(payload)
    vacio = json.dumps({"total": 0, "results": []})

    class _Http:
        def __init__(self):
            self.calls = 0

        async def post_json(self, url, payload, **kw):
            self.calls += 1
            return primera if self.calls == 1 else vacio

    http = _Http()
    adapter = ParisAdapter(http, [])
    productos = [p async for p in adapter.discover(CATEGORY)]
    assert len(productos) == 6
    assert http.calls == 2  # cortó al primer vacío, no siguió hasta max_pages
