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
