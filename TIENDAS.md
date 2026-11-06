# TIENDAS.md

Censo de tiendas: **las que están conectadas hoy** y **las que van a entrar**, con
el estado real de cada una. Escrito el **2026-11-05**, con actualización de
producción del **2026-11-06** inmediatamente abajo.

**Actualización 2026-11-06:** producción tiene **31 tiendas activas y 727 llaves**
tras aplicar las migraciones 40–46. Se inició la primera ingesta dirigida de
`ripley`, `hites`, `pc-express`, `megabytes`, `inforingen`, `colloky`, `nomades`,
`speedo`, `trekbikeschile`, `newbalance`, `lippi`, `thenorthface`, `mammut` y
`marmot`. Los recuentos y errores de la primera pasada están en el bloque nuevo
de [`HANDOFF.md`](HANDOFF.md). `ripley` y `pc-express` acumulan puntos con
`publish_enabled = false`; las otras doce tienen publicación habilitada, sujeta
a los 30 días observados de historia y a la detección/curación habitual. Unimarc
sigue en un worktree separado, sin ingesta en producción. Imperial sigue sin
fuente estable (403). Las tablas siguientes son la **fotografía del 5-nov**, no
el estado actual de las tiendas ya conectadas.

Los datos de la primera tabla salen de consultar la base de producción
(`stores`, `store_categories`, `listings`), no de memoria. Los de las demás salen
de las mediciones de `INVESTIGACION_*.md`.

⚠️ **Las migraciones 40–46 ya están aplicadas en producción.** La 40 aplicada
incluye `publish_enabled` y PC Express, añadidos el 6-nov al archivo del
worktree principal antes de aplicarla. Su checksum debe mantenerse idéntico al
de esa versión; revisar [`HANDOFF.md`](HANDOFF.md) antes de integrar otros
worktrees.

Documentos hermanos: [`TIENDAS_PROHIBIDAS.md`](TIENDAS_PROHIBIDAS.md) (las que no
se pueden), [`INVESTIGACION_deporte_outdoor.md`](INVESTIGACION_deporte_outdoor.md),
[`INVESTIGACION_ropa.md`](INVESTIGACION_ropa.md),
[`INVESTIGACION_hardware.md`](INVESTIGACION_hardware.md),
[`INVESTIGACION_viajes.md`](INVESTIGACION_viajes.md),
[`INVESTIGACION_TANDA2.md`](INVESTIGACION_TANDA2.md).

---

## 1. Fotografía del 5-nov: 17 tiendas, 165 llaves

| tienda | familia / adaptador | llaves | listings | estabilidad de cohorte |
|---|---|---|---|---|
| **falabella** | `falabella_family` | 11 | **64.421** | ⚠️ **8%** |
| **jumbo** | `cencosud_family` | 6 | 14.240 | sin evaluar (conectada 4-nov) |
| **paris** | `paris` | 10 | 9.709 | ⚠️ **15%** |
| **tottus** | `falabella_family` | 8 | 8.485 | sin evaluar |
| **santaisabel** | `cencosud_family` | 6 | 6.404 | sin evaluar (conectada 4-nov) |
| **nike** | `vtex_family` | 5 | 4.174 | 0% ⚠️ por el agujero de octubre, no por rotación |
| **andesgear** | `magento_html` | 25 | 3.025 | 🟢 **79%** |
| **easy** | `easy` | 8 | 3.021 | 🟢 **96%** por cohorte (34% transversal, que miente) |
| **sodimac** | `falabella_family` | 5 | 2.393 | sin dato |
| **ferretek** | `ferretek` | 7 | 1.606 | 🟢 **99%** |
| **prat** | `shopify_family` | 3 | 1.363 | 🟢 **96%** |
| **pcfactory** | `pcfactory` | 12 | 924 | ⚠️ **39%** |
| **spdigital** | `spdigital` | 17 | 699 | 🔴 **4%** |
| **kruuse** | `kruuse` | 24 | 641 | 🟢 **81%** (14% bruto, corregido por los 518 sin stock) |
| **urban** | `woo_family` | 1 | 293 | sin dato |
| **construmart** | `magento_html` | 19 | 234 | 🟢 **92%** |
| **kupfer** | `magento_html` | 1 | 25 | sin dato |

⚠️ **Cuatro tiendas están bajo `UMBRAL_ESTABILIDAD = 0.40`** y el criterio manda
apagarlas: `spdigital` (4%), `falabella` (8%), `paris` (15%) y `pcfactory` (39%).
**No se apagó ninguna**, y es decisión de producto: Falabella y Paris son el 46%
del canal y llevan 114 publicaciones cada una. El umbral además está sin calibrar.

**Categorías alimentadas** (15): `belleza`, `deporte-calzado`,
`deporte-equipamiento`, `deporte-vestuario`, `ferre-herramientas`, `ferre-jardin`,
`hogar-electro`, `ropa-accesorios`, `ropa-calzado`, `supermercado`, `tecno-audio`,
`tecno-celulares`, `tecno-componentes`, `tecno-notebooks`, `tecno-tv`.

⚠️ Dos categorías están alimentadas por **una sola tienda**: `deporte-calzado` y
`deporte-equipamiento` (solo Andesgear), y `ropa-accesorios` (solo Nike). Eso las
hace frágiles al tope `MAX_PER_STORE_PER_DAY`.

---

## 2. Listas para conectar: medidas y con veredicto

Entran con **cero líneas de adaptador** salvo donde se indica. Falta por cada una:
fixture con payload real, fila en `stores` + `store_categories`, y migración con
fecha de conexión anotada.

| tienda | familia | llaves medidas | SKUs | dup. residual | θ medible | notas |
|---|---|---|---|---|---|---|
| **colloky** | `vtex_family` | **4 raíces** | **3.530** | **1,00×** (disjuntas) | 🟢 57,5% | 🟢 Jaccard **1,0000**, canario exacto, GTIN 99,8%. ⚠️ Necesita **categoría nueva**: su raíz `Ropa` (1.449) no tiene dónde caer |
| **trekbikeschile** | `magento_html` | **93 hojas** | 513 de 527 (97,3%) | **1,05×** | 🟢 42,4% | Config Sparta (`paginates=False`). ⚠️ Ticket hasta **$10,9M** (bicicletas) |
| **speedo** | `magento_html` | **70 hojas** | 383 de 425 (90,1%) | **1,15×** | 🟢 41,5% | Config Sparta. Requiere los selectores nuevos (`name_selector`/`url_selector`/`sku_selector`) |
| **sparta** | `magento_html` | 340 hojas | 3.157 de 13.448 (**24%**) | 1,72× | 🟢 41,6% | Config Kupfer. ⚠️ El techo de 24% es por `Disallow: /*?`. Requiere `dedupe_across_categories` con la letra chica de los ejes cruzados |
| **lippi** | `shopify_family` | **76 hojas** | 3.418 de 3.581 (95,4%) | **1,31×** | 🟢 11,6% | 🟢 Flag `emitir_por_producto` **ya implementado y testeado**. UA: `DEFAULT_USER_AGENT` (su 429 es por headers) |
| **newbalance** | `magento_html` | **81 hojas** | 909 de 1.408 (64,6%) | 1,87× | 🟢 39,5% | ✅ Vitrinas excluidas por decisión del dueño (se pierde el 35%) |
| **infor-ingen** | `woo_family` | **14 llaves** | **1.615** | **1,048×** | 🟢 100% muestra | 🟢 Jaccard **1,0000**, canario exacto (`count==enumerado` en 58/58), stock real |
| **megabytes** | `woo_family` | **9 llaves** | 327 | 1,15× | 🟢 91% muestra | 🟢 Jaccard **1,0000**. ⚠️ **Solo con `DEFAULT_USER_AGENT`** (los headers de navegador la rompen). Canario estadístico, no exacto |

### Las cuatro de Magento del grupo `Crawl-delay: 3` — medidas

Parsean con los selectores por defecto y comparten el robots de Andesgear
(`paginates=True`). Barrido completo, 803 hojas:

| tienda | hojas cat. | dup. residual | θ medible | notas |
|---|---|---|---|---|
| **mammut** | 97 | **1,27×** | 🟢 55,3% | 🟢 **193/193 hojas sin un error**; vitrinas aportan 10 exclusivos |
| **marmot** | 77 | **1,24×** | 🟢 64,8% | 🟢 **144/144 sin error**; 23 exclusivos |
| **thenorthface** | 113 | **1,40×** | 🟢 36,5% | 58 exclusivos. ⚠️ pmax **$6.999.990** — verificar si es centinela |
| **kliper** | 111 | 1,26× | 🟢 51,3% | ⚠️ **886 SKUs exclusivos (36%)** en vitrinas, el grueso en el eje **`marcas` (670)**, que es eje legítimo de un multimarca |

⚠️ **Estos porcentajes de cobertura NO son el techo de catálogo**: el barrido lee
solo la página 1 de cada hoja y las cuatro **sí paginan**, así que en producción
recolectan mucho más. De esta medición se lee **qué llaves usar**, no cuánto se
alcanza. Kliper declara 13.769 productos y el barrido vio 2.462.

⚠️ **Y antes de conectarlas las cuatro hay una decisión**: `kliper` declara
**13.769 productos** y su menú enlaza `/marcas/the-north-face`, `/marcas/marmot`,
`/marcas/mammut` y **`/marcas/andesgear`** — vende las marcas de las otras tres
**y de una tienda ya conectada**. Conectar las cuatro es contar el mismo catálogo
cuatro veces en el presupuesto de pasada, y la misma oferta podría salir dos veces
al canal con dos precios.

---

## 3. Medidas, con una decisión pendiente

| tienda | familia | qué falta decidir |
|---|---|---|
| **nomades.com** | 🔴 adaptador **escrito** (`scrapers/stores/nomades.py`) | 🟢 24 llaves, **282 SKUs CLP**, solapamiento **cero**, canario exacto, 24 requests/pasada. Falta **categoría nueva** (`viajes-tours`) con θ heredado, y el fixture + tests |
| **spacestore** | `shopify_family` | Entra con cero código (1,31 variantes/producto), pero **vende merchandising Disney**: no tiene categoría en el sistema |
| **hites / tricot / abc** | 🔴 `salesforce_family` (no existe) | Un adaptador cubre las tres. 🟢 Orden estable (Jaccard 1,0000 ×3). ⚠️ Hites publica **tres precios** y el más prominente exige su tarjeta; ABC cotiza **por zona de inventario** (caso Construmart) |
| **marathon** | 🔴 `salesforce_family` | Sumaría la cuarta a esa familia |
| **cruceros.cl** | 🔴 adaptador nuevo | 🟢 14.285 zarpadas con sitemap propio. Pendiente del **soporte de moneda** (cotiza en USD, aprobado por el dueño el 5-nov) |

---

## 4. Necesitan más medición antes de decidir

| tienda | familia probable | qué falta |
|---|---|---|
| **casaroyal**, **asics** | `vtex_family` | `category/tree` responde; faltan las 11 preguntas restantes |
| **volkanica**, **stanley1913**, **underarmour** | `shopify_family` | El endpoint responde; falta todo lo demás |
| **tecnoplaza** | `woo_family` | Su endpoint de categorías agotó **3 reintentos con `ReadTimeout`** en dos corridas |
| **alltec**, **todoclick**, **compuchile**, **globalmac** | 🔴 `presta_family` | Solo firma de PrestaShop; no hay familia |
| **sipoonline**, **toptec**, **rutaoutdoor** | 🔴 `jumpseller_family` | Solo firma. Las tres con `Crawl-delay` 60/10/5 |
| **sistemax** | 🔴 `opencart_family` | Solo firma |
| **cocha**, **travelsecurity** | 🔴 nuevo | Falta la ruta de catálogo de su sección de paquetes |
| **imperial** | 🔴 `occ_family` (Oracle Commerce Cloud) | [Revalidación 6-nov](research/2026-11-06/IMPERIAL.md): 403 «Access Denied» en 6/6 intentos; el 5-nov hubo 11 precios en una respuesta y luego 520. Sin fuente estable |
| **myshop**, **winpy**, **maconline**, **mercadodigital**, **bip**, **pchardware** | 🔴 nuevo | Plataforma sin determinar. Winpy declara `generator: Winpy.cl` (hecho en casa); su `Crawl-delay` real es **5, no 10** |
| **unimarc** | 🔴 nuevo (Next.js, `__NEXT_DATA__`) | 🟢 Acceso, paginación y EAN ya medidos (719/719). Falta: fijar y **verificar la sucursal** (riesgo Construmart), y decidir cómo trata el detector las **107 promociones de multicompra** y las **243 Club** |
| **pc-express** | 🟢 conectado el 6-nov; publicación pausada | [8 llaves públicas, 458/458 SKU y 458 puntos iniciales en producción](research/2026-11-06/PC_EXPRESS.md). Precio principal: transferencia. Falta control negativo de stock antes de publicar |
| **latamairlines** | 🔴 nuevo | Pasa con `BROWSER_HEADERS`; su `sitemapindex` da timeout |

---

## 5. Lo que NO entra

Detalle y razón medida en [`TIENDAS_PROHIBIDAS.md`](TIENDAS_PROHIBIDAS.md). Resumen:

- 🔴 **Bot management firme**: Decathlon, **Nice One** (403 con
  `cf-mitigated: challenge`, re-confirmado el 5-nov), MTS, Adidas, MercadoLibre.
- ✅ **Corregidas el 2026-11-05 — estaban como firmes y son viables**: **Unimarc**
  (su catálogo vive en `__NEXT_DATA__` de las páginas de categoría; 719/719 SKUs
  con EAN) y **PC Express** (el host real es `tienda.pc-express.cl`, al que
  `www.pc-express.cl` redirige 301). Detalle y la letra chica de las promociones
  de multicompra y del Club Unimarc en `TIENDAS_PROHIBIDAS.md`.
- 🟠 **Prohibido por su propio `robots.txt`**: **Doite** (`/collections/*`), **Lider**
  (`/search*`), **Kayak** (`/flights/` y `/hotels/`).
- 🔴 **Precio de un tercero que rota** (rompe la baseline por SKU): Kayak,
  **solotodo.cl**, MercadoLibre.
- 🔴 **Tarifa inaccesible**: **JetSmart** (motor de reservas prohibido por su
  robots), **Sky** (shell de JS, habría que revertir bundles).
- 🔴 **Sin SKU en el grid**: **weplay.cl** (1 de 36 filas lo trae).
- ⚫ **No son tiendas**: dafiti.cl (cerró Chile), mountain.cl (copia HTTrack de
  2022), zmart.cl (cambió a juguetes), tecnoshop.cl y ggames.cl (dominios
  secuestrados), pcofertas.cl (en venta), y ~20 dominios cuyo DNS no resuelve.

---

## 6. Orden sugerido de conexión

El criterio es costo de implementación contra catálogo aportado y estabilidad
esperada, no simpatía por la vertical.

1. **Colloky** — cero código, 3.530 SKUs disjuntos, la mejor medida de toda la
   Fase 0. Bloqueada solo por la categoría nueva.
2. **Infor-Ingen + Megabytes** — cero código (`woo_family`), llaves resueltas,
   orden estable, ~30 requests por pasada entre las dos. Y la vertical de hardware
   **necesita tiendas que acumulen serie**, que es exactamente lo que miden.
3. **Trek + Speedo** — 1,05× y 1,15× de solapamiento residual. Speedo necesita los
   selectores nuevos, que ya están en la familia.
4. **Lippi** — el flag ya está implementado y testeado.
5. **nomades.com** — llena un tema que hoy está mudo, 24 requests por pasada, y el
   adaptador ya está escrito.
6. **Sparta, New Balance, y las cuatro de `Crawl-delay: 3`** — después de resolver
   el solapamiento con Kliper y el techo del 24% de Sparta.
7. **`salesforce_family`** (hites, tricot, abc, marathon) — el mejor retorno por
   adaptador escrito que queda, pero es un adaptador nuevo y le faltan 5 de las 12
   preguntas.

⚠️ **Y el recordatorio que vale para todas**: una tienda nueva **no publica nada
durante 30 días** (`MIN_POINTS`/`MIN_DAYS` son un rechazo, no un default). El
retorno de todo esto se ve en diciembre de 2026, no en noviembre.

⚠️ **Conectar por tandas, midiendo la duración de la pasada después de cada una.**
El runner es secuencial y `db.PASS_WINDOW` son 2 h; la pasada ya usa ~57 min, así
que el presupuesto que queda es de ~1 h de requests.
