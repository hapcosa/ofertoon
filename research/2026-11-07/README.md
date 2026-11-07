# Revisión de tiendas antes bloqueadas

Mediciones hechas el **2026-11-06 UTC** y archivadas en el directorio
`2026-11-07` reservado por el prompt. Cada ficha incluye el estado de
`CLAUDE.md` y un comando reproducible. Los 403/520 son fotografías de esa
fecha, no conclusiones permanentes.

| Tienda | Estado | Resultado |
|---|---|---|
| [Rockford](rockford.md) | **adaptador probado** | Nuevo host oficial `rkflife.com`, 2.933 productos únicos en cuatro raíces; migración 50 escrita, no aplicada, publicación apagada. |
| [Sparta](sparta.md) | **adaptador probado** | Adaptador Magento existente; 63 llaves re-medidas, 1.208 SKUs únicos sin cruces entre categorías; migración 52 escrita, sin aplicar. |
| [Spacestore](spacestore.md) | **investigada** | Shopify en ápex; una página JSON entrega precios y stock; falta recorrer el catálogo, seleccionar llaves activas y mapearlo. |
| [Imperial](imperial.md) | **investigada** | Home 200; API OCC y categoría 520 por error de origen; re-medir. |
| [La Polar](la_polar.md) | **investigada** | Ápex con TLS expirado; `www` redirige a ABC, no catálogo independiente. |
| [Decathlon](decathlon.md), [Nice One](nice_one.md), [MTS](mts.md), [Adidas](adidas.md) | **investigadas** | Una confirmación por tienda: 403. Solicitar feed/acceso; sin evasión. |

Ninguna migración se aplicó ni se reinició un servicio desde este worktree.
