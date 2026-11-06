# TIENDAS_PROHIBIDAS.md

Tiendas que **no se pueden conectar**, con la razón medida y la fecha de la
medición. Escrito el **2026-11-04** durante la Fase 0 de `PLAN_EXPANSION.md`.

Existe para que nadie vuelva a gastar una sesión en una tienda ya descartada —
pero también para lo contrario: este repo se equivocó **siete veces** declarando
bloqueada una tienda viable (Tottus, Jumbo, Santa Isabel, Imperial, Spacestore, y
el 2026-11-05 **Unimarc y PC Express**).

⚠️ **Y la séptima y la sexta las había escrito yo en este mismo archivo, horas
antes.** Así que la advertencia hay que leerla fuerte: **ningún "no" de acá es
permanente, ni siquiera los marcados 🔴 FIRME.** Lo que sí es permanente es el
patrón del error, y en los siete casos fue el mismo: **se midió el host o la ruta
equivocados y se concluyó sobre la tienda**.

| caso | lo que se midió | lo que había que medir |
|---|---|---|
| Tottus | su API VTEX (503) | que **no es VTEX**: corre la plataforma de Falabella |
| Jumbo, Santa Isabel | el sitemap viejo | la navegación vigente |
| Imperial | `www` (520) | el **ápex** con `BROWSER_HEADERS` (200) |
| Spacestore | `www` (403) | el **ápex** (200 ×4) |
| **PC Express** | `pcexpress.cl` (403) — **que es otro sitio** | `www.pc-express.cl`, que **redirige 301 a `tienda.pc-express.cl`** (200) |
| **Unimarc** | la home y el `robots.txt` (404) | la **página de categoría**, que sirve `__NEXT_DATA__` |

## Cómo leer la tabla

| marca | significa |
|---|---|
| 🔴 **FIRME** | Bot management de verdad. Lo único que queda es evasión, y esa es la línea que el repo decidió no cruzar. **No volver a intentar.** |
| 🟠 **POLÍTICA** | Técnicamente alcanzable, prohibido por la propia tienda en su `robots.txt`. No es un fallo: es un "no" explícito y se respeta. |
| 🟡 **RE-MEDIR** | El "no" heredado NO se sostiene, o el origen está inestable. Hay trabajo concreto por hacer. |
| ⚫ **NO EXISTE** | No es una tienda: dominio muerto, sitio congelado, o cambió de rubro. Nada que conectar. |

---

## 🔴 FIRME — bot management, no volver a intentar

Re-verificadas una por una el **2026-11-04** con `BROWSER_HEADERS` (el juego
completo, el que destrabó Tottus y Nike). Todas siguen igual que en
`PLAN_TIENDAS.md` §Fase 6.

| Tienda | Medición del 2026-11-04 | Por qué es firme |
|---|---|---|

| **Decathlon** (`decathlon.cl`) | **403** en www, ápex **y `robots.txt`** | Cloudflare. Un 403 en el propio `robots.txt` es la firma de que el borde no mira la ruta: no hay nada que negociar. Sigue siendo "la más valiosa de la categoría y la más difícil". |
| **Nice One** (`niceone.cl`) | **403** en www, ápex y `robots.txt` | Idem Decathlon. |
| **MTS** (`mts.cl`) | **403** en www, ápex y `robots.txt` | Idem Decathlon. |

| **Adidas** (`adidas.cl`) | home `www` **403**, ápex **403**, `robots.txt` **200** | Akamai. Que el `robots.txt` responda y la home no es exactamente el caso Adidas ya documentado: el borde deja pasar el archivo estático y nada más. |
| **Nice One** (`niceone.cl`) — re-confirmado | **403 con `cf-mitigated: challenge`** (medición independiente del 2026-11-05) | Es Cloudflare marcando el request como desafío, o sea bot management explícito. Lo que queda es pedir un feed o un acceso acordado, no insistir. |
| **MercadoLibre** (`api.mercadolibre.com`) | no re-medido hoy | **403 sin OAuth desde 2025.** Y aunque se consiguiera el token, es marketplace: el precio es por vendedor, así que la baseline por SKU se rompe — una serie que cambia de vendedor no es una serie. El bloqueo es la segunda razón, no la primera. |

---

## 🟠 POLÍTICA — la tienda nos dice que no, por escrito

| Tienda | Qué dice | Medición del 2026-11-04 |
|---|---|---|
| **Doite** (`doite.cl`) | `Disallow: /collections/*` en el bloque `User-agent: *` | **Es el hallazgo de hoy y contradice `PLAN_EXPANSION.md` §2.1**, que la daba por viable con "`/products.json` verificado". Verdad a medias: el endpoint funciona, pero es `/collections/{handle}/products.json` — exactamente lo que su robots prohíbe (línea 261, dentro del bloque `*` que va de la 16 a la 308). Su robots trae **287 `Disallow` en nuestro bloque**, incluidos 207 handles de colección nombrados uno por uno: es una política editada a mano ("Editado por Cheil Chile"), no un descuido. Y **la vía alternativa está cerrada por el servidor**: `/products.json` de raíz —que su robots **no** prohíbe— responde **403**. Dos razones independientes, cada una suficiente. |
| **Lider** (`lider.cl`) | `Disallow: /search*` | home **200** (744 KB). Técnicamente funciona: `super.lider.cl/search?q=` devuelve 200 con precios en `__NEXT_DATA__`. Pero esa es la ruta que su robots prohíbe, y el repo ya decidió no apoyarse en el tecnicismo. Queda la vía limpia de sus cuatro sitemaps, al costo que `PLAN_TIENDAS.md` §Lider documenta: **tajada chica y elegida a mano**, no la tienda completa. |

⚠️ **Sparta no está en esta lista, y conviene decir por qué**: su `robots.txt`
trae `Disallow: /*?`, `/*?*`, `/*&*`, `/*?limit=*` y
`Disallow: /*product_list_limit=`, o sea **ninguna query string está permitida**.
Eso no la prohíbe — prohíbe **paginarla**, que es otra cosa. Entra con la
configuración de Kupfer (`paginates=False`, `page_size=None`) y con el techo de
cobertura que eso implica (~24% del catálogo). Ver
`INVESTIGACION_deporte_outdoor.md`.

---

## ✅ CORREGIDAS el 2026-11-05 — eran viables y estaban acá como firmes

Las dos las descubrió otro agente el 5-nov y las **re-verifiqué yo** con los
headers del repo, porque la regla es verificar y no heredar. Las dos dan 200.

### Unimarc — ✅ conectada (adaptador probado el 2026-11-06)

> **Cerrada.** Ya no pertenece a este documento: tiene adaptador, fixtures, 33
> tests y la migración 47 escrita. La investigación completa —las doce preguntas,
> las ocho llaves verificadas disjuntas sobre SKUs reales y el canal de venta,
> que era el riesgo real— está en
> [`research/2026-11-06/INVESTIGACION_unimarc.md`](research/2026-11-06/INVESTIGACION_unimarc.md).
> Lo de abajo se conserva como el registro de por qué el veredicto viejo era
> falso, que es la parte que no hay que perder.
>
> Dos cosas de abajo quedaron **precisadas** por esa medición: el precio **sí
> depende de la sucursal** (del `salesChannel`, y el del anónimo es el 39), y de
> los dos UAs que acá figuran como equivalentes, `BROWSER_USER_AGENT` **a secas
> da 403 las 4 veces** — pasan el identificable y `BROWSER_HEADERS` completos.

**El bloqueo histórico ya no describe la fuente.** `www.unimarc.cl/` responde
**200 con 1,86 MB y `__NEXT_DATA__`, con los dos UAs** (`DEFAULT_USER_AGENT` y
`BROWSER_HEADERS`), y la página de categoría
`/category/lacteos-huevos-y-refrigerados` también: 200, 310 KB, con
`__NEXT_DATA__`.

⚠️ **Mi error fue leer su `robots.txt` como señal de bloqueo.** Da **404 y
redirige a `/404`** — eso no es un bloqueo del catálogo, es que no publica
`robots.txt`. Y los "once accesos probados" que `PLAN_TIENDAS.md` registraba
apuntaban a su **API VTEX vieja**, que efectivamente falla; el catálogo de hoy no
pasa por ahí.

Lo medido por el otro agente (ver `research/2026-11-05/INVESTIGACION.md` en el
repo principal) y que no hay que volver a medir:

- El payload está en `props.pageProps.dehydratedState.queries`, query
  `productsSearch-client`, con `availableProducts`, `notAvailableProducts` y
  `resource` (el total como texto).
- **Pagina con `?page=N`**: 0-49, 50-99. Una raíz declaró **719** y el recorrido
  dio **719 SKU únicos sin duplicados** en 15 páginas. Fin de paginación
  verificado además con una subcategoría de 33 cuya página 2 vino vacía.
- **EAN en 719 de 719** — cobertura total, y en supermercado eso es lo que el
  cross-store necesitaba.
- 716 declaran cantidad disponible > 0.

⚠️ Tres cosas que el implementador no puede ignorar, y las dos primeras son del
dominio del detector, no del adaptador:

1. **107 de 719 traen `itemsRequiredForPromotion`**: son promociones de
   multicompra. **Convertir un "3 × $2.000" en un precio unitario sin condición es
   publicar una oferta falsa**, que es exactamente lo que este proyecto existe
   para no ser.
2. **243 llevan etiqueta Club Unimarc.** Decisión del dueño del 2026-11-05:
   **el Club cuenta como oferta**, porque ser Club es solo dar el RUT y cualquiera
   puede. **No es tarjeta de la casa** y no va a `price_card` — pero el copy tiene
   que conservar la condición visible. La etiqueta vive en
   `priceDetail.promotionalTag.text`, y ⚠️ **`membership` viene vacío en ofertas
   que sí dicen Club**, así que mirar ese arreglo no alcanza.
3. **El recorrido fue anónimo, sin sucursal fijada.** La home declaraba
   `salesChannel=39` pero no está demostrado que eso valga para todas las
   categorías. Es el riesgo Construmart: si el precio es por sucursal, **la serie
   es de esa sucursal** y cambiarla después invalida el histórico. Hay que fijar y
   verificar el contexto antes de conectarla.

### PC Express — 🟢 viable, bajo subdominio

**`pcexpress.cl` da 403 y es otro sitio.** El real es **`pc-express.cl`**, con
guión, y su `www` **redirige 301 a `tienda.pc-express.cl`**, que responde **200
con 261 KB y 67 precios** usando `DEFAULT_USER_AGENT`.

Mi error fue doble y vale anotarlo entero: primero probé el dominio equivocado
(`pcexpress.cl`), después encontré el correcto en una lista de competidores **y
nunca seguí su redirección**. Es el mismo principio que la llave
`cat2049/Audifonos` de Falabella, un nivel más arriba: **el host lo publica la
tienda, no lo adivina uno** — y cuando hay un 301, el destino es el host.

Pendiente: las doce preguntas. Hoy solo está respondida la 1 a medias (borde y
host), y nada de plataforma, robots del subdominio, paginación ni llaves.

## 🟡 RE-MEDIR — el "no" heredado no se sostiene

| Tienda | Veredicto heredado | Lo que se midió el 2026-11-04 |
|---|---|---|
| **Imperial** (`imperial.cl`) | ❌ "403 de Akamai. **Descartada: es bloqueo, no caída**" (`PLAN_TIENDAS.md` §504) | **El veredicto es incorrecto.** El ápex da **HTTP 200 con 456 KB, 4 de 4 intentos, con `BROWSER_HEADERS`** — y **403 las 4 veces con `DEFAULT_USER_AGENT`**. O sea es el patrón Tottus/Nike (403→200 con headers completos), no un WAF cerrado. Su `robots.txt` en `www` responde **200 y es permisivo**: 14 `Disallow`, todos de carrito, cuenta y búsqueda, sin `Crawl-delay`, y **`Allow: /` explícito para ClaudeBot, GPTBot y PerplexityBot**. Declara sitemap. Plataforma identificada: **Oracle Commerce Cloud** (su bundle es `/storefront/occ-public/esm/min/client-*.js`), que expone una API pública de storefront en `/ccstore/v1/*`. <br>⚠️ **Pero el origen está inestable**: en la misma sesión, `/ccstore/v1/*`, `/sitemap.xml` y el `robots.txt` del ápex dieron **526** y los mismos del `www` dieron **520** — mientras la home seguía en 200. Cloudflare 520/526 es error de origen, no bloqueo. **Acción**: re-medir en otra sesión y probar `/ccstore/v1/collections` y `/ccstore/v1/products` cuando el origen esté arriba. Si responden, Imperial es una familia nueva (`occ_family`) y no una tienda bloqueada. |
| **Spacestore** (`spacestore.cl`) | ❌ 403 (medido hoy mismo, en la primera sonda) | **El 403 era del `www`.** El ápex `https://spacestore.cl/` da **200 las 4 veces con los tres juegos de headers** (`DEFAULT_UA`, `BROWSER_UA`, `BROWSER_HEADERS`). Mismo error de método que Imperial: probar un solo host y concluir sobre la tienda. Queda pendiente su plataforma: `/products.json` da 403 y no responde ninguna API conocida; sitemap 200. |
| **Rockford** (`rockford.cl`) | sin auditar | DNS **resuelve**, pero el TLS falla: `ssl_verify_result=20` (**certificado inválido o cadena incompleta**). No es un bloqueo ni un dominio muerto — es un certificado roto, y el mismo síntoma que tiene hoy el ápex de `lapolar.cl` (`CERTIFICATE_VERIFY_FAILED: certificate has expired`). Re-medir; si persiste, no se conecta, porque bajar la verificación de TLS no es una opción. |

---

## ⚫ NO EXISTE — no hay tienda que conectar

| Dominio | Qué es en realidad (2026-11-04) |
|---|---|
| **`dafiti.cl`** | **Dafiti cerró su operación chilena.** El ápex no resuelve por DNS; `www.dafiti.cl` devuelve 200 con 5.776 bytes y el título **"Gracias por todo, Chile ❤️ \| Dafiti"**. `PLAN_EXPANSION.md` §2.4 la listaba como marketplace a evaluar: la pregunta no se llega a hacer. |
| **`mountain.cl`** | **No es un e-commerce, y además está congelado.** Es "GRUPO MOUNTAIN - Servicios Profesionales" (piscinas, toldos), y el HTML trae el comentario `Mirrored from mountain.cl/home/ by HTTrack Website Copier/3.x, Wed, 16 Feb 2022` — una copia estática de **febrero de 2022** servida como sitio. El plan lo tenía como "Mountain, 200 sin determinar": queda determinado. |
| **`zmart.cl`** | **Cambió de rubro.** Redirige (302) a `botin.cl`, "El Botín del Alicanto \| Juguetes, cartas TCG", servido por Netlify. Ya no es la tienda de hardware que el plan listaba. |
| **`reifstore.cl`** | **DNS no resuelve.** |
| **`pcmix.cl`** | **DNS no resuelve.** |
| **`dinamicpc.cl`** | **DNS no resuelve.** |

---

## Lo que no es una prohibición pero cuesta igual

Dos tiendas que entran, con una restricción que hay que respetar y que se
confunde fácil con un bloqueo:

- **Megabytes** (`megabytes.cl`) — **funciona SOLO con `DEFAULT_USER_AGENT`**:
  200 las 4 veces. Con `BROWSER_USER_AGENT` y con `BROWSER_HEADERS` da
  `RemoteProtocolError` las 4 veces (el servidor corta la conexión). Es el
  **patrón inverso al de Prat y al de Easy**: acá lo que rompe es el juego de
  headers de navegador, no el UA identificable. Vale como regla general: ante un
  fallo de transporte, **probar también el UA identificable** — el reflejo de
  escalar a `BROWSER_HEADERS` puede ser justamente la causa.
- **Winpy** (`winpy.cl`) — declara **`Crawl-delay: 5`**, no 10 como dice
  `PLAN_EXPANSION.md` §1. Son `rate_limit_rps = 0.2`, el mismo presupuesto que SP
  Digital, que está conectada. El plan la daba como posible descarte por costo de
  fetches: con 5 ese argumento se cae a la mitad.
