"""Contract test de Unimarc contra payload real.

Los tres fixtures son el `__NEXT_DATA__` que sirve `unimarc.cl/category/...`,
capturado el 2026-11-06 con la cookie `co_sc=39` —el canal del visitante
anónimo—, con los productos verbatim. Cada uno existe por un motivo que el
camino feliz no ejercita:

* `unimarc_lacteos_p1.html`: los casos de precio que el adaptador decide (Club
  con descuento, Club con promo de multicompra, `Exclusivo .cl`, sin etiqueta) y
  las tres bases de `ppum`.
* `unimarc_lacteos_p15.html`: la última página de la llave, con el bloque
  `notAvailableProducts`. Su agotado viene con **precio 0** y etiqueta
  `Pronto disponible`. Es la moraleja del caso `isOutOfStock` de la familia
  Falabella: un lector de stock se prueba contra lo agotado, no contra lo que
  está a la venta.
* `unimarc_bebidas_p20_diamante.html`: la etiqueta `Diamante` sobre un precio
  **igual** al de lista, con un control sin etiqueta al lado. Es el falso
  positivo que haría publicar "Requiere Diamante" sobre un vino que no está en
  oferta.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from scrapers.base import CategoryRef, RawProduct, StoreAdapter
from scrapers.stores.unimarc import (
    PAGE_SIZE,
    SALES_CHANNEL,
    NotAListingPage,
    UnimarcAdapter,
    listing_data,
    parse_product,
    parse_promo,
    parse_pum,
)

FIXTURES = Path(__file__).parent / "fixtures"
LACTEOS_P1 = FIXTURES / "unimarc_lacteos_p1.html"
LACTEOS_P15 = FIXTURES / "unimarc_lacteos_p15.html"
BEBIDAS_P20 = FIXTURES / "unimarc_bebidas_p20_diamante.html"

LACTEOS = CategoryRef(
    slug="supermercado", store_key="lacteos-huevos-y-refrigerados", label="Supermercado"
)
BEBIDAS = CategoryRef(slug="supermercado", store_key="bebidas-y-licores", label="Supermercado")
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def _productos(path: Path, category: CategoryRef = LACTEOS) -> dict[str, RawProduct]:
    """Los productos del fixture, por `store_sku`. Incluye los agotados."""
    _, _, disponibles, agotados = listing_data(path.read_text(encoding="utf-8"))
    salida = {}
    for items, in_stock in ((disponibles, True), (agotados, False)):
        for item in items:
            producto = parse_product(
                item, category=category, in_stock=in_stock, scraped_at=NOW
            )
            if producto is not None:
                salida[producto.store_sku] = producto
    return salida


@pytest.fixture(scope="module")
def pagina1():
    return _productos(LACTEOS_P1)


@pytest.fixture(scope="module")
def pagina15():
    return _productos(LACTEOS_P15)


@pytest.fixture(scope="module")
def bebidas():
    return _productos(BEBIDAS_P20, BEBIDAS)


# --- El contrato -------------------------------------------------------------

def test_cumple_el_protocolo():
    assert isinstance(UnimarcAdapter(None, [LACTEOS]), StoreAdapter)


def test_no_declara_completeness():
    """No implementa el canario exacto a propósito: tres de las ocho llaves
    quedan una entrada cortas del total que la tienda declara, de forma
    inestable. Ver el docstring de la clase."""
    assert not hasattr(UnimarcAdapter(None, [LACTEOS]), "completeness")


def test_lee_el_total_declarado_y_la_pagina_servida():
    pagina, total, disponibles, agotados = listing_data(
        LACTEOS_P1.read_text(encoding="utf-8")
    )
    assert (pagina, total) == (1, 719)
    assert len(disponibles) == 7 and agotados == []


def test_una_pagina_que_no_es_listado_falla_ruidosamente():
    """El fallo silencioso es el que importa: sin esto una página de error
    entraría como catálogo vacío y la llave se vería 'sana' con 0 productos."""
    with pytest.raises(NotAListingPage):
        listing_data("<html><body>Página no encontrada</body></html>")
    with pytest.raises(NotAListingPage):
        listing_data('<html><script id="__NEXT_DATA__">{"props":{}}</script></html>')


# --- Precio, condición y las etiquetas que NO son condiciones ----------------

def test_club_con_descuento_declara_la_condicion(pagina1):
    """El precio Club es `price_effective` —ser Club es dar el RUT, decisión del
    dueño del 2026-11-05— pero el copy tiene que decir que hay que serlo."""
    leche = pagina1["2896"]
    assert leche.price_effective == Decimal(1190)
    assert leche.price_normal == Decimal(1350)
    assert leche.price_card is None
    assert leche.price_condition == "Club Unimarc"
    assert leche.gtin == "7802920777542"
    assert leche.pum.label == "litro" and leche.pum.price == Decimal(1190)


def test_sin_etiqueta_no_hay_condicion_que_declarar(pagina1):
    tazon = pagina1["97541"]
    assert tazon.price_effective == Decimal(1490)
    assert tazon.price_condition is None
    # Precio igual al de lista: no hay "antes" que creer.
    assert tazon.price_normal is None


def test_diamante_no_es_una_condicion_de_compra(bebidas):
    """`Diamante` es un sello del vino sobre un precio igual al de lista.

    Es el caso de control de `_condicion`: la etiqueta existe y el filtro NO la
    emite, porque no condiciona ningún precio. Sin esto el canal publicaría
    "Requiere Diamante" sobre un vino que cuesta lo de siempre."""
    for sku in ("3965", "14086"):
        vino = bebidas[sku]
        assert vino.price_effective == Decimal(7790)
        assert vino.price_condition is None, "Diamante no condiciona el precio"
    # Y el control de al lado, sin etiqueta, se comporta igual.
    assert bebidas["98283"].price_condition is None


def test_el_agotado_de_precio_cero_no_se_emite(pagina15):
    """Los agotados de Unimarc vienen con precio 0 y etiqueta `Pronto
    disponible`. Un 0 no es un precio: se enumera y no se emite, igual que las
    filas sin stock de Construmart. Lo que no puede pasar es que entre como
    observación de $0 y arrastre el p50 del SKU a cero para siempre."""
    assert "99062" not in pagina15
    # El resto de la página sí entra: el descarte es del agotado, no de la página.
    assert len(pagina15) == 18


def test_pronto_disponible_nunca_llega_como_condicion(pagina15):
    """Ni por la puerta de atrás: ningún producto emitido de la última página
    lleva un estado de stock en el campo de la condición."""
    assert all(p.price_condition != "Pronto disponible" for p in pagina15.values())


# --- La promoción de multicompra ---------------------------------------------

def test_promo_de_multicompra_con_el_unitario_sin_condicion_en_la_serie(pagina1):
    """El caso que motivó la migración 46: el unitario NO baja (600 = 600) y
    todo el ahorro está en comprar 2."""
    yoghurt = pagina1["6189"]
    assert yoghurt.price_effective == Decimal(600), "la serie guarda el unitario"
    assert yoghurt.promo.qty == 2
    assert yoghurt.promo.total == Decimal(1000)
    assert yoghurt.promo.label == "2 x $1.000"
    assert yoghurt.promo.unitario == Decimal(500)
    # La condición sigue viajando: la promo es Club.
    assert yoghurt.price_condition == "Club Unimarc"


def test_promo_de_cuatro_con_unitario_no_entero(pagina1):
    """`4 x $2.360` da 590 justo, pero `4 x $1.150` daría 287,5: lo que se
    persiste son `qty` y `total` enteros y el unitario queda derivado."""
    yoghurt = pagina1["41643"]
    assert yoghurt.promo.qty == 4
    assert yoghurt.promo.total == Decimal(2360)
    assert yoghurt.price_condition == "Exclusivo .cl"


@pytest.mark.parametrize(
    "mensaje, qty, esperado",
    [
        ("4 x $1.150", 4, (4, Decimal(1150))),   # el punto es separador de miles
        ("2 x $1.000", 2, (2, Decimal(1000))),
        ("3 x $990", 3, (3, Decimal(990))),
    ],
)
def test_parse_promo_lee_el_texto_de_la_tienda(mensaje, qty, esperado):
    promo = parse_promo(
        {
            "priceDetail": {"itemsRequiredForPromotion": qty},
            "promotion": {"descriptionMessage": mensaje, "price": float(esperado[1]) / qty},
        }
    )
    assert (promo.qty, promo.total) == esperado
    assert promo.label == mensaje


@pytest.mark.parametrize(
    "item",
    [
        # Las unidades del texto y las que declara el campo no coinciden: una de
        # las dos está mal y no se sabe cuál.
        {"priceDetail": {"itemsRequiredForPromotion": 3},
         "promotion": {"descriptionMessage": "4 x $1.000", "price": 250.0}},
        # El unitario que declara la tienda no cuadra con qty × total.
        {"priceDetail": {"itemsRequiredForPromotion": 4},
         "promotion": {"descriptionMessage": "4 x $1.000", "price": 500.0}},
        # Una promo de una unidad no es multicompra, es el precio.
        {"priceDetail": {"itemsRequiredForPromotion": 1},
         "promotion": {"descriptionMessage": "1 x $1.000", "price": 1000.0}},
        # Formato que no reconocemos: no se adivina.
        {"priceDetail": {"itemsRequiredForPromotion": 2},
         "promotion": {"descriptionMessage": "Lleva 2 y paga 1", "price": 500.0}},
        # Sin promo declarada.
        {"priceDetail": {}, "promotion": {}},
    ],
)
def test_promo_que_no_cuadra_no_se_emite(item):
    """Ante la duda no se emite promo: el producto entra con su precio unitario,
    que es lo que de verdad paga quien compra una. Publicar un ahorro mal leído
    es publicar una oferta falsa."""
    assert parse_promo(item) is None


# --- El precio por unidad de medida ------------------------------------------

@pytest.mark.parametrize(
    "texto, label, price",
    [
        ("$1.190 x litro", "litro", Decimal(1190)),
        ("$10.000 x Kg", "Kg", Decimal(10000)),
        ("$309 x unidad", "unidad", Decimal(309)),
    ],
)
def test_parse_pum_las_tres_bases_observadas(texto, label, price):
    pum = parse_pum(texto)
    assert (pum.label, pum.price) == (label, price)


@pytest.mark.parametrize(
    "texto",
    ["", None, "1.190 x litro", "$1.190", "$1.190 x " + "u" * 20],
)
def test_pum_ilegible_no_frena_el_producto(texto):
    """El `pum` es copy, no señal: lo que no se entiende se descarta, y el
    producto entra igual. Una etiqueta truncada sería una unidad equivocada."""
    assert parse_pum(texto) is None


def test_el_pum_sale_del_precio_publicado_y_no_del_tachado(pagina1):
    """`sellers[0].ppum` es el del precio que se publica; el de
    `priceDetail.ppumListPrice` es el precio por kilo de un precio que ya no
    existe."""
    mantequilla = pagina1["84289"]
    assert mantequilla.price_effective == Decimal(2000)
    assert mantequilla.pum.price == Decimal(10000) and mantequilla.pum.label == "Kg"


# --- El canal de venta -------------------------------------------------------

@pytest.mark.asyncio
async def test_toda_request_fija_el_canal_de_venta():
    """El precio de Unimarc depende del `salesChannel` y el canal del anónimo es
    el 39 (medido el 2026-11-06: con `co_sc=1` cambia el precio, con `co_sc=40`
    cambia el surtido). Si una request sale sin fijarlo, la serie de la tienda
    mezcla dos canales — el caso Construmart."""
    pedidas = []

    class FakeHttp:
        async def get_text(self, url, *, rps=None, headers=None):
            pedidas.append((url, headers))
            # El fixture es la página 15; se renumera para que el payload diga la
            # que se pidió, que es lo que la tienda real hace.
            pagina = len(pedidas)
            return LACTEOS_P15.read_text(encoding="utf-8").replace(
                '"page":15', f'"page":{pagina}'
            )

    adapter = UnimarcAdapter(FakeHttp(), [LACTEOS])
    [p async for p in adapter.discover(LACTEOS)]

    assert pedidas, "no pidió ninguna página"
    for url, headers in pedidas:
        assert headers.get("Cookie") == f"co_sc={SALES_CHANNEL}"


@pytest.mark.asyncio
async def test_si_la_tienda_sirve_otra_pagina_falla_en_vez_de_recorrer_la_misma():
    """La página servida viene en el propio payload. Si se ignora, paginar es
    recorrer la 1 en loop y cada pasada pesaría 50 veces el mismo precio."""

    class SiempreLaUno:
        async def get_text(self, url, *, rps=None, headers=None):
            return LACTEOS_P1.read_text(encoding="utf-8")

    adapter = UnimarcAdapter(SiempreLaUno(), [LACTEOS])
    with pytest.raises(NotAListingPage, match="sirvió"):
        [p async for p in adapter.discover(LACTEOS)]


@pytest.mark.asyncio
async def test_no_repite_un_sku_dentro_de_la_llave():
    """La paginación de la tienda puede repetir entradas entre páginas; un SKU
    emitido dos veces en la misma pasada pesa doble en su propio p50."""

    class DosVecesLaMisma:
        def __init__(self):
            self.n = 0

        async def get_text(self, url, *, rps=None, headers=None):
            self.n += 1
            # Devuelve la 15 siempre, pero diciendo que es la página pedida.
            texto = LACTEOS_P15.read_text(encoding="utf-8")
            return texto.replace('"page":15', f'"page":{self.n}')

    adapter = UnimarcAdapter(DosVecesLaMisma(), [LACTEOS])
    emitidos = [p.store_sku async for p in adapter.discover(LACTEOS)]
    assert len(emitidos) == len(set(emitidos))


def test_la_identidad_del_listing_es_el_sku_de_la_tienda(pagina1):
    """No el `productId` ni el `itemId` de VTEX: `sku` es lo que la ficha usa.
    Acá no hay talles, así que no se repite el problema de `vtex_family`, donde
    la identidad es el talle y cambia de pasada a pasada."""
    leche = pagina1["2896"]
    assert leche.store_sku == "2896"
    assert leche.url == "https://www.unimarc.cl/leche-entera-natural-colun-sin-tapa-1-l-2/p"
    assert leche.category_path == "lacteos-huevos-y-refrigerados"


def test_el_tamano_de_pagina_es_el_de_la_tienda():
    assert PAGE_SIZE == 50
