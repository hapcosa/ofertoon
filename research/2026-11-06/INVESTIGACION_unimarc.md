# Unimarc: investigación completa y adaptador — 6 de noviembre de 2026

Continúa la reapertura del 2026-11-05
([research/2026-11-05/INVESTIGACION.md](../2026-11-05/INVESTIGACION.md)), que
estableció que la tienda **no está bloqueada** y recorrió una raíz (719/719 SKUs).
Lo que faltaba era todo lo que decide si se puede conectar sin arruinar una serie:
el canal de venta, las llaves, y qué significan sus etiquetas.

Medido desde este servidor, con `httpx`, **sin navegador, sin credenciales, sin
proxies y sin resolución de CAPTCHA**. Las respuestas describen el acceso desde
acá y en este momento, no una garantía permanente.

Estado de la tienda (de los cinco de CLAUDE.md): **adaptador probado**. No es
ingesta activa — la migración 47 está escrita y **sin aplicar**.

---

## 1. El hallazgo que bloqueaba la conexión: el precio depende del canal

Unimarc cotiza por `salesChannel`. El front lo guarda en la cookie `co_sc` (lo
escribe `/api/setCookie?co_sc=N`) y el BFF lo deriva de las coordenadas de la
dirección elegida (`POST /address/validate-sc`). **Un visitante anónimo recibe el
39**: lo declara la home en `pageProps.salesChannel` y el SSR lo pone por default
(`r.co_sc = "39"` en su bundle).

Medición sobre `lacteos-huevos-y-refrigerados/leches-y-cremas/leches-blancas`
(33 SKUs), pidiendo **la misma URL** y cambiando solo la cookie:

| cookie | SKUs | precios distintos vs. anónimo |
|---|---|---|
| sin cookie | 33 | — (referencia) |
| `co_sc=39` | 33 | **0** → es el default, confirmado |
| `co_sc=1` | 33 | 1 (SKU 83611: $1.000 vs $1.190) |
| `co_sc=2` | 33 | 2 |
| `co_sc=40` | **35** | 0, pero **cambia el surtido** (+2 SKUs) |
| `co_sc=99999` | — | **caso de control**: el payload no se arma |

El canal cambia **precio y catálogo**. Es el caso Construmart: la serie de un SKU
es la de *su* canal, y mezclar dos convierte el p50 en un promedio de dos cosas
distintas. Por eso `UnimarcAdapter.SALES_CHANNEL` manda el 39 **explícito en toda
request** en vez de confiar en el default del servidor, y cambiar ese número
invalidaría el histórico entero de la tienda.

**Lo que NO se resolvió, y conviene no afirmar**: qué sucursal física es el 39. El
endpoint que traduce coordenadas a canal exige sesión (`{"message":"No session"}`
en los cuatro puntos probados), y este proyecto no abre navegador. La afirmación
verificable es "la serie es la del canal 39"; "cobertura nacional" no lo es.

Reproducible: [`unimarc_canal.py`](unimarc_canal.py).

---

## 2. Las doce respuestas (PLAN_EXPANSION §1)

| # | Pregunta | Respuesta medida |
|---|---|---|
| 1 | **¿Qué plataforma usa de verdad?** | Front **Next.js** (`__NEXT_DATA__`), backend **VTEX** (`categoryData.url` → `unimarc.vtexcommercestable.com.br`). Se entra por el HTML, no por la API VTEX: la página ya trae precio, EAN, `ppum` y promoción resueltos para un canal. El árbol de categorías sí se leyó de la API (`/api/catalog_system/pub/category/tree/1`, 200). |
| 2 | **`robots.txt` y `Crawl-delay`** | **No hay**: `robots.txt` y `sitemap.xml` responden 404 (redirigen a `/404`). Sin `Crawl-delay` declarado, el rps se elige conservador: **0.4**. |
| 3 | **¿Qué headers hacen falta?** | ⚠️ **Al revés que en el resto del repo.** 4 intentos de cada juego, misma URL: `DEFAULT_USER_AGENT` **200 4/4**, `BROWSER_USER_AGENT` **403 4/4**, `BROWSER_HEADERS` **200 4/4**. Lo que rechaza no es el UA identificable sino un UA de navegador **sin** los demás headers de navegador. El adaptador usa el default de `HttpClient` (el identificable), verificado además sobre una paginación completa (5 págs, 241/241, cinco 200). |
| 4 | **¿Pagina? ¿Cómo señala el final?** | `?page=N`, 50 por página, 1-indexada. El payload **devuelve la página servida** (`pageProps.page`), así que un `page` ignorado es detectable: el adaptador falla ruidosamente si no coincide. Una página pasada del final da **HTTP 200 con 0 filas** (no 404): probado con `mascotas?page=6` y `?page=9` sobre 5 páginas reales. |
| 5 | **¿El orden es estable entre requests?** | **Sí, y es exacto.** Dos recorridos completos de `mascotas` el mismo día: 241 únicos los dos, **241 en ambos, 0 solo en uno**. 241 filas → 241 únicos (cobertura 1,0000). Contrasta con Tottus (0,911 y dos recorridos dando 326 y 389). |
| 6 | **¿Declara el total?** | Sí, en el cuerpo: `productsSearch-client.state.data.resource`. ⚠️ Pero **el canario exacto no es viable** — ver §4. |
| 7 | **¿GTIN/EAN?** | **8.204 de 8.213 (99,89%)**, medido sobre el catálogo **completo** de las ocho llaves, no sobre la página 1. |
| 8 | **¿Trae `price_normal`?** | Sí (`sellers[0].listPrice`). 2.201 de 8.213 entradas tienen precio publicado menor al de lista. El θ de `supermercado` se puede seguir midiendo con el método de la migración 24. |
| 9 | **¿Señal de stock en el listado, y es señal?** | **Sí y es señal real**: la tienda separa `availableProducts` de `notAvailableProducts`. 15 agotados en 8.213 (0,18%), y **caen al final del orden** (páginas 32-34 de 34 en `despensa`), igual que en Cencosud. ⚠️ Vienen con **precio 0** y etiqueta `Pronto disponible`: no se emiten (un 0 no es un precio), igual que las filas sin stock de Construmart. |
| 10 | **¿Precios centinela?** | **No.** Máximo observado sobre el catálogo completo: **$289.990** (Johnnie Walker Blue Label). Cero por encima de `MAX_PLAUSIBLE_CLP`. Los únicos 0 son los 14 agotados. |
| 11 | **¿Llaves disjuntas sobre SKUs reales? ¿Catálogo o vitrina?** | **Catálogo** (son nodos del árbol propio de la tienda) y **disjuntas**: 8.213 filas → **8.212 SKUs únicos**, un solo solapado en los 28 pares. Ver §3. |
| 12 | **¿Cuánto cuesta por pasada?** | **169 requests**, 8.213 entradas, ~7 min a 0.4 rps. Dos pasadas diarias → +16.400 observaciones/día. Entra de sobra en `PASS_WINDOW` (120 min). |

---

## 3. Las llaves: ocho departamentos, y lo que quedó afuera a propósito

Recorrido completo del 2026-11-06, 169 requests, `co_sc=39` fijo
([`unimarc_llaves.py`](unimarc_llaves.py) · [JSON](unimarc_llaves.json) ·
[CSV](unimarc_skus.csv)):

| llave | enumerados / declarados | págs | agotados | categoría interna |
|---|---|---|---|---|
| `despensa` | 1.680 / 1.681 | 34 | 4 | supermercado |
| `bebidas-y-licores` | 1.588 / 1.588 | 32 | 2 | supermercado |
| `perfumeria` | 1.353 / 1.353 | 28 | 5 | **belleza** |
| `desayuno-y-dulces` | 1.314 / 1.315 | 27 | 1 | supermercado |
| `limpieza` | 810 / 811 | 17 | 0 | supermercado |
| `lacteos-huevos-y-refrigerados` | 719 / 719 | 15 | 3 | supermercado |
| `congelados` | 508 / 508 | 11 | 0 | supermercado |
| `mascotas` | 241 / 241 | 5 | 0 | supermercado |
| **total** | **8.213 filas → 8.212 únicos** | **169** | **15** | |

**Disjuntas sobre SKUs reales**: un único solapado en los 28 pares — un espumador
de leche (`97701`) que vive en `desayuno-y-dulces` y aparece cross-listado en
`lacteos-huevos-y-refrigerados`. Su efecto es pesar doble en su propio p50, sobre
1 listing de 8.212, y por eso **el adaptador no deduplica entre llaves**:
deduplicar traería el riesgo que `cencosud_family` documenta (gana la primera
llave del orden de `db.load_store_targets`) y acá `perfumeria` mapea a `belleza`
mientras las otras siete mapean a `supermercado` — un solapamiento futuro con
perfumería mediría un producto de belleza con el θ de supermercado **en
silencio**. Por un listing de 8.212 no vale pagar eso.

### Lo que quedó afuera, para que nadie lo agregue sin releer esto

* `carnes`, `frutas-y-verduras`, `quesos-y-fiambres`, `panaderia-y-pasteleria` —
  **precio estacional o de peso variable**. El p50 de 60 días de un tomate no es
  una baseline, es el promedio de dos temporadas. Mismo criterio que sacó
  `Frutas-y-Verduras` y `Carnes` de Tottus.
* `veganos-y-vegetarianos` — **vitrina transversal**: cross-lista despensa,
  lácteos y congelados.
* `hogar`, `bebes-y-ninos` — no mapean limpio a ninguna categoría interna.
  Meterlos en `supermercado` mezclaría dos distribuciones de precio bajo un θ
  calibrado para una.
* `store-locator` — no es catálogo.

### ⚠️ `fiestas-patrias`: la vitrina que no se ve en el árbol

No está en el árbol de nivel 1 y **no debe ser una llave**, pero existe y hay que
conocerla: es el `categorySlug` de **32 de las 50** entradas de la página 1 de
`bebidas-y-licores` (Coca-Colas, cervezas, vinos — y un set de vasos, que es ruido
de catálogo).

De ahí sale una trampa de método: **el `categorySlug` de un producto NO sirve para
verificar que una llave trae lo que dice**. Mide la categoría principal que la
tienda le asignó, que puede ser una vitrina estacional. Medir `bebidas-y-licores`
con ese campo da 34% de coincidencia y parece el caso `cat2049/Audifonos` de
Falabella (forma correcta, contenido equivocado) — y no lo es: el contenido es
bebidas. El tamiz hay que hacerlo sobre el **nombre** o sobre `categories[]`.

---

## 4. Por qué no hay canario exacto, aunque el total esté a mano

La tienda declara el total y la paginación llega al final, así que el chequeo
exacto **se puede calcular**. No se usa: de las ocho llaves, cinco cerraron exacto
y **tres quedaron UNA entrada cortas** (`despensa` 1.680/1.681,
`desayuno-y-dulces` 1.314/1.315, `limpieza` 810/811). Y es inestable:
`bebidas-y-licores` cerró 1.588/1.588 en este recorrido.

Es la misma deriva entre el servicio que cuenta y el que pagina que documenta
`cencosud_family`, y la misma decisión: tres llaves en `partial` casi toda pasada
—por **una entrada de 1.681**— es un mensaje de Telegram por pasada, o sea una
alarma que suena siempre y por lo tanto está apagada. Es el caso que la familia
Falabella ya documentó con su llave corta por un producto de 352.

Queda el canario estadístico, y el orden estable (§2 #5) hace que sea confiable.

---

## 5. Las etiquetas: dos son condiciones y dos no

Las cuatro etiquetas de `priceDetail.promotionalTag.text` sobre las 8.213 entradas:

| etiqueta | n | relación con el precio | ¿es condición? |
|---|---|---|---|
| `Club Unimarc` | 2.615 | precio < lista (2.007) **o** promo (608) | **sí** |
| `Exclusivo .cl` | 220 | precio < lista (194) **o** promo (26) | **sí** |
| `Diamante` | 5 | precio **igual** al de lista, sin promo | no — sello de vino |
| `Pronto disponible` | 15 | los 15 agotados, 14 con precio 0 | no — es **stock** |

**`promotionalTag` no es un campo de condiciones**: es el espacio de marketing del
tile. De ahí que el adaptador emita `price_condition` solo cuando hay un precio
condicionado — precio menor al de lista, o promoción de multicompra. Ese filtro
clasifica bien las 8.213: de las Club y las Exclusivo **ninguna** tiene precio
igual al de lista sin promo (verificado: 0 casos), y Diamante y Pronto disponible
no pasan nunca.

Es una regla de dominio en vez de una lista de nombres a mantener: una etiqueta
nueva sobre un precio rebajado se declara verbatim —el suscriptor tiene que
leerla aunque nosotros no sepamos qué significa— y un sello nuevo sobre un precio
sin rebaja no inventa letra chica. Publicar "Requiere Diamante" sobre un vino que
cuesta lo de siempre es el error simétrico de callar el Club.

Confirmado además lo que avisaba la investigación del 5-nov: **`membership` viene
vacío en ofertas que sí dicen Club**, así que mirar ese arreglo no alcanza. Y
`paymentMethod` vino vacío en **las 8.213**: la guarda que manda un precio con
medio de pago a `price_card` existe de forma preventiva y no se ejercitó con datos
reales.

---

## 6. Las promociones de multicompra

693 de 8.213 entradas (8,4%) traen `itemsRequiredForPromotion`, y **635 de ellas
tienen precio unitario igual al de lista** — o sea el ahorro existe solo comprando
N, que es exactamente lo que midió la migración 46 sobre una raíz y acá se
confirma sobre ocho.

Tres fuentes dicen lo mismo y el adaptador **exige que concuerden**:
`priceDetail.itemsRequiredForPromotion` (las unidades),
`promotion.descriptionMessage` (`"4 x $1.150"`, el texto) y `promotion.price` (el
unitario, **en float**). `qty` y `total` se toman del texto —enteros, en CLP, como
manda la regla 3— y se verifican contra los otros dos. Si discrepan no se emite
promo: el producto entra con su precio unitario, que es lo que de verdad paga
quien compra una.

Etiquetas de las 693: `Club Unimarc` 626, `Exclusivo .cl` 66, `Pronto disponible`
1 (un agotado). O sea **la promo casi siempre viene con una condición**, y el
mensaje tiene que decir las dos cosas: `4 x $1.150` es cuánto se ahorra y bajo qué
cantidad; `Club Unimarc` es quién puede pagarlo.

---

## 7. Qué se construyó

* `scrapers/stores/unimarc.py` — el adaptador.
* `tests/test_unimarc.py` — 33 tests contra tres fixtures de payload real.
* `tests/fixtures/unimarc_{lacteos_p1,lacteos_p15,bebidas_p20_diamante}.html`.
* `migrations/47_unimarc_y_condicion_del_precio.sql` — **escrita, sin aplicar**.
* `price_points.price_condition` + su camino hasta el copy
  (`RawProduct` → `db.insert_price_point` → `Candidate` → `formatter.condition_line`).

### Cómo se verificó el efecto, no el mensaje

**1. Una corrida del runner que ESCRIBE** (`--dry-run` no ejercita el INSERT).
Base descartable aparte con la secuencia completa de 47 migraciones, dejando solo
la llave `mascotas`, `DATABASE_URL` apuntado ahí y alertas sin configurar:

```
python -m scrapers.runner --once --store unimarc --skip-pricing
  → unimarc/supermercado → 241 vistos, 241 observaciones nuevas [ok]
```

Lo que quedó escrito:

| | |
|---|---|
| `scrape_runs` | `status=ok`, `items_seen=241`, `items_ok=241`, sin error |
| `listings` / `price_points` | 241 / 241 |
| con `price_condition` | 135 — 127 `Club Unimarc` + 8 `Exclusivo .cl`; 106 sin |
| con `promo_qty` | 43 |
| con `pum_price` | 241 |
| con `gtin_raw` | 241 |
| `price_effective` ≤ 0 o sobre `MAX_PLAUSIBLE_CLP` | **0** |
| `price_condition` vacía o con solo espacios | **0** |

**2. El seed de la migración, contra una base descartable**, con caso de control:
las 8 llaves exactas (7 a `supermercado`, `perfumeria` a `belleza`), la columna
`VARCHAR(48)` nullable, el CHECK **rechazando** una condición de solo espacios y
**aceptando** `'Club Unimarc'`, y **0** de las llaves excluidas (`carnes`,
`frutas-y-verduras`, `fiestas-patrias`, `hogar`) presentes.

⚠️ **Esa parte no la puede verificar un test**, y conviene saberlo: el
`_truncate_state` del conftest preserva `categories`, `stores` y
`schema_migrations` y **trunca todo el resto entre tests**, `store_categories`
incluida. O sea una migración que sembrara llaves equivocadas pasaría la suite
igual. Por eso se verificó aplicando la migración aparte y leyendo las filas.

**3. `resolve_adapter`** resuelve `scrapers.stores.unimarc:UnimarcAdapter` y la
instancia cumple `StoreAdapter`, **no** `CountingAdapter` (no hay canario exacto,
§4) y **no** `DetailAdapter` (el listado trae precio). Es el paso 7 de
CLAUDE.md §1: un `adapter` que la imagen no tenga deja las llaves en `failed`.

**4. El mensaje que saldría**, generado con el formatter y una observación real de
esa corrida (el `p50` es simulado: sin 30 días de serie no hay p50 real):

```
🔥 −33% · Supermercado

Alimento húmedo perro Pedigree razas pequeñas carne sobre 100 g
Unimarc

$2.000 por 3  ·  $667 cada una  ·  antes real $989 por unidad
⚠️ Ahorro por cantidad: 3 x $2.000. El precio de una unidad no baja.
🪪 Requiere Club Unimarc
📦 $8.600 por Kg  ·  antes real $9.890
📉 Por debajo de su piso habitual de 60 días
```

Las dos condiciones salen y son distintas: `3 x $2.000` es cuánto se ahorra y bajo
qué cantidad; `Club Unimarc` es quién puede pagarlo.

**5. La suite**, con `TEST_DATABASE_URL` apuntando a `ofertas_test_unimarc` (base
propia de la rama, como manda CLAUDE.md §Trabajo multi-agente §4) — o sea sin
saltear los 54 tests de DB:

* **948 passed, 0 fallos** (`exit=0`) en la corrida completa con todo en el
  árbol: la migración 47, el adaptador, los tres fixtures, `test_unimarc.py` y
  `test_price_condition.py`.

⚠️ Una corrida intermedia dio **934 passed / 14 errors** con
`UndefinedTableError`, y la causa fue de método, no del código: se lanzó un
`pytest` de un archivo suelto **mientras la suite corría contra la misma base**,
y el setup de sesión del conftest hace `DROP SCHEMA public CASCADE`. Los 14
pasan aislados. Queda anotado en TRAMPAS §F.

## 8. Lo que queda abierto

1. **La sucursal del canal 39 no está identificada.** Requiere sesión. La serie es
   la del canal 39 y eso es lo que se puede afirmar.
2. **`min_history_days` de `supermercado` y `belleza`**: supermercado está en
   **10** (excepción vencida de la migración 32, ver abajo). Si Unimarc entra con
   eso así, publica contra un p50 de dos semanas teniendo uno de ocho.
3. **El tope fino del tema `supermercado`**: cuota 5, una sola categoría ruteada y
   `MAX_PER_CATEGORY_PER_DAY = 3` → dos lugares inalcanzables. Unimarc **no** lo
   arregla: el limitante es la categoría, no la tienda.
4. **`paymentMethod` nunca se observó no vacío**: la guarda de `price_card` no
   está ejercitada contra datos reales.
