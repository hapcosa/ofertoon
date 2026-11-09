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

## Continuación del 2026-11-07

| Frente | Estado | Hallazgo nuevo |
|---|---|---|
| [Tricot y ABC](salesforce.md) | **investigadas** | Tricot prohíbe hoy `?start` en robots; ABC permite la ruta limpia con zona fijada, pero el listado no expone stock y el total declarado difiere en dos del recorrido completo. Sin migración 54. |
| [Imperial](imperial.md) | **investigada** | Home 200/200; API de colecciones 520/520, productos 520 y categoría 520/520. |
| [Spacestore](spacestore.md) | **fuente comprobada parcial** | Sitemap: 59.650 URLs de producto; `all` topa en 25.000. Tres colecciones pequeñas completas suman 1.291 IDs disjuntos. Falta partición exhaustiva y categorías internas apropiadas. |

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
La suite completa del checkout integrado terminó con **982 tests aprobados**
contra esa base descartable el 2026-11-07. Se construyeron las imágenes de
`db-migrate`, `scraper`, `publisher`, `bot` y `paypal-webhook`; el contenedor de
migraciones, en modo `--status`, vio exactamente las cuatro pendientes.

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
La rama `feat/unimarc` está subida a GitHub; abrir su PR espera autenticación de
`gh` o permisos de creación en el conector. Activar MercadoPago además exige
credenciales y plan del dueño, según
el runbook en preparación en `feat/mercadopago`; integrar la migración 51 no
inicia cobros.

## Continuación del 2026-11-09

[Salesforce](salesforce.md) cambió de veredicto con controles de stock y dos
instantáneas Tricot separadas 15 minutos: **ABC y Tricot tienen adaptador
probado**, con 820 y 465 observaciones respectivamente en la pasada de lectura
final. La migración 54 está escrita, sin aplicar, y deja publicación apagada.
La fecha de conexión será la primera ingesta real tras integrarla. Ningún
servicio se reinició ni se hizo commit desde esta continuación.
