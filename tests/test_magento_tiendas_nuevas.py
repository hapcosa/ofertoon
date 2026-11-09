"""Las ocho tiendas Magento de la expansión: lo que su configuración no puede mover.

Cada aserción acá corresponde a algo **medido** (ver `INVESTIGACION_TANDA2.md` y
los docstrings de cada clase) y que si alguien "mejora" sin volver a medir, rompe
la recolección en silencio. El caso que justifica el archivo es Speedo: con los
selectores por defecto el parser **encontraba el grid, enumeraba las 33 filas y
leía el total declarado**, y emitía **cero productos** — un `enumerated` sano con
`emit=0` no lo ve ninguna guarda, porque el canario compara enumerado contra
declarado y ahí todo cierra.
"""
from __future__ import annotations

import pytest

from scrapers.stores.magento_html import (
    NAME_SELECTOR,
    SKU_SELECTOR,
    URL_SELECTOR,
    AndesgearAdapter,
    ConstrumartAdapter,
    KliperAdapter,
    KupferAdapter,
    MammutAdapter,
    MarmotAdapter,
    NewBalanceChileAdapter,
    SpartaAdapter,
    SpeedoAdapter,
    TheNorthFaceAdapter,
    TrekChileAdapter,
)

#: Las cuatro que comparten el `robots.txt` de Sparta: 87 `Disallow`,
#: `Crawl-delay: 1` y toda query string prohibida.
PLANTILLA_SPARTA = (SpartaAdapter, SpeedoAdapter, TrekChileAdapter, NewBalanceChileAdapter)

#: Las cuatro del grupo outdoor de Kliper: 17 `Disallow`, `Crawl-delay: 3`.
PLANTILLA_KLIPER = (TheNorthFaceAdapter, KliperAdapter, MammutAdapter, MarmotAdapter)

NUEVAS = PLANTILLA_SPARTA + PLANTILLA_KLIPER


@pytest.mark.parametrize("adapter", NUEVAS, ids=lambda a: a.slug)
def test_toda_tienda_nueva_declara_slug_y_host(adapter):
    assert adapter.slug
    assert adapter.base_url.startswith("https://")
    assert not adapter.base_url.endswith("/")


@pytest.mark.parametrize("adapter", NUEVAS, ids=lambda a: a.slug)
def test_ninguna_manda_product_list_limit(adapter):
    """Ninguna publica un limiter: pedir un valor sería adivinar, y uno que no
    ofrecen cae a su default sin avisar (la trampa de Kupfer con `=96`)."""
    assert adapter.page_size is None


@pytest.mark.parametrize("adapter", PLANTILLA_SPARTA, ids=lambda a: a.slug)
def test_la_plantilla_de_sparta_no_pagina_ni_sube_el_rps(adapter):
    """Su robots prohíbe `/*?` y declara `Crawl-delay: 1`.

    Prender `paginates` acá no es una mejora de cobertura: es pedir una ruta que
    la tienda prohibió.
    """
    assert adapter.paginates is False
    assert adapter.rate_limit_rps == 1.0


@pytest.mark.parametrize("adapter", PLANTILLA_KLIPER, ids=lambda a: a.slug)
def test_el_grupo_outdoor_pagina_y_respeta_su_crawl_delay(adapter):
    """`Crawl-delay: 3` ⇒ 0.33 rps. Subirlo es dejar de respetar su robots."""
    assert adapter.paginates is True
    assert adapter.rate_limit_rps == pytest.approx(0.33)
    assert adapter.max_pages == 30


@pytest.mark.parametrize("adapter", NUEVAS, ids=lambda a: a.slug)
def test_todas_deduplican_por_pasada(adapter):
    """Las ocho cross-listan: medido, la duplicación bruta va de 2,0× a 4,7×."""
    assert adapter.dedupe_across_categories is True


@pytest.mark.parametrize("adapter", (SpeedoAdapter, TrekChileAdapter), ids=lambda a: a.slug)
def test_speedo_y_trek_necesitan_sus_propios_selectores(adapter):
    """Su tema NO pone `a.product-item-link`. Ver el docstring del módulo.

    Volverlos al default deja la tienda emitiendo cero **sin un solo error**.
    """
    assert adapter.name_selector == "[data-product-sku]"
    assert adapter.url_selector == "a.product-item-photo"
    assert adapter.sku_selector == "[data-product-sku]"
    assert adapter.name_selector != NAME_SELECTOR


@pytest.mark.parametrize(
    "adapter",
    (KupferAdapter, ConstrumartAdapter, AndesgearAdapter, SpartaAdapter,
     NewBalanceChileAdapter, TheNorthFaceAdapter, KliperAdapter, MammutAdapter,
     MarmotAdapter),
    ids=lambda a: a.slug,
)
def test_las_demas_usan_los_selectores_del_tema_luma(adapter):
    """Incluidas las tres ya conectadas: este test es la regresión del cambio."""
    assert adapter.name_selector == NAME_SELECTOR
    assert adapter.url_selector == URL_SELECTOR
    assert adapter.sku_selector == SKU_SELECTOR


def test_los_slugs_son_unicos():
    slugs = [a.slug for a in NUEVAS] + [
        KupferAdapter.slug, ConstrumartAdapter.slug, AndesgearAdapter.slug
    ]
    assert len(slugs) == len(set(slugs))


def test_newbalance_no_se_conecta_dos_veces():
    """Es la única de la tanda con firma de Magento **y** de Demandware.

    Entra por Magento porque está verificado parseando. Este test no puede
    impedir que alguien la agregue también a un futuro `salesforce_family`, pero
    deja el aviso donde se va a leer.
    """
    assert NewBalanceChileAdapter.slug == "newbalance"
    assert NewBalanceChileAdapter.base_url == "https://newbalance.cl"
