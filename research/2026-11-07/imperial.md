# Imperial — investigada; fuente inestable

**Medido el 2026-11-06 UTC.** `https://imperial.cl/` con
`BROWSER_HEADERS` respondió 200 (redirección a `www`, 461.363 bytes, firma
`occ-public` de Oracle Commerce Cloud). Pero la API pública de storefront no
estuvo disponible: `https://www.imperial.cl/ccstore/v1/collections` y
`/ccstore/v1/products` respondieron **520** con error JSON de Cloudflare
`unknown_origin_error`, `error_category=origin`, `retryable=true` y
`owner_action_required=true`. La página de categoría
`/herramientas-de-banco/category/14341` también dio 520.

Esto reafirma y precisa la corrección de `TIENDAS_PROHIBIDAS.md`: **no es un
403 duro de Akamai para toda la tienda**. El acceso a la home funciona con
headers del proyecto; el bloqueo actual para una ingesta estable es el **origen
de las rutas de catálogo**. No se escribe `occ_family` sobre una API que no
entrega un catálogo reproducible. Tampoco se cambia el UA o TLS para tapar 520.
Las preguntas de paginación, stock, precio, GTIN y cobertura siguen abiertas.

Reproducir:

```bash
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py browser https://imperial.cl/
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py browser_json https://www.imperial.cl/ccstore/v1/collections
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py browser_json https://www.imperial.cl/ccstore/v1/products
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py browser https://www.imperial.cl/herramientas-de-banco/category/14341
```

Re-medir en otra sesión. Un 520 tiene fecha, no convierte la tienda en
prohibida de forma permanente.
