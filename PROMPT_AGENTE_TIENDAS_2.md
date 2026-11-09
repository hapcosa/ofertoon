# Prompt — agente de tiendas, continuación del 2026-11-08

Pegá lo que está dentro del bloque.

---

```
Seguís en `feat/tiendas-bloqueadas` (worktree `~/servicios/ofertoon-bloqueadas`).
Tu investigación del 7-nov está bien hecha y tu resultado negativo era honesto.
Pero hay un precedente del propio repo que la vuelve positiva, y está medido.

LO PRIMERO: TU LECTURA DEL ROBOTS ERA CORRECTA
La re-medí yo el 2026-11-08 y **Tricot sí prohíbe `/*?start*` y `/*&start*`**.
Más todavía: el bloque nombra explícitamente a `ClaudeBot`, `Claude-SearchBot` y
`Claude-User`, así que no hay lectura permisiva posible. Hiciste bien en no
paginar y en corregir `INVESTIGACION_ropa.md`.
(Mi primer parseo dijo lo contrario y estaba mal: el archivo lista **18
`User-agent:` seguidos compartiendo un solo bloque de reglas**, y un parser que
resetea el flag en cada línea se queda con el último. Si escribís un lector de
robots, ese es el caso que hay que cubrir.)

PERO "SIN PAGINACIÓN" NO ES "NO CONECTABLE" — Y EL REPO YA TIENE EL PRECEDENTE
Tu ficha concluye que una categoría sin paginación no permite responder
cobertura, orden ni llaves. **Sparta está conectada exactamente así**, por la
migración 52 que escribiste vos: su robots prohíbe toda query string
(`Disallow: /*?`), así que `SpartaAdapter` corre con `paginates = False` y
`page_size = None`, ve siempre la página 1, y su techo de catálogo del 24-27%
está **declarado en el header** en vez de ser un problema. Kupfer y Construmart
usan la misma configuración.

Lo que cambia con `paginates=False` no es si la tienda entra: es que
  * la pregunta 4 se contesta "no pagina, por robots" y se cierra;
  * la pregunta 5 (**orden estable**) pasa a ser **la que decide la tienda**,
    porque si el orden rota, el catálogo nunca llega a `MIN_DAYS`. En Sparta se
    midió con ~15 min de separación real sobre 9 hojas: 8 con Jaccard 1,000;
  * la pregunta 6 se contesta con el total declarado por hoja, y la cobertura es
    "lo alcanzable", no "el catálogo".

LO QUE MEDÍ EL 2026-11-08 Y NO TENÉS QUE REHACER
  * `https://www.tricot.cl/sitemap_index.xml` → 5 sitemaps:
    `sitemap_0-product.xml` (**10.434 URLs de producto**),
    `sitemap_1-product.xml`, `sitemap_2-category.xml`, `sitemap_3-content.xml`,
    `sitemap_4.xml`. El robots **publica el sitemap** y no prohíbe las fichas.
  * `sitemap_2-category.xml` → **426 URLs de categoría, todas limpias y sin
    parámetros**. Hay vitrinas evidentes para descartar
    (`/homepage-carousel/...`, `/nueva-temporada/lo-nuevo`) y hojas reales
    (`/accesorios/mujer/bananos`, `/infantil/bebe-nina`, `/hombre/pijamas`).
  * `https://www.tricot.cl/accesorios/mujer/bananos` **sin un solo parámetro**
    responde 200 con productos: **10 `data-pid` únicos sobre 30 nodos
    `product-tile`**, y declara **30** en el texto.

⚠️ Ese último número es lo PRIMERO que tenés que resolver, porque decide todo lo
demás: **¿la página 1 trae 10 productos o 30?** Las dos lecturas son plausibles y
el repo tiene las dos precedentes: ABC repite el `data-pid` **tres veces por
tile** (lo medíste vos: 108 pids para 36 productos), y Hites mezcla carruseles de
recomendados en `[data-pid]` mientras `.product-tile` cuenta 36. Acá la razón es
exactamente 3:1, lo que apunta a la repetición tipo ABC — pero **medilo, no lo
deduzcas**: contá productos distintos por su URL de ficha, no por el atributo.

TU TRABAJO, EN ORDEN

1. **Resolver el 10-contra-30** sobre tres o cuatro hojas distintas. Si son 30 y
   el total declarado es 30, la hoja entra COMPLETA y el techo de Tricot es
   mucho mejor que el de Sparta.
2. **Medir el orden estable** con separación real de ~15 minutos (no
   back-to-back, para no medir la cache) sobre 8 o 9 hojas, al menos 5 de ellas
   con total declarado mayor que lo que trae la página. Jaccard por hoja. **Si el
   orden rota, Tricot no entra y ahí sí es un no definitivo** — es la pregunta
   que decide.
3. **Elegir llaves disjuntas** de las 426, descartando vitrinas y carruseles, y
   cruzar los SKUs reales entre pares. Mirá si Tricot repite el patrón de Sparta
   (tres ejes sobre el mismo catálogo) o si su árbol es limpio.
4. **Las cuatro preguntas que te faltan**, sobre la página 1 nomás: GTIN,
   `price_normal`, **stock** y centinelas. Para stock, el precedente también
   existe y es el de Sparta y Colloky: **medí si la tienda OCULTA los agotados en
   vez de marcarlos**. Si los oculta, el `in_stock` ciego no cuesta nada
   estructural (un producto que se agota desaparece y su serie queda con un
   hueco), y eso se verifica buscando vocabulario de agotado y el botón de
   agregar al carro en una hoja completa. Si los LISTA sin marcarlos, es el caso
   Paris/Falabella y ahí sí bloquea.
5. **ABC: la misma pregunta de stock es lo único que la separa de entrar.** Ya
   tenés 824 IDs estables en `/mujer/ropa-mujer/` con Jaccard 1,0000, 23 páginas,
   cero GTIN, 774/824 con `Normal` y máximo $29.990. Te falta **un agotado de
   control**: sin él no se sabe si la ausencia de señal significa "no hay
   agotados en esta hoja" o "los agotados se listan iguales". Buscá un producto
   agotado por su ficha y mirá qué trae su tile. Los 2 IDs que cruzan con calzado
   son 2 de 824: el precedente de Unimarc (1 de 8.212) dice que eso no justifica
   deduplicar entre llaves cuando las llaves mapean a categorías internas
   distintas — pero acá sí mapean distinto (`ropa-vestuario` vs `ropa-calzado`),
   así que **declaralo y elegí a propósito**, como se hizo con Sparta.
6. **Si Tricot y/o ABC pasan: migración 54**, con techo de cobertura declarado en
   el header, `publish_enabled = FALSE`, fecha de conexión y evaluación anotadas.
   Si no pasan, el entregable es la ficha con el veredicto fechado — que es un
   entregable válido y el de ayer lo fue.

LO QUE NO VALE LA PENA AHORA
  * **Imperial**: 520 persistente en las rutas de catálogo, tres mediciones en
    tres días. Es origen inestable y no hay nada que hacer sin otra fuente.
    Dejalo con su veredicto fechado.
  * **Spacestore**: tus 1.291 IDs en tres colecciones disjuntas son una tajada
    válida — el precedente es Rockford, 4 raíces de un catálogo mayor, declarado
    parcial en el header. Si querés cerrarla, es migración 55 y alcanza con
    declarar el techo. Pero Tricot/ABC valen más: alimentan **Vestuario**, que es
    el tema con más lugares vacíos.

POR QUÉ VESTUARIO IMPORTA, MEDIDO
El canal tiene cuota 20 por tema desde la migración 55 (ocho temas, techo 160/día)
y los topes finos subieron a 20 para que no estorben. Pero el 7-nov **Vestuario
publicó 0 de 5** y Belleza 0 de 3: no es el detector, son temas sin candidatos
maduros. Tricot y ABC son las dos tiendas que mejor los llenan.

NÚMEROS DE MIGRACIÓN
La **54** es tuya y sigue libre. Verificalo igual, con esto y no con `ls`:

    for d in ~/servicios/ofertoon*; do
      find "$d/migrations" -maxdepth 1 -name '*.sql' -printf '%f\n' 2>/dev/null
    done | grep -oE '^[0-9]+' | sort -n | tail -1

Tomadas: 47 unimarc · 50 rockford · 51 mercadopago · 52 sparta · 53 piso de 10 ·
55 cuota 20. La 49 nunca se escribió. **Si necesitás dos, tomá 54 y 56.**

QUÉ NO TOCAR
  * `subscriptions/` y `migrations/51` → del agente de pagos.
  * `migrations/53`, `migrations/55`, `curation/ranker.py` y la regla 5 de
    CLAUDE.md → de `feat/piso-diez`.
  * 🔴 **Nunca aplicar migraciones ni reiniciar servicios.** Es del dueño, y ya te
    lo pidió explícitamente.
  * En los `.md` compartidos: **agregá, nunca reordenes**.

CÓMO SE TRABAJA ACÁ
  * **Verificá el efecto, nunca el mensaje.**
  * **Una prueba sin caso de control es un falso verde** — y el agotado de ABC es
    exactamente el caso de control que falta.
  * **Un veredicto de acceso tiene fecha**, y el robots de Tricot lo demuestra:
    cambió entre el 5 y el 7 de noviembre.
  * **Un pytest a la vez por base**, y avisá antes de una corrida larga.
  * **No commitees ni pushees salvo que te lo pidan.**
  * **Avisá cualquier decisión que tomes por tu cuenta.** Honestidad 100%: si
    algo falla, decilo con el output. Un resultado negativo bien medido vale más
    que una tienda conectada a medias.
```
