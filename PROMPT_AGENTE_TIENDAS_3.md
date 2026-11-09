# Prompt — agente de tiendas, continuación del 2026-11-09

Pegá lo que está dentro del bloque.

---

```
Seguís en `feat/tiendas-bloqueadas` (worktree `~/servicios/ofertoon-bloqueadas`).
ABC y Tricot están integrados a `main` (migración 54) y tu trabajo pasó la
revisión: `publish_enabled` nace FALSE y afuera del `ON CONFLICT`, los dos
adapters resuelven, y el stock quedó con caso de control real — un agotado con
botón deshabilitado que NO aparece entre los 820 IDs. 990 passed con los topes
en 20 y el piso en 10.

⚠️ **La 54 todavía NO está aplicada en producción.** Mergeá `main` antes de tocar
nada: trae las migraciones 53 y 55, los topes del ranker en 20 y un fix de
`scrapers/base.py` que te afecta directo (abajo).

ESTADO REAL, MEDIDO EL 2026-11-09 13:33 UTC — y lo primero que hacés es volver
a medirlo
  - **53 migraciones aplicadas. Pendiente: la 54, la tuya.** Desde un árbol que
    no tenga todos los archivos, `migrate.py --status` contesta "sin pendientes"
    y es falso: la verdad está en `SELECT filename FROM schema_migrations`.
  - Las cinco tiendas que se abrieron el 9-nov **ingirieron bien**:

        unimarc    7.697 items   8 corridas   1 FAILED
        rockford   2.926 items   4 corridas   0 failed
        sparta     1.203 items  63 corridas   0 failed, 29 partial
        pc-express   463 items   8 corridas   0 failed
        ripley        95 items   1 corrida    1 partial

  - El canal publicó **29 posts** (contra 22-23 los días previos), con la cuota
    en 20 por tema y los topes finos en 20.

LO QUE TE TOCA MIRAR DE LO TUYO, Y ES LO PRIMERO

1. **Los 29 `partial` de Sparta dicen `canario: 36 de 94 que declara la tienda
   (paginación incompleta)`.** Eso NO es un error de tu adaptador: Sparta no
   pagina por su `robots.txt`, así que ver 36 de 94 es el techo esperado y está
   declarado en el header de tu migración 52. **Pero el canario no lo sabe**, y
   por eso los marca `partial` en cada pasada, para siempre.
   Dos consecuencias, y las dos te van a costar tiempo si no las resolvés ahora:
     - `runner.pasadas_flacas` y el canario quedan con 29 `partial` permanentes
       de ruido, y un ruido permanente es un canario que se ignora;
     - **Tricot va a hacer exactamente lo mismo** en cuanto se aplique la 54,
       porque tampoco pagina. Vas a sumar nueve `partial` más por pasada.
   La pregunta a contestar, con el código delante: ¿el canario distingue una
   tienda que **no puede** paginar de una que paginó mal? Si no, es una guarda
   que no puede cumplir su función en estas tiendas, y la salida es declararlo
   por tienda —algo como "el total declarado no es alcanzable, el techo es la
   página 1"— en vez de dejar que mienta. **Medí y proponé; cambiar una guarda es
   decisión del dueño.**

2. **El `failed` de Unimarc ya está arreglado y te explica un patrón.** Era
   `StringDataRightTruncationError` sobre `character varying(14)`: un GTIN más
   largo que `listings.gtin_raw`, que **hacía fallar la llave entera** y perdía
   ~1.700 observaciones por pasada. El arreglo está en `main`
   (`scrapers/base.py`, `GTIN_MAX_CHARS = 14`): ahora el GTIN se descarta y el
   producto entra sin él.
   Lo que te importa: **ABC y Tricot emiten `gtin=None` en los 820 y 465 tiles
   que midieron**, así que no te toca hoy — pero si algún día una de las dos
   empieza a traer el campo, ya está cubierto. Y la lección general vale para
   cualquier adaptador nuevo: un campo opcional que no cabe en su columna no
   degrada el copy, **tira la serie de esa llave**.

TU TRABAJO NUEVO

3. **SPACESTORE, que es lo que queda y ya tiene fuente comprobada.** Tus tres
   colecciones disjuntas suman 1.291 IDs sobre 59.650 URLs de producto en el
   sitemap, con `all` topando en 25.000. Eso es una **tajada**, y el repo tiene
   el precedente exacto: Rockford entró con cuatro raíces de un catálogo mayor,
   declarado parcial en el header de la 50. No hace falta cobertura total para
   conectar — hace falta **declarar el techo** y que las llaves sean disjuntas.
   Lo que falta antes de escribir la migración **56**:
     - las preguntas que no contestaste de las doce: GTIN, `price_normal`,
       **stock con caso de control** (el que te sirvió en ABC: buscá un agotado
       por su ficha y mirá si aparece en el listado) y centinelas;
     - el costo por pasada en requests y MB, que es lo que decide si entra en el
       presupuesto — y ojo que la pasada ya está en **110 min proyectados sobre
       los 120 de `PASS_WINDOW`** con 802 llaves, así que una tienda que sume
       muchas llaves hay que dimensionarla antes y no después;
     - a qué categorías internas mapea. Si cae en `ropa-*`, alimenta
       **Vestuario**, que hoy publica 5 de 20.

4. **SI SPACESTORE NO DA: Kliper, con la medición rehecha.** Su adaptador ya
   existe (`magento_html:KliperAdapter`) y lo único que la frena es presupuesto y
   duplicación. Los 706 requests / 35,7 min son de un handoff viejo: **re-medilos
   antes de citarlos**. Y la razón de fondo sigue en pie y es del dueño, no tuya:
   Kliper distribuye `thenorthface`, `mammut`, `marmot` y `andesgear`, que están
   las cuatro conectadas, así que sería el mismo catálogo por quinta vez. **Medí
   el solapamiento real de SKUs contra esas cuatro y reportá el número** — con
   eso el dueño decide; sin eso es una discusión de opiniones.

NÚMEROS DE MIGRACIÓN
Tomadas: 47 · 50 · 51 · 52 · 53 · 54 (tuya) · 55. La 49 nunca se escribió. La
**56 es tuya**. Verificalo igual, con esto y no con `ls` de tu árbol:

    for d in ~/servicios/ofertoon*; do
      find "$d/migrations" -maxdepth 1 -name '*.sql' -printf '%f\n' 2>/dev/null
    done | grep -oE '^[0-9]+' | sort -n | tail -1

QUÉ NO TOCAR
  * `subscriptions/`, `alerts.py` y `migrations/51` → del agente de pagos.
  * `migrations/53`, `55`, `curation/ranker.py` y `scrapers/base.py` → de
    `feat/piso-diez`. ⚠️ Si tu adaptador necesita un largo máximo de campo,
    **importalo de `base.py`** en vez de copiarlo: una copia queda vieja en
    silencio.
  * 🔴 **Nunca aplicar migraciones ni reiniciar servicios.** Es del dueño. Y si
    alguna vez lo autoriza, **mirá antes si hay una pasada en vuelo**: el ciclo de
    12 h arranca a una hora derivada de la última pasada, así que el momento más
    probable de que haya una es justo cuando desplegás. Está en TRAMPAS **F**.
  * En los `.md` compartidos: **agregá, nunca reordenes**.

CÓMO SE TRABAJA ACÁ
  * **Verificá el efecto, nunca el mensaje.**
  * **Una prueba sin caso de control es un falso verde.** El agotado de ABC fue
    el mejor trabajo de tu sesión anterior: repetilo en Spacestore.
  * **Un veredicto de acceso tiene fecha.** El robots de Tricot cambió entre el 5
    y el 7 de noviembre.
  * **Un pytest a la vez por base** (`ofertas_test_bloqueadas`), y avisá antes de
    una corrida larga: hay tres agentes sobre el mismo Postgres `:5436`, que
    además sirve producción.
  * **No commitees ni pushees salvo que te lo pidan.**
  * **Avisá cualquier decisión que tomes por tu cuenta.** Honestidad 100%: un
    resultado negativo bien medido vale más que una tienda conectada a medias, y
    el de Tricot lo demostró.
```
