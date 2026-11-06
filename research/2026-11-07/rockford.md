# Rockford — adaptador probado; ingesta aún no activa

**Medido el 2026-11-06 UTC.** La conclusión anterior de `TIENDAS_PROHIBIDAS.md`
(`rockford.cl` con TLS defectuoso) sigue cierta para **ese dominio**, pero ya no
describe el catálogo vigente: la tienda oficial Rockford Chile en
`https://www.rkflife.com/` responde 200, TLS verificado, y sirve Shopify.
`https://www.rockford.cl/` todavía falla con `CERTIFICATE_VERIFY_FAILED`
(cadena/issuer). No se bajó la verificación ni se la necesita.

| Pregunta de `PLAN_EXPANSION.md` §1 | Evidencia y decisión |
|---|---|
| 1. Plataforma | HTML de `rkflife.com` con firma Shopify; `/collections/{handle}/products.json` sirve JSON público. |
| 2. Robots | `https://www.rkflife.com/robots.txt` 200, `Allow: /`; prohíbe carrito, cuenta, filtros, no las colecciones usadas. No se observó `Crawl-delay`. Se fija 0,5 rps conservador. |
| 3. Headers | En `rockford_headers.ndjson`, misma URL, 4 intentos/juego: `DEFAULT_USER_AGENT` **200×4**; `BROWSER_USER_AGENT` **429×4**; `BROWSER_HEADERS` **403,403,200,403**. El adaptador conserva el UA identificable por defecto. |
| 4. Paginación | `?limit=250&page=N`; 5/3/3/3 páginas con productos en las cuatro llaves, siguiente página vacía (`products: []`). Primera página vacía es error de llave, probado en contrato. |
| 5. Orden | Dos recorridos completos de `hombre-vestuario`: 1.090 IDs idénticos, Jaccard 1,0000. `rkflife_hombre-vestuario_ids_first.json` y `rkflife_hombre-vestuario_ids.json`. |
| 6. Total | No hay total de categoría fiable en `products.json`; fin por lista vacía y cobertura por IDs observados. No se presenta un canario exacto ficticio. |
| 7. GTIN | 0 de 16.962 variantes de las cuatro raíces traen `barcode`. No se inventa identidad cross-store. |
| 8. Precio tachado | `compare_at_price` existe en parte de las variantes (3.685 de 5.184 en `hombre-vestuario`); se guarda como evidencia, no alimenta el descuento real. |
| 9. Stock | `variants[].available` verdadero/falso. Hombre-vestuario: 3.199 talles disponibles, 1.985 agotados, 651 productos mixtos y 1 enteramente agotado. Fixture real cubre mixto y agotado. |
| 10. Centinelas | Rango medido de las cuatro raíces: $9.995–$379.990; ninguno supera `MAX_PLAUSIBLE_CLP`. No se observaron centinelas en esta tajada. |
| 11. Llaves | Son raíces de navegación, no vitrinas `-off`: `hombre-vestuario` y `mujer-vestuario` → `ropa-vestuario`; `calzado-hombre` y `calzado-mujer` → `ropa-calzado`. Un ID compartido entre los dos vestuarios, **cero cruces entre categorías internas**, 2.933 IDs únicos. Deduplicación en la pasada. No se agregan llaves promocionales sin re-medir. |
| 12. Costo | 1.090 + 708 + 530 + 606 = 2.934 filas de producto, 2.933 únicas; 16.962 variantes. Adaptador: 18 requests/pasada (14 páginas con filas, 4 finales vacías), 18.256.001 bytes de cuerpo JSON descomprimido (18,26 MB / 17,41 MiB), ~36 s a 0,5 rps, ~2.933 observaciones. |

Los cuatro archivos `rkflife_*_ids.json` se obtuvieron enumerando cada llave y
`compare_ids.py` calculó las intersecciones. Ninguna de las 2.934 filas tenía
precios distintos entre talles, así que se emite una observación por producto;
la variante elegida es la disponible más barata. `vendor=rockfordcl` aparece
incluso en un polar **Columbia** agotado; se descarta como marca. La serie usa el
ID de producto Shopify. Las colecciones `-off` no entran porque son vitrinas.

La segunda medición completa del 2026-11-06 15:30–15:31 UTC sumó
6.497.514 bytes en `hombre-vestuario`, 4.163.182 en `mujer-vestuario`,
3.699.974 en `calzado-hombre` y 3.895.331 en `calzado-mujer`. Cada recorrido
terminó en una página vacía. `shopify_audit.py` informa `response_bytes` y
`decoded_body_bytes` y `complete` para reproducir el costo y el fin del catálogo.

Reproducción desde este worktree, con TLS verificado y pausas de 1,5 s:

```bash
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py default https://www.rockford.cl/
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py default https://www.rkflife.com/robots.txt
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/shopify_audit.py list https://www.rkflife.com
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/shopify_audit.py collection https://www.rkflife.com hombre-vestuario
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/shopify_audit.py collection https://www.rkflife.com mujer-vestuario
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/shopify_audit.py collection https://www.rkflife.com calzado-hombre
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/shopify_audit.py collection https://www.rkflife.com calzado-mujer
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/compare_ids.py research/2026-11-07/rkflife_hombre-vestuario_ids.json research/2026-11-07/rkflife_mujer-vestuario_ids.json research/2026-11-07/rkflife_calzado-hombre_ids.json research/2026-11-07/rkflife_calzado-mujer_ids.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python -m pytest -p no:cacheprovider -q tests/test_rockford.py tests/test_shopify_family.py
```

El módulo, fixture y contrato están probados. `migrations/50_rockford_rkflife.sql`
queda **escrita, sin aplicar**, con `publish_enabled=false` para acumular
historial cuando se despliegue. La fecha de conexión será la de la primera
ingesta real; evaluar 30 días observados después, antes de habilitar publicación.
La tajada de cuatro raíces no equivale al catálogo completo de RKF Life.
