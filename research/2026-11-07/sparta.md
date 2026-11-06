# Sparta — adaptador probado; migración 52 sin aplicar

La investigación original del **2026-11-04** está en
`INVESTIGACION_deporte_outdoor.md` §1. Su barrido de 545 hojas y SKUs quedó
archivado en `sparta_barrido_2026-11-04.json`. El `robots.txt` se releyó el
**2026-11-06 16:19 UTC**: HTTP 200, `Disallow: /*?` y los listados sin query
string permitidos. `SpartaAdapter` ya existe en `magento_html`, usa 1,0 rps,
no pagina y no agrega parámetros. Fixture y tests de contrato existentes.

## Decisión de llaves

Las nueve raíces sugeridas en la investigación alcanzaban 3.157 SKUs, pero
comparten SKUs entre categorías internas. `db.load_store_targets` ordena por
slug de categoría antes que por llave, así que un producto de vestuario
compartido podría usar el θ de equipamiento (0,250 en vez de 0,350). La
migración 52 elige una primera tajada de **63 hojas**: 19 de calzado, 34 de
vestuario y 10 de máquinas de ejercicio. Se excluyen ejes de actividad que
mezclan rubros, vitrinas, accesorios ambiguos y `vestuario-deportivo/ninos`,
que compartía un SKU con dos hojas de zapatillas.

El barrido original sobre esas llaves dio 1.157 SKUs únicos y cero cruces
entre las tres categorías internas. Se re-midieron las 63 páginas el
**2026-11-06 16:19–16:21 UTC**: 1.208 SKUs únicos, 407 de calzado, 762 de
vestuario, 39 de equipamiento, **cero cruces**. El detalle por llave está en
`sparta_selected_2026-11-06.json`. La duplicación que queda es dentro de cada
categoría y la elimina `dedupe_across_categories`.

## Costo y límite

El recorrido nuevo costó **63 requests y 37.093.957 bytes de HTML
descomprimido** (37,09 MB), en aproximadamente 2,3 minutos. La tienda prohíbe
paginar: 29 de las 63 hojas declaran más productos de los 36 visibles y el
canario exacto las marcará `partial` por ese techo conocido. El sitemap
original tenía 13.448 fichas; esta tajada no es el catálogo completo.

La migración inserta `publish_enabled=false`. La fecha de conexión será la
primera ingesta real en `scrape_runs`; la aceptación se evalúa 30 días
observados después con `python -m scripts.aceptacion_tienda --store sparta`.

Reproducción desde la raíz del checkout:

```bash
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py default https://sparta.cl/robots.txt
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/sparta_audit.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_magento_html.py tests/test_magento_tiendas_nuevas.py
```
