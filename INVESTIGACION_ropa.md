# INVESTIGACION_ropa.md

Fase 0 de `PLAN_EXPANSION.md` §2.1 (Colloky) y §2.4 (la hipótesis Salesforce).
Medido el **2026-11-04**.

**Veredictos:** Colloky 🟢 entra, y es la tienda mejor medida de toda esta Fase 0.
La terna Salesforce 🟢 es real y un solo adaptador la cubre — pero son **tres
tiendas, no cuatro**.

---

## 1. Colloky — 🟢 entra, y es la más limpia del plan

### Las doce respuestas

| # | Pregunta | Respuesta medida |
|---|---|---|
| 1 | **Plataforma** | **VTEX**, sin ambigüedad: **5.826 ocurrencias** de `vtex` en la home y la API de catálogo responde. ⇒ `vtex_family`, familia que ya existe. |
| 2 | **`robots.txt`** | 200, **7 `Disallow` en total**, sin `Crawl-delay`, y **ninguno toca `/api/catalog_system/`**. ⇒ `rate_limit_rps = 0.5`, el default de la familia. |
| 3 | **UA** | `BROWSER_HEADERS_JSON` (el que la familia ya manda). **256 requests entre las dos corridas, cero fallos, cero reintentos, cero 403/429.** |
| 4 | **Paginación** | `_from`/`_to` de la API, con `206 Partial Content` como respuesta normal (ya cubierto por `http.SUCCESS_STATUS`). El final es una lista vacía o una página con menos de `PAGE_SIZE`. |
| 5 | **¿Orden estable?** | 🟢 **Probado directo, y es el mejor resultado de toda esta Fase 0.** Dos recorridos completos de `Calzado` separados por 30 s (2026-11-05): **Jaccard = 1,0000** — 1.331 filas → 1.331 únicos en los dos, **cero duplicados dentro de cada recorrido** y **cero SKUs exclusivos de uno u otro**. El total declarado dio 1.331 las dos veces, calzando exacto. <br>De paso queda medido el crecimiento de catálogo: 1.273 el 4-nov y 1.331 el 5-nov (+58 en un día), y **el declarado lo siguió** — o sea el canario exacto no se desincroniza con la deriva, que es justo lo que lo descalifica en Cencosud y en la familia Falabella. |
| 6 | **Total declarado** | 🟢 **Sí, en el header `Resources: 0-49/N`**, que es la fuente del canario **exacto**. Ver abajo: acá sí es viable. |
| 7 | **GTIN** | 🟢 **99,8%** — 3.174 de 3.180 productos muestreados traen `ean` en sus items. Es la cobertura de GTIN más alta de cualquier tienda del sistema. ⚠️ Y conviene no exagerar lo que vale: `CLAUDE.md` tiene medido que el cuello de botella del cross-store **no es la cobertura sino el solapamiento**, y Colloky es ropa y calzado **infantil** — las grandes que venderían lo mismo (Falabella, Paris) no exponen GTIN en el listado. Lo más probable es que siga dando cero mensajes. Medirlo después de conectar, no antes. |
| 8 | **`price_normal`** | 🟢 **57,5%** de los productos muestreados tienen `ListPrice > Price`. ⇒ θ se puede fijar midiendo. |
| 9 | **Stock en el listado** | 🟡 **El campo existe pero no informa nada**: `AvailableQuantity > 0` en **100%** de los 3.180 productos. O sea la API **no devuelve agotados**: desaparecen del listado en vez de aparecer marcados. Para la serie eso es benigno (un producto que desaparece simplemente deja de observarse, y `compute_baseline` filtra `if in_stock`), pero hay que escribirlo: **`in_stock` en Colloky es una constante, no una señal**, y la guarda de stock del detector no protege nada ahí. |
| 10 | **Centinelas** | 🟢 No. **Precio máximo observado: $49.990.** |
| 11 | **Llaves disjuntas** | 🟢 **Perfectamente disjuntas, verificado enumerando el catálogo completo** (120 requests, 339,5 MB). Ver abajo. |
| 12 | **Costo por pasada** | **71-72 requests, ~200 MB, ~145 s** con las 4 raíces. Es la tienda más barata en requests de toda esta Fase 0. ⚠️ Pesada en bytes: VTEX sirve ~2,8 MB por página de 50. |

### Las llaves: cuatro raíces, y una vitrina que NO puede entrar

Enumeré **las cinco raíces completas** y crucé los `productId`:

| raíz | declarado | enumerado único |
|---|---|---|
| `1` Calzado | 1.273 | **1.273** |
| `2` Escolar | 181 | **181** |
| `3` Ropa | 1.449 | **1.449** |
| `4` Accesorios | 627 | **627** |
| `5` Outlet | 2.370 | 2.368 |

Las cuatro primeras tienen **cero solape entre sí** y suman **3.530**, que es
exactamente la unión. El árbol de Colloky es limpio: la taxonomía es una
partición de verdad.

🔴 **`Outlet` es una vitrina y no puede ser llave.** Sus 2.368 SKUs están **100%
contenidos** en las otras cuatro raíces: **cero exclusivos**. Conectarla haría
pesar el doble a 2.368 listings —el 67% del catálogo— en su propio p50. Solapa
76% con Calzado, 67% con Ropa, 61% con Escolar y 52% con Accesorios.

**Recomendación: las 4 raíces de catálogo, `Outlet` afuera.** Y no hay que bajar
a subcategorías: **ningún nodo del árbol pasa `MAX_OFFSET = 2500`** (el más
grande es Outlet con 2.370, y queda afuera), así que la restricción que en Nike
obliga a usar subcategorías acá no aplica.

### El canario exacto: acá SÍ

A diferencia de la familia Falabella y de Cencosud, en Colloky **lo enumerado
igualó lo declarado exacto en las 4 raíces**. El único desvío fue `Outlet`
(2.368 de 2.370, deriva de 2 ítems) y queda excluida. ⇒ **`completeness()`
implementable y el canario exacto encendido**, sin tolerancias.

### ⚠️ Falta una categoría: la raíz más grande de Colloky no tiene dónde caer

Las 15 categorías internas al 2026-11-05 son `belleza`, `deporte-calzado`,
`deporte-equipamiento`, `deporte-vestuario`, `ferre-herramientas`, `ferre-jardin`,
`hogar-electro`, `ropa-accesorios`, `ropa-calzado`, `supermercado`, `tecno-audio`,
`tecno-celulares`, `tecno-componentes`, `tecno-notebooks`, `tecno-tv`.

El mapeo de Colloky sale solo para tres de sus cuatro raíces:

| raíz de Colloky | SKUs | categoría interna |
|---|---|---|
| `1` Calzado | 1.273 | `ropa-calzado` (θ 0.350) |
| `4` Accesorios | 627 | `ropa-accesorios` (θ 0.350) |
| `2` Escolar | 181 | `ropa-accesorios`, o propia |
| **`3` Ropa** | **1.449** | 🔴 **ninguna** |

**`Ropa` es su raíz más grande y no existe un `ropa-vestuario`.** La única
categoría de vestuario del sistema es `deporte-vestuario` (θ 0.350) y meter ahí
poleras y pantalones de niño mezclaría dos comportamientos de precio distintos en
una sola serie de θ — justo lo que la migración 24 manda separar.

⇒ Conectar Colloky **requiere una categoría nueva** (`ropa-vestuario`, θ de
partida heredado de sus vecinos y anotado como herencia, no como medición: Colloky
sí declara `ListPrice` en 57,5%, así que acá θ se puede medir después). Y eso se
cruza con la decisión de ticket de abajo: si Colloky va a categoría propia por el
rango de $50k, la categoría nueva podría ser directamente `ropa-infantil` en vez
de `ropa-vestuario`. **Es una decisión de producto y esta Fase 0 no la toma.**

### ⚠️ Lo que Colloky rompe: el rango de ticket

Precio máximo del catálogo: **$49.990**. `compute_score` es
`discount_real*100 + below_floor*50` y **no mira el precio absoluto** a
propósito. Es el mismo choque que trajo el supermercado, en la dirección del
supermercado: un 30% sobre unas zapatillas de niño de $25.990 son **$7.800** de
ahorro puntuando igual que un 30% sobre un notebook.

La solución ya está decidida por precedente y **no es tocar el score**: es darle
destino propio. Colloky cae naturalmente en `ropa-calzado` / `ropa-accesorios`,
que hoy alimentan Falabella y Nike con tickets mucho mayores. **Es una decisión
de producto** (¿categoría propia tipo `ropa-infantil` con tema propio, como se
hizo con `supermercado` y `belleza`?), y esta Fase 0 no la toma.

---

## 2. La terna Salesforce — 🟢 un adaptador, tres tiendas

### ⚠️ Primera corrección: son tres, no cuatro

`PLAN_EXPANSION.md` §2.4 dice: "**Hites, La Polar, Tricot y ABCDin** corren las
cuatro Salesforce Commerce Cloud. O sea un adaptador nuevo cubre cuatro tiendas".

Medido hoy: **`www.lapolar.cl` y `www.abcdin.cl` redirigen las dos a
`www.abc.cl`**, con byte-count idéntico (1.317.663 B en las dos). Son **el mismo
sitio**. (El ápex `lapolar.cl` ni siquiera carga: `CERTIFICATE_VERIFY_FAILED,
certificate has expired`; y `tiendaslapolar.cl` no resuelve.)

⇒ Las tiendas Salesforce son **`hites.com`, `tricot.cl` y `abc.cl`**. El retorno
por adaptador escrito sigue siendo el mejor que queda en el plan — pero es 3×, no
4×. Si La Polar opera hoy bajo otro dominio, esta Fase 0 no lo encontró y habría
que buscarlo antes de dar la vertical por cerrada.

### Lo confirmado

| | hites.com | tricot.cl | abc.cl |
|---|---|---|---|
| `demandware` en la home | **1.840** | 212 | 902 |
| `/on/demandware.store/` | 33 | 15 | 14 |
| Site ID | `HITES` | `TRICOT_CL` | `Abc` |
| `.product-grid` | 1 | 1 | 1 |
| `robots.txt` | 200, 60 disallow | 200, 28 disallow | 200, 43 disallow |
| `Crawl-delay` | ninguno | ninguno | ninguno |

**Las tres son el mismo SFCC y comparten la forma del listado**: URLs de
categoría limpias y jerárquicas (`/accesorios/accesorios-deportivos/`,
`/accesorios/hombre/billeteras`, `/belleza/cuidado-capilar/`) y grid con
`[data-pid]`. ⇒ **un solo `salesforce_family.py` las cubre**, con host y
selectores por tienda.

### La paginación, y la ruta permitida

Las tres paginan con **`?start=N&sz=M` sobre la URL de categoría limpia**, y eso
está **permitido** por los tres `robots.txt`. Lo que cada una prohíbe es otra
ruta al mismo dato:

- **abc.cl**: `Disallow: /on/demandware.store/*` y `Disallow: /*cgid=*` — o sea
  el controlador SFCC y el parámetro de categoría. La home **ofrece las dos
  rutas** (`.../Search-UpdateGrid?cgid=belleza&...&start=0&sz=36` y
  `/belleza/?start=0&sz=36`); hay que usar la segunda.
- **hites.com**: `Disallow: /*Search-UpdateGrid*` y `Disallow: /busqueda*`.
- **tricot.cl**: `Disallow: /search*` y `Disallow: /*?prefn*` (los filtros).

Verificado que paginan de verdad: **solape entre página 1 y página 2 = 0 en las
tres**. Y `sz` es honrado (en Tricot parece clampear a 60).

### ⚠️ Dos trampas de parseo, medidas

- **Hites mezcla carruseles de recomendados con el grid.** `[data-pid]` cuenta
  **108** cuando `.product-tile` cuenta **36**, y con `sz=100` da 144 pids / 91
  únicos. Contar `[data-pid]` metería productos recomendados dentro de la
  categoría — la clase de bug "la página tiene la forma correcta y el contenido
  equivocado", pero **adentro** de la página. **El selector correcto en Hites es
  `.product-tile`.**
- **ABC repite el `data-pid` tres veces por tile**: 108 pids para 36 productos
  únicos, 300 para 100. Deduplicar por pid, no contar nodos.

### ⚠️ ABC cotiza por zona de inventario — el caso Construmart

El endpoint de paginación que ABC publica en su propia home lleva:

```
zone=inventory_LaPolar_whven%7ct_ecom_metropolitana
```

O sea **su inventario (y probablemente su precio) está scopeado por zona**, y la
que sirve por defecto es la Metropolitana. Es el caso Construmart exacto: la
serie que recolectemos **es la de esa zona**, y cambiar la zona después
**invalida el histórico entero de la tienda**, porque el p50 de un SKU mezclaría
dos zonas. Hay que fijarlo explícitamente en el adaptador y documentarlo, igual
que `ConstrumartAdapter.CUSTOMER_GROUP_ID`.

Como lateral: `inventory_LaPolar_...` es evidencia independiente de que `abc.cl`
es la operación fusionada que absorbió los dominios de La Polar y ABCDin.

### Las llaves salen de la navegación, y ya me cobró el atajo

Medido el 2026-11-05 leyendo el menú de cada tienda:

| tienda | categorías de nivel 1 | de nivel 2 |
|---|---|---|
| hites | **23** | 161 |
| tricot | **6** | 49 |
| abc | **17** | 91 |

Hites: `/accesorios/`, `/bebes/`, `/belleza/`, `/celulares/`, `/construccion/`,
`/deportes/`, `/dormitorio/`, `/electro-hogar/`, `/escolares/`, `/hogar/`,
`/hombre/`, `/muebles/`, `/mujer/`, `/musica-y-libreria/`, `/navidad/`,
`/ninos-y-jugueteria/`, … Tricot: `/accesorios`, `/calzado`, `/hombre`,
`/infantil`, `/mujer`, `/ropa-interior`. ABC: `/belleza/`, `/calzado/`,
`/deportes/`, `/dormitorio`, `/hogar/`, `/hombre`, `/linea-blanca/`, `/muebles/`,
`/mujer`, `/ninos/`, `/otras-lineas/`, `/tecnologia/`, …

⚠️ **Y la regla "la llave la publica la tienda, no la adivina uno" me cobró el
atajo en el primer intento**: probé `hites.com/calzado/` por analogía con ABC y
dio **HTTP 404** — Hites simplemente no tiene esa categoría, su calzado cuelga de
`/hombre/`, `/mujer/` y `/deportes/`. Es la misma lección que la llave
`cat2049/Audifonos` de Falabella, con la diferencia barata de que acá falla
ruidosamente con un 404 en vez de servir el contenido equivocado con un 200.

⚠️ **ABC publica la misma categoría con y sin barra final** (`/belleza` y
`/belleza/`, `/hombre` y `/hombre/`, `/mujer` y `/mujer/`, `/dormitorio` y
`/dormitorio/`). Dos `store_key` que son la misma categoría: si entran las dos,
cada listing pesa el doble en su propio p50. Hay que normalizar la barra al
construir la migración.

### El canario exacto: probablemente NO

- **abc.cl** declara el total y parece confiable: "989 productos" en `/belleza/`.
- **tricot.cl** declara "30 productos" en `/accesorios/hombre`, pero enumerando
  dan ~69 (36 + 33). Ese "30" **no es el total**.
- **hites.com** no expone un total que ninguno de los cuatro patrones probados
  encontrara.

⇒ Con dos de tres sin total confiable, el criterio del plan (§3.1: implementarlo
solo si lo enumerado iguala lo declarado de forma **estable**) dice **no
implementar el canario exacto en esta familia**, y quedarse con el estadístico
más el aviso `catalogo_mas_grande_que_la_ventana`. Mismo camino que la familia
Falabella y Cencosud. **Pendiente de confirmar** con una medición dedicada.

### El barrido del 2026-11-05: qué quedó medido y qué era mi parser fallando

Barrí 2 paraguas + hasta 4 hojas por tienda, con tope de 6 páginas
(`sz` 36/60/36), dos recorridos del primer paraguas. **184 MB en Hites, 54 en
Tricot, 116 en ABC: 354 MB en 392 s.** Eso ya es un dato de la pregunta 12 — es
la vertical más cara en bytes de todo el plan.

🟢 **Lo único que quedó medido limpio, y es importante: el orden es estable en las
tres.** Dos recorridos del mismo paraguas, comparando conjuntos de `pid`:

| tienda | paraguas | p1 | p2 | **Jaccard** |
|---|---|---|---|---|
| hites | `/electro-hogar/` | 216 | 216 | **1,0000** |
| tricot | `/accesorios` | 360 | 360 | **1,0000** |
| abc | `/tecnologia/` | 216 | 216 | **1,0000** |

Es la pregunta que más caro cuesta ignorar y las tres la pasan. (Con el `srule`
de relevancia que ABC manda por defecto, era el riesgo principal.)

🔴 **Y lo demás de ese barrido NO sirve, porque era mi parser y no las tiendas.**
Lo digo explícito para que nadie lo tome de la tabla: reporté `con_precio = 0%` en
Hites, `con_antes = 0%` en ABC y `unavailable = 81,9%` en Hites, y **los tres son
artefactos míos**. Lo que salió de mirarlo con lupa:

**⚠️ El `unavailable` de Hites NO es stock — es método de envío, el engaño de
Tottus otra vez.** El HTML es
`<svg class="icon" title="<span class='font-weight-bold unavailable'>(No Disponible)"><use xlink:href="#shipping-icon-express">`:
dice que el **despacho express** no está disponible. Y `available` es
`<span class="font-weight-bold available">Ver Disponibilidad</span>`, un link, no
un estado. **36 de 37 tiles traen las dos clases a la vez**, así que contar la
palabra da ruido. Si eso entraba al adaptador, el `in_stock` de Hites quedaba
decidido por la disponibilidad del courier.

**🟢 Pero Hites SÍ tiene señal de stock en el listado, y está en otro lado**: el
nodo `.price` contiene el texto **`¡SIN STOCK!`**. En `/dormitorio/camas/` lo
traen los 37 tiles. Hay que verificarlo contra una categoría con stock mezclado
—la lección de `isOutOfStock`: un lector se prueba contra fichas agotadas, no
contra las que están a la venta— pero la señal existe y es barata.

**⚠️ Y el hallazgo más caro: Hites publica TRES precios por tile, y el más
prominente exige su tarjeta.** Medido sobre `/dormitorio/camas/`:

| nodo | contenido | qué es |
|---|---|---|
| `.price-item.hites-price` | `43%$199.990` | **precio con tarjeta Hites** |
| `.price-item.sales.strike-through` / `.sales` | `37%$219.990` + `TODO MEDIO DE PAGO` | **el que paga cualquiera** |
| `.price-item.list.strike-through` | `Price reduced from Normal $34…` | el normal declarado |
| `.discount-price` | `43%` | el badge, que es **el de la tarjeta** |
| `.price-sales-text` | `TODO MEDIO DE PAGO` | **no es un precio**: es el rótulo |

Es el `cmrPrice` de Falabella en Hites, y la regla del sistema no cambia:
`price_effective` es el de **TODO MEDIO DE PAGO** y el `hites-price` va a
`price_card`. Tomar el nodo equivocado publica un precio que exige plástico de la
casa — y el `.discount-price` que la tienda muestra (43%) es el de la tarjeta, no
el real (37%). No todos los tiles traen `hites-price`: el tercero de la muestra no
lo tenía.

**⚠️ `.strike-through` es ambiguo en Hites**: en dos tiles matcheó el nodo de
`sales` y en un tercero el de `list`. Por eso mi `con_antes = 99,6%` no significa
nada. El selector tiene que ser el compuesto (`.price-item.list.strike-through`),
nunca la clase sola.

🔴 **La contención paraguas/hoja (pregunta 11) sigue sin respuesta, y por una
razón aritmética**: **todas** las categorías tocaron el tope de 6 páginas, así que
el paraguas y la hoja devuelven exactamente sus primeros 216 y cruzarlos no mide
contención, mide el orden. Para responderla hay que enumerar completo, y a 2-3 MB
por página de 36 productos eso son cientos de MB por categoría. **Es la medición
más cara que queda en el plan** y conviene hacerla sobre una categoría chica, no
sobre `/electro-hogar/`.

⚠️ **Varias hojas devolvieron `pagina_1_sin_tiles` de forma intermitente**
(`tricot/accesorios/hombre`, `/calzado/*`, `abc/tecnologia/computadores/`) — y al
menos `tricot/accesorios/hombre` **sí funciona**: pedida sola da 200 con 60 tiles,
18 veces seguidas sin fallar. O sea es intermitencia bajo carga, no una llave
inexistente. Antes de dar una hoja por vacía hay que reintentarla espaciada.

### Lo que falta medir antes de escribir el adaptador

Esta vertical quedó en **la mitad**. Medido: plataforma, robots, ruta permitida,
paginación real, selectores y la trampa de zona. **Sin medir**:

| # | Pregunta | Estado |
|---|---|---|
| 5 | Orden estable entre requests | 🔴 sin medir — y en SFCC el default suele ser un `srule` de relevancia (ABC manda `srule=Categoria`), así que **es el riesgo principal**, igual que fue Tottus |
| 7 | GTIN y en qué fracción | 🔴 sin medir |
| 8 | `price_normal` (y el ruido de la tarjeta de la casa, que en Hites y ABC es esperable) | 🔴 sin medir |
| 9 | Señal de stock, verificada **contra productos agotados** | 🔴 sin medir |
| 10 | Centinelas (precio máximo sobre el catálogo) | 🔴 sin medir |
| 11 | Llaves disjuntas sobre SKUs reales — hites publica **1.156** enlaces internos de categoría y abc **657**: hay mucho eje solapado que cruzar | 🔴 sin medir |
| 12 | Costo por pasada | 🔴 sin medir. ⚠️ Dato de alerta: **una sola página de categoría pesa 1,5 a 3,1 MB** en las tres. Con `sz=100` ABC dio 2,8 MB. Una familia de tres tiendas grandes a ese peso es el ítem más caro en bytes de todo el plan. |

---

## 3. Resumen de la vertical

| Tienda | Veredicto | Costo de implementación | Lo que falta |
|---|---|---|---|
| **Colloky** | 🟢 **entra** | **Una fila en `stores` + 4 `store_categories` + un fixture.** Cero líneas de adaptador: `vtex_family` la cubre tal como está | Decidir si va a `ropa-*` existente o a categoría propia por el ticket de $50k |
| **Hites / Tricot / ABC** | 🟢 **viables, no listas** | Un `salesforce_family.py` nuevo (3 tiendas) | Las 6 preguntas de arriba, empezando por el orden estable |
