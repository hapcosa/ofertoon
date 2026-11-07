# Backtest del 2026-11-06 — los θ medidos y la decisión que esperan

Corrida: `python -m pricing.backtest --from 2026-08-15 --to 2026-10-07
--exclude-day 2026-09-18 --exclude-day 2026-09-19 --exclude-day 2026-09-29`.
51 días de mercado, 135.880 listings, ~25 min.

Se escribe acá porque el número que importa —el θ que pasaría el gate— es
**evidencia medida esperando una decisión de producto**, y hasta hoy vivía solo
en el prompt de traspaso de la sesión que lo corrió.

## Lo medido

Solo **7 de las 17** categorías son medibles en ese rango: el resto no tiene
30 días de serie **más** 30 de futuro para etiquetar, y ahí un 0 no significa
nada (CLAUDE.md §Pasos 2).

    categoría            θ hoy   señ./día  precisión  gate   θ que pasaría
    ferre-herramientas   0.250      3.2      91.3%     ✓     0.25 (ya está)
    tecno-celulares      0.150      4.9      93.3%     ✓     0.15 (ya está)
    tecno-tv             0.180    2.3-4.3   93-97%   borde   0.15
    hogar-electro        0.200      2.5      95.3%     ✗     0.15
    tecno-notebooks      0.150      2.5      93.8%     ✗     0.10
    tecno-componentes    0.150      2.3      90.6%     ✗     0.10
    ferre-jardin         0.250      1.2      96.0%     ✗     0.10

**El limitante es el VOLUMEN, no la precisión.** Casi todas las filas están
entre 90% y 100%, muy por encima del 80% que pide el gate; lo que no se alcanza
son las 3 ofertas/día. O sea hay margen para bajar θ y ganar ofertas sin romper
la promesa del canal — y es justo al revés de lo que sugiere la intuición de
"bajar θ ensucia el canal".

Mover un θ **es una decisión de producto**: se mide, se reporta y la toma el
dueño. Esta tabla es la parte de medir.

## Dos cautelas, para no sobreleer la tabla

1. **No se compara de frente con la calibración del 5-nov.** No está registrado
   con qué rango se corrió, y el rango cambia el volumen: `señales/día` es
   señales dividido por días de mercado, así que dos rangos distintos dan dos
   números distintos para el mismo θ.
2. **`tecno-componentes` a θ 0.35 tiene más de la mitad de sus aciertos en
   liquidación.** Eso no describe un canal de ofertas, describe un outlet. La
   fila de arriba (θ 0.150) no sufre ese sesgo, pero conviene saber que la
   categoría lo tiene al subir.

## El desfase que esta corrida dejó abierto (no es un bug)

El backtest mide con **30** días de historia mínima y producción corre con
**20** desde la migración 48: `replay_listing` llama a `evaluate` sin
`min_history_days`, así que cae en el default `MIN_DAYS = 30` de
`baselines.py`. Verificado en el código, no deducido.

Era un desfase *temporal* por diseño —la migración 32 contaba con que las
categorías maduraran y la columna volviera a 30— y con los 20 permanentes ese
supuesto se cayó: **el θ que sale del backtest describe un detector que no es el
que corre.**

Pero todavía **no tiene consecuencia medible**: en el rango medible las
categorías afectadas ni aparecen, porque no tienen 30 días de futuro para
etiquetar. El efecto recién se puede medir sobre noviembre, o sea ~diciembre.

Si llegado ese momento se decide que el backtest lea la columna, el cambio son
cuatro ediciones en `pricing/backtest.py`: `replay_listing` acepta
`min_history_days` y lo pasa a `evaluate`; `load_series` agrega
`c.min_history_days` al SELECT y devuelve un tercer dict indexado por
`category_slug`; `run_backtest` lo propaga. Dos tests lo cubren —uno con 20 que
emite y uno con 30 que no, sobre una serie de 25 días de historia.

El costo a declarar antes de hacerlo: el **Cyber Monday del 5-7 de octubre** —el
único evento de descuentos reales de la serie— se mediría contra baselines de 20
días, que es exactamente lo que la migración 32 §2 quería evitar.

---

## Medido el 2026-11-06: qué hace el piso de 20 antes de que publique

El piso de 20 días se aplicó el 6-nov 13:52 UTC y **el pipeline no volvió a
correr desde entonces** (el último fue el 5-nov 18:51 UTC), así que la base no
muestra todavía ni un candidato producido con él. Esto lo mide offline, sin
escribir nada: se repite el SELECT de `detector._load_candidates` —sin su
`NOT EXISTS`, para ver la foto completa— y se corre `evaluate` dos veces por
observación, una con el `min_history_days` de la base (20) y otra forzando 30.

Reloj de la medición: el de las baselines vigentes (5-nov 18:51 UTC). Con `NOW()`
el filtro de `PRICE_MAX_AGE_HOURS` vaciaría la muestra y el resultado sería 0 por
construcción. **66.146 observaciones.**

    veredicto            con 20      con 30     delta
    accepted                515         409      +106
    history               40701       47034     -6333
    threshold             22083       15961     +6122
    ramp                    428         346       +82
    above_floor             178         155       +23
    refurbished            2149        2149        +0
    out_of_stock             64          64        +0
    server_hw                28          28        +0

Lo que dice, y no es lo que uno esperaría:

1. **6.333 observaciones cruzan la guarda de historia** que antes rechazaba, pero
   **6.122 de ellas mueren en θ**. El piso no las convierte en ofertas: las
   convierte en rechazos por umbral, que es un rechazo que **sí se persiste** y
   por lo tanto sí calibra.
2. **El pool de aceptados sube 409 → 515, un +26%.** Los 106 nuevos, por
   categoría: `tecno-audio` 46, `supermercado` 21, `tecno-celulares` 9,
   `deporte-equipamiento` 6, `deporte-vestuario` 6, `hogar-electro` 5,
   `tecno-componentes` 4, `ropa-calzado` 4, `ferre-herramientas` 2, y 1 cada una
   en `ferre-jardin`, `deporte-calzado` y `tecno-tv`.
3. **Y la cuota diaria es 33.** Con 409 aceptados ya había 12 candidatos por
   lugar; con 515 hay 15. O sea el piso de 20 **no publica más ofertas: cambia
   cuáles ganan**, y mete 106 que se miden contra un p50 de 20 a 29 días en una
   competencia que antes era solo entre series de 30 o más. El efecto es de
   composición, no de volumen — que es justo lo que no se ve mirando el total
   publicado.

Dos límites de esta medición, para no sobreleerla: no modela el **cooldown**
(`prior_post=None`), así que los aceptados son un techo —hay 545 `deal_posts`, el
último del 5-nov—; y no modela las promociones de multicompra, que solo pueden
sumar. Reproducible con el script del scratchpad de la sesión; el SELECT es el de
`detector._load_candidates` sin el `NOT EXISTS`.

### Y en lo que se PUBLICA, que es la pregunta que importa

La misma medición, pero pasando los aceptados por la curación: `ORDER BY score
DESC`, tope de 5 por tienda, de 3 por categoría y la cuota de cada tema, igual
que `curation.ranker`.

    piso 30   409 aceptados → 25 publicables →  0 de la cohorte de 20-29 días
    piso 20   515 aceptados → 25 publicables →  8 de la cohorte de 20-29 días

**El piso de 20 no agrega ni una oferta publicada: desplaza 8 de las 25**, o sea
un tercio del canal pasa a medirse contra un p50 de 20 a 29 días. Y el
desplazamiento tiene nombre:

    categoría              piso 30   piso 20
    tecno-notebooks              3         0     ← pierde sus tres lugares
    tecno-audio                  0         3     ← los gana, los tres jóvenes
    tecno-componentes            3         2
    tecno-celulares              0         1       (joven)
    supermercado                 3         3       (2 jóvenes)
    ropa-calzado                 3         3       (1 joven)
    tecno-tv                     2         2       (1 joven)
    hogar-electro                3         3
    deporte-equipamiento         3         3
    deporte-vestuario            2         2
    ferre-jardin                 1         1

`tecno-notebooks` no empeoró: lo que pasó es que el tema `Tecnología` tiene cuota
**8** y ahora hay más candidatos de audio con mejor score peleándola. Es
exactamente el efecto de composición, visible solo acá.

**Y de paso cae un número que no estaba medido: se publican 25 de los 33 de
cuota, con los dos pisos.** Los 8 lugares que sobran no los limita el detector,
los limitan los topes finos y las categorías sin candidatos maduros: 3 de
`belleza` (su primer candidato posible es el 2026-12-04), 2 de `supermercado` y 2
de `ropa` por `MAX_PER_CATEGORY_PER_DAY = 3`, y 1 de `viajes-tours`. El problema
del tema `supermercado` que CLAUDE.md ya documentaba **es el mismo en cuatro
temas más**, y vale 8 de 33.

Límites, otra vez: no modela el cooldown (hay 545 `deal_posts`, así que algunos
ganadores serían desplazados), es una foto de un solo momento del pipeline, y los
scores salen del mismo set de observaciones. La conclusión que aguanta estos
límites es la de composición, no los nombres exactos de las categorías.

---

## Verificación de despliegue del 2026-11-06 — dos bloqueos encontrados

Medido comparando el `sha256[:32]` de cada `migrations/*.sql` de cada árbol
contra `schema_migrations.checksum` de producción, que es exactamente lo que hace
`migrate.py`. Es la verificación que nadie había hecho y que decide si el deploy
puede correr.

    árbol                archivos  mismatch  pendientes
    ofertoon (main)            46         0  --
    ofertoon-unimarc           48         0  47
    ofertoon-bloqueadas        48         1  50, 51      ← 40_ripley_hites.sql
    ofertoon-mercadopago       47         0  51          ← la MISMA 51

### 1. `feat/tiendas-bloqueadas` tiene la 40 vieja — `migrate.py` no aplicaría nada

Su worktree nació de `a2d8c06`, y la reescritura de `40_ripley_hites.sql` (la que
agrega `stores.publish_enabled` y conecta `pc-express`) se hizo en el árbol de
trabajo de `main` y se commiteó después, en `326057d`. Así que ese árbol tiene la
versión **anterior**: md5 `6dd670…` contra `e5dbca…` de `main` y de
`feat/unimarc`.

Un checksum distinto en un archivo **ya aplicado** es `checksum_mismatch`, y
`migrate.py` entonces **no aplica nada** — ni la 50, ni la 51, ni la 47 de otra
rama. Desde ese árbol el deploy entero está bloqueado y el síntoma no aparece
hasta que se intenta.

🟢 **No contamina `main` al mergear**, y eso está verificado, no supuesto: la rama
**nunca tocó** ese archivo (`git log a2d8c06..HEAD -- migrations/40_…` vacío), así
que git ve "main lo cambió, la rama no" y conserva el de `main`. El árbol
mergeado (`827c75e`) trae el `e5dbca…` correcto. El bloqueo es solo del worktree,
no del merge — pero basta para que ese agente no pueda probar una aplicación
desde su propio árbol, que es justo lo que CLAUDE.md §Paso 3 manda no hacer.

### 2. Dos migraciones con el número 51, en dos árboles que no se ven

    ofertoon-bloqueadas/migrations/51_sparta_tajada_disjunta.sql
    ofertoon-mercadopago/migrations/51_mercadopago_suscripciones.sql

Las dos sin commitear, cada una en su worktree, ninguna ve a la otra. Es la
colisión de CLAUDE.md §Trabajo multi-agente §2 **ocurriendo por segunda vez en
dos días**, y la primera vez obligó a renumerar la tanda 40-44 entera.

Se detectó antes de aplicar, así que se arregla renumerando una sola: la de
Sparta a **52**, porque MercadoPago ya confirmó por escrito que se queda con la
51. Renumerar es renombrar el archivo y corregir las referencias cruzadas de su
header — ninguna de las dos está aplicada, así que no hay checksum que preservar.

### Lo que esto dice del método, y es lo que vale guardar

El reparto de números por escrito **no alcanza**: se escribió, se comunicó, y la
colisión pasó igual, porque el canal de aviso no llegó a tiempo al tercer agente.
Lo único que la cazó fue **medir los archivos contra la base**. Que es la misma
lección de todo este repo: el efecto, nunca el mensaje — ni siquiera cuando el
mensaje es un acuerdo entre agentes.

---

## ⚠️ CORRECCIÓN del 2026-11-07 — el piso de 20 no aflojó nada: apretó

Lo de arriba comparó **20 contra 30** y concluyó que el piso de 20 "desplaza un
tercio del canal" hacia baselines de 20-29 días. La aritmética está bien y la
conclusión está **mal**, porque el 30 existió unas horas y **no produjo ni un
post publicado**. El contrafáctico correcto es el que el canal venía usando de
verdad: **10**.

La secuencia real del piso, reconstruida de las migraciones y confirmada en lo
publicado:

    migración 32 (octubre)     7 categorías en 10, con reversión comprometida
    ~5/6-nov, a mano           las 17 a 30 — sin migración, lo dice el header de la 48
    migración 48, 6-nov 13:52  las 17 a 20

Entre esos dos últimos pasos pasaron horas y ningún pipeline corrió, así que
**ninguna oferta se publicó jamás con el piso en 30**.

### Lo publicado, con la historia que de verdad tenía al detectarse

Días distintos **con stock** en los 60 previos a `detected_at`, que es lo que
cuenta `compute_baseline` (`in_stock` filtra, y eso baja el número). Validado
contra el `n_days` guardado: coincide con una diferencia constante de 1, porque
la baseline incluye la observación del propio `detected_at` y esta cuenta usa
`< detected_at`.

    fecha        posts   n_days < 21   n_days < 30   n_days mínimo
    2026-10-30      24         8            14            11
    2026-10-31      21         1            14            15
    2026-11-01      22         9            12            10
    2026-11-02      25        11            14            10
    2026-11-03      25         9            12            10
    2026-11-04      34         5            12            10
    2026-11-05      25         6            11            11
    ---- migración 48: el piso pasa a 20 ----
    2026-11-06      23         0             7            24
    2026-11-07      22         2             5            20

Leído en voz alta: hasta el 5-nov el canal publicaba ofertas medidas contra
**baselines de 10 u 11 días** —entre 5 y 11 por día por debajo de 21—, y después
del 48 el mínimo es 20 y la cola corta **desaparece**. La fracción medida contra
menos de 30 días cae de **44-56% a 23-30%**.

**O sea la migración 48 fue un apriete, no un aflojamiento.** Hizo exactamente lo
que un piso tiene que hacer: sacó las baselines más cortas. Lo que yo reporté
—"mete 106 candidatos medidos contra un p50 de 20 a 29 días"— describía el paso
de 30 a 20, que nunca ocurrió en producción.

### Por qué me equivoqué, que es lo que vale guardar

El header de la 48 avisa en su §1: *"Es importante no confundirla con la
reversión de la 32, que ya ocurrió"*. Yo leí la columna (`min_history_days = 20`)
y el código del backtest (`MIN_DAYS = 30`), y de ahí deduje el contrafáctico en
vez de medirlo. **El estado anterior de una columna no se deduce del código: se
lee en lo que el sistema ya produjo.** `deal_posts` + `deal_candidates` +
`price_points` lo tenían escrito todo el tiempo.

Corolario para el desfase backtest/producción de la regla 5: sigue siendo real
—el backtest mide con 30 y producción corre con 20— pero su signo es el
contrario del que supuse. El backtest es **más exigente** que producción, así que
el θ que saca está calibrado sobre una población de listings más madura que la
que el detector ve. Eso subestima el volumen que θ va a producir, no lo
sobreestima.
