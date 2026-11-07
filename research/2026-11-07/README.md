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

## Integración del 2026-11-07

El trabajo de Rockford y Sparta quedó commiteado en `feat/tiendas-bloqueadas` e
integrado en el checkout principal junto con Unimarc y MercadoPago. Las
migraciones **47, 50, 51 y 52** están escritas y en producción siguen
**pendientes** a esta fecha. La 49 queda sin archivo por decisión documentada;
no se reutiliza su número. Una aplicación de la secuencia completa sobre la
base descartable `ofertas_test_bloqueadas` creó 8 llaves de Unimarc, 4 de
Rockford y 63 de Sparta. Las tres tiendas nacieron con
`publish_enabled=false`; Hites siguió en `true` como control. También quedaron
presentes `price_points.price_condition` y la tabla de eventos de MercadoPago.

Rockford y Sparta conservan el estado **adaptador probado** hasta que una
primera ingesta real deje `scrape_runs` y `price_points`. Esa fecha será su
conexión; la evaluación de publicación corresponde 30 días observados después.
Spacestore, Imperial, La Polar, Decathlon, Nice One, MTS y Adidas siguen en
**investigada**; los límites concretos están en sus fichas. No se inició la
familia Salesforce, que era opcional si quedaba sesión.

Pendientes de operación: aplicar las cuatro migraciones desde el checkout
principal con las imágenes reconstruidas; recrear `scraper` y `publisher` para
que el primero resuelva los nuevos adaptadores y el segundo respete
`publish_enabled`; hacer una pasada `--once` y verificar los efectos en la base.
El PR de `feat/unimarc` espera autenticación de `gh` o permisos de creación en
GitHub. Activar MercadoPago además exige credenciales y plan del dueño, según
el runbook en preparación en `feat/mercadopago`; integrar la migración 51 no
inicia cobros.
