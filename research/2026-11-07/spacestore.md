# Spacestore — investigada; fuente de precios parcial, sin adaptador

**Medido el 2026-11-06 UTC.** El `www` había dado 403 y causó el descarte
antiguo; el ápex `https://spacestore.cl/` entrega un sitemap Shopify y el
catálogo público por **colección**. `https://spacestore.cl/sitemap.xml`
respondió 200, con 64 sitemaps (60 de productos y uno de colecciones). No hay
que contar los 2.003 `<loc>` del primer sitemap como productos: incluyen URLs
de imágenes. `robots.txt` respondió 200, permite `/`, sin `Crawl-delay`
observado; prohíbe carrito/cuenta/filtros, no la colección medida.

`/products.json` de raíz había dado 403, pero
`/collections/all/products.json?limit=250&page=1` dio **200 JSON**, 250
productos, 269 variantes, 248 disponibles y 21 agotadas. Rango de precio
$14.990–$573.990; dos productos con spread entre variantes; cero barcodes.
El archivo `spacestore_all_ids.json` conserva los 250 IDs. El sitemap enumeró
431 colecciones en `spacestore_collections.txt`, pero varias rutas temáticas
probadas (`belleza`, `audifonos`, `peluches`) devolvieron `products: []`: un
handle en el sitemap **no demuestra una llave de catálogo activa**. Una ficha
pedida en paralelo con el sitemap dio 429; no permite inferir un bloqueo
persistente y no se repitió.

La fuente tiene precios reales, pero falta recorrer `all` completo, medir
estabilidad de orden, elegir llaves de navegación activas y decidir la taxonomía
de su mezcla de merchandising, juguetes y accesorios. Por eso queda en
**investigada**, sin módulo ni migración. La fuente de precios está comprobada
en una página, pero el catálogo no está recorrido entero. La corrección respecto
del 403 heredado está medida en la ruta correcta del ápex.

Reproducir:

```bash
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py default https://spacestore.cl/robots.txt
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/shopify_audit.py list https://spacestore.cl
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/shopify_audit.py collection https://spacestore.cl all --max-pages 1
```

## Recorrido adicional 2026-11-07 22:55–23:00 UTC

`/collections/all/products.json?limit=250&page=100` todavía entrega 250 filas;
`page=200` devuelve **400**: `Page * Limit exceeds the 25000 limit`.
Por lo tanto, `all` no puede certificar el catálogo completo con esa ruta.
No se debe tratar la página 100 como fin normal.
El índice tiene 60 sitemaps de productos. `spacestore_sitemap_count.py`
recorrió los 60 con pausa de 1,5 s y contó **59.650 entradas `<url>` de
producto** (27,43 MB de XML); las entradas de imagen `<loc>` no se contaron.
`spacestore_sitemap_counts.json` guarda el conteo por archivo. El sitemap
enumera URLs, pero no precios, stock ni la pertenencia disjunta a categorías.

Se recorrieron hasta página vacía tres colecciones de tipo de producto. Los
archivos `spacestore_*_ids.json` conservan los IDs reales:

| Llave | Productos | Variantes | Páginas con datos + final vacío | Bytes decodificados | Precio mínimo–máximo | Sin barcode | Stock |
|---|---:|---:|---:|---:|---:|---:|---|
| `tazones` | 386 | 404 | 2 + 1 | 847.937 | $18.990–$145.990 | 404/404 | 9 variantes agotadas, 4 productos mixtos |
| `funko-pop` | 266 | 266 | 2 + 1 | 526.288 | $33.990–$132.990 | 266/266 | 8 productos agotados |
| `calcetines` | 639 | 704 | 3 + 1 | 1.543.350 | $14.990–$275.990 | 704/704 | 24 variantes agotadas, 24 productos mixtos |

Las tres llaves suman **1.291 IDs distintos**, con intersección cero en cada
par. `tazones` y `funko-pop` se recorrieron dos veces: Jaccard de IDs **1,0000**
en ambos casos. `compare_at_price` apareció en 24, 19 y 10 variantes,
respectivamente; queda como dato declarado, nunca como baseline.

`poleras`, `polerones`, `polerones-licenciados`, `poleras-tematicas`,
`camiseta`, `disfraces`, `figuras-coleccionables`, `ropa`, `belleza` y `juguetes`
están en el sitemap pero dieron primera página vacía. Esto impide inferir
cobertura de ropa o juguetes a partir del nombre de un handle. `tazones` y
`funko-pop` necesitarían categorías internas nuevas para no mezclarse con
electrodomésticos o ropa. Esta tajada comprueba catálogo y disyunción, pero no
cubre el resto de la tienda ni justifica aún una migración.

Reproducir las tres colecciones con `shopify_audit.py collection
https://spacestore.cl HANDLE --max-pages 20` y cruzar sus archivos con
`compare_ids.py`. El User-Agent usado fue `DEFAULT_USER_AGENT`, con TLS
verificado y pausa de 1,5 s entre páginas.
