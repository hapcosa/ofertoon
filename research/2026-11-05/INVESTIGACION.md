# Unimarc, Imperial y hardware: investigación del 5 de noviembre de 2026

## Resultado

| Tienda | Resultado comprobado desde este servidor | Decisión técnica |
|---|---|---|
| Unimarc | 719 SKU únicos / 719 declarados, en 15 páginas públicas | Fuente viable para implementar adaptador |
| Imperial | Un listado entregó 11/11 registros con precios; después respondió 520 también en la misma URL | Fuente identificada, acceso inestable; no activar todavía |
| Nice One / N1G | La portada devuelve 403 con `cf-mitigated: challenge` | Bloqueo actual comprobado; pedir feed o acceso acordado |
| PC Express | `pcexpress.cl` da 403, pero `tienda.pc-express.cl` entrega 200 con precios y páginas de catálogo | Usar el dominio público de tienda; integración viable |
| MTS | Robots 403, coincidente con la portada 403 de la revisión anterior del mismo día | Sin fuente de precios validada |

No se usaron credenciales, proxies, resolución de CAPTCHA ni navegadores
modificados. Se utilizó `httpx` con los headers que el proyecto ya tiene y
solicitudes espaciadas. Las respuestas solo describen el acceso desde este
servidor y en este momento; no una garantía permanente para todos los clientes.

## Unimarc: el bloqueo antiguo ya no describe la fuente actual

Fuente comprobada:
https://www.unimarc.cl/category/lacteos-huevos-y-refrigerados

La respuesta HTML incluye `script#__NEXT_DATA__`. Dentro de
`props.pageProps.dehydratedState.queries`, la query `productsSearch-client`
contiene `availableProducts`, `notAvailableProducts` y `resource` (total como
texto). No hace falta recuperar la API VTEX antigua que antes fallaba.

- `?page=1` entrega los índices 0–49, `?page=2` los 50–99.
- La raíz elegida declaró **719** entradas: 14 páginas de 50 y una de 19.
- Se recuperaron **719 SKU únicos**, sin duplicados en el recorrido.
- **719** tienen EAN; **716** declaran cantidad disponible mayor que cero.
- **243** llevan etiqueta **Club Unimarc**.
- **107** tienen `itemsRequiredForPromotion`: no interpretar descuentos de
  multicompra como precio de una unidad sin condiciones.
- Ninguna de estas 719 entradas declaró `paymentMethod` no vacío. Eso no prueba
  que otras categorías o futuras promociones carezcan de restricciones.
- La subcategoría `.../leches-y-cremas/leches-blancas` devolvió 33 entradas y su
  página 2 vacía: final de paginación comprobado además del caso de varias páginas.

### Decisión del dueño: Club Unimarc sí cuenta

El 5-nov el dueño indicó: «club unimarc tambien cuenta cm oferta, ser club
unimarc es solo dar el rut asi que cualquiera puede ser parte».

**Incluir Club Unimarc como oferta elegible**, conservando la condición visible
«requiere RUT / Club Unimarc». No clasificarla como tarjeta propia ni excluirla
por pertenencia al club. Esto modifica el criterio anterior de esta sesión,
que era demasiado restrictivo para el producto pedido.

La aceptación del Club no elimina la validación histórica, ni autoriza a
convertir una promoción de varias unidades en una rebaja unitaria sin condición.
El adaptador y el copy deben conservar esas diferencias. La etiqueta Club se
encuentra en `priceDetail.promotionalTag.text`; **`membership` viene vacío en
ofertas que sí dicen Club**, así que no basta mirar ese arreglo.

Ejemplo real, coincidente entre listado y ficha:
[Leche Colun entera 1 L](https://www.unimarc.cl/product/leche-entera-natural-colun-sin-tapa-1-l-2):
**$1.190 Club**, precio de lista declarado **$1.350**, SKU `2896`,
EAN `7802920777542`. La diferencia declarada no sustituye el descuento contra
nuestro historial.

### Límites antes de producción

- El recorrido fue anónimo, **sin sucursal fijada**. La portada observada
  declaraba `salesChannel=39`, pero no se demostró que ese valor garantice el
  contexto de todas las páginas de categoría. No afirmar cobertura nacional ni
  mezclar precios de sucursales hasta fijar y verificar el contexto.
- El árbol tiene ruido: en leches blancas aparecen tazones y un lechero. Dos
  incluso traen esa misma categoría en el payload. No usar el nombre de la URL
  como prueba de que todos sus productos son leche.
- El `robots.txt` observado redirigió a `/404`. No confundir ese 404 con un
  bloqueo del catálogo ni con una autorización contractual.
- `availableQuantity` contiene cifras grandes como 10.000 o 99.999: sirven como
  señal positiva declarada, no como inventario físico verificado.

### Evidencia y reproducción

- [CSV completo](unimarc_precios.csv): incluye precios publicados, etiqueta Club,
  EAN, disponibilidad declarada y condiciones originales de promociones.
- [Resumen por página](unimarc_resumen.json): incluye fecha UTC y conteos.
- [Script reproducible](unimarc_catalogo.py): no escribe DB ni publica mensajes.

```bash
.venv/bin/python research/2026-11-05/unimarc_catalogo.py --out /tmp/unimarc-auditoria
```

El script falla explícitamente si el número de SKU únicos no coincide con el
inicialmente declarado. El CSV es investigación, no una lista de ofertas
confirmadas por el detector.

## Imperial: precios encontrados, pero falta estabilidad y stock

Fuente que respondió 200:
https://www.imperial.cl/herramientas-de-banco/category/14341

La página pública contiene un script de la forma
`window.state = JSON.parse(decodeURI("…"))`. Es un catálogo Oracle Commerce;
no es necesario ejecutar JavaScript para leer ese estado. La extracción usó
parseo JSON y decodificación de URI, nunca `eval`.

Ruta de los datos:
`searchRepository.pages.<ruta>.results.records`.

Cada registro trae `sku.repositoryId`, `product.displayName`, `product.route`
y precios en los registros hijos: `sku.activePrice`, `sku.listPrice`,
`sku.salePrice`. `totalNumRecs` declaró 11 y se extrajeron 11.

Ejemplo: SKU `155853`, ingleteadora telescópica eléctrica 10 pulgadas / 1.900 W:
precio activo **$224.991**, lista declarada **$249.990**.
No se comprobó disponibilidad ni condición comercial final en la ficha.

La fuente también expone una plantilla de paginación:
`/herramientas-de-banco/_/N-3394376065?No={offset}&Nrpp={recordsPerPage}`.
Sin embargo, probarla devolvió 520. También devolvieron 520:

- Categoría raíz de herramientas y una categoría de herramientas manuales.
- Ficha del SKU 155853, incluyendo una repetición.
- Sitemap y consulta de prueba al producto en `/ccstore/v1/products/155853`.
- **La misma categoría de banco que antes respondió 200**, al repetirla.

Por lo tanto, no es defendible decir «Imperial ya funciona» ni «está bloqueada
por Akamai igual que antes». Hay una fuente real recuperable, pero el acceso
cambió durante la investigación. El 520 por sí solo no determina si la causa es
el origen, un filtro o una incidencia intermedia.

Evidencia persistida: [11 precios](imperial_precios.csv) y
[bloque de catálogo extraído](imperial_muestra.json). Todos están marcados con
stock no verificado. Falta comprobar estabilidad en otro momento, contexto de
tienda, stock y recorrido de una categoría paginada antes de conectar el runner.

## Hardware marcado como bloqueado

### Nice One / N1G

`https://niceone.cl/` redirige a `https://n1g.cl/Home/` y devuelve **403** con
challenge de Cloudflare. `https://www.n1g.cl/Home/` también da 403.
`https://www.n1g.cl/robots.txt` sí respondió 200 con texto de robots, lo que no
abre el catálogo. No se obtuvo una fuente directa de precios utilizable.

Acción concreta: pedir exportación de catálogo/feed de afiliación o acceso
acordado por IP. No incorporar precios de un comparador como si fueran
observaciones directas de Nice One.

### PC Express

**Corrección del mismo día:** `https://www.pcexpress.cl/` y
`https://pcexpress.cl/` devuelven 403 de LiteSpeed, pero la tienda funciona en
https://tienda.pc-express.cl/ . Su portada, `robots.txt`, `sitemap.xml`,
listados y fichas respondieron 200 desde este servidor. No hubo que eludir
una protección: el dominio investigado inicialmente no era el del catálogo.

La categoría pública de tarjetas de video (`path=460_475`) entregó 20 productos
en la primera página y 6 en la segunda. La página de ofertas entregó 24 en la
primera página. Las fichas muestran precios separados: por ejemplo, el SKU
`21478` cuesta $219.900 con transferencia/efectivo y $233.936 con otros medios.
La extracción deberá conservar esa condición y validar stock antes de entrar
al detector. La categoría titulada «Tarjetas de Video» incluye al menos un
puente NVLink; el nombre de la categoría no garantiza la clase de cada SKU.

### MTS

Se incluyó por la ambigüedad de «hardware» entre componentes y ferretería. El
robots siguió en 403. La revisión anterior de este mismo día también obtuvo
403 en la portada. Sigue pendiente una fuente pública funcional o feed acordado.

## Cambios y alcance

Se actualizan los planes para que no vuelvan a heredar el diagnóstico obsoleto
de Unimarc. Se conserva la decisión explícita de incluir Club Unimarc y la
muestra completa obtenida. **No se conectaron nuevas tiendas a producción**,
no se modificaron umbrales ni se publicaron mensajes. Esta entrega es la
investigación solicitada con evidencia reproducible.
