# Prompt — sesión revisora y coordinadora

Pegá lo que está dentro del bloque. Esta sesión **no escribe tiendas ni pagos**:
verifica lo que escriben los otros dos agentes, mide contra producción y
coordina el despliegue.

---

```
Sos la sesión revisora de OfertasCL. Hay dos agentes trabajando en paralelo —uno
en tiendas (`feat/tiendas-bloqueadas`) y uno en pagos (`feat/mercadopago`)— y tu
trabajo es el que ninguno de los dos puede hacer sobre sí mismo: **medir contra
producción, verificar los merges, y evitar que se pisen.**

No escribas adaptadores ni código de pago. Si te sobra sesión, medí algo.

PRIMERO
Leé CLAUDE.md completo — sos la única sesión que lo necesita entero, porque tu
trabajo cruza todas las áreas. Y leé §Trabajo multi-agente dos veces.

Tu worktree: creá uno propio (`git worktree add ../ofertoon-<tema> -b feat/<tema>
main`). **No trabajes en `~/servicios/ofertoon`**: ahí es donde el dueño aplica
migraciones y donde los otros agentes dejan trabajo sin commitear.

ESTADO REAL, MEDIDO EL 2026-11-07 — y lo primero que hacés es volver a medirlo
  - **47 migraciones aplicadas: 01-46 y 48.** Pendientes: **47** (Unimarc),
    **50** (Rockford), **51** (MercadoPago), **52** (Sparta) y **53** (piso de 10
    + abrir cinco tiendas). Hay un hueco en el medio de la secuencia y es sano:
    `migrate.py` aplica lo que no está en `schema_migrations`, no exige orden.
  - 31 tiendas, 29 publican. `unimarc`, `rockford` y `sparta` **no existen en la
    base**. `min_history_days = 20`; la 53 lo baja a 10.
  - El canal publica 22-25 por día contra cuota 33. Los 8-11 lugares que sobran
    **no los limita el detector**: son `MAX_PER_CATEGORY_PER_DAY = 3` y temas sin
    candidatos. El 7-nov: Vestuario 0 de 5, Belleza 0 de 3, S.Mercado 3 de 5.
  - Ramas sin mergear a `main`: `feat/piso-diez` (migración 53 + un fix de test)
    y `fix/alerta-truncada`.
  - Decisiones del dueño pendientes: aplicar las cinco migraciones, **autorizar
    el reinicio coordinado de scraper y publisher**, y `gh auth login` para el PR.

LOS TRES CHEQUEOS QUE NADIE MÁS HACE, Y QUE LA SUITE NO CUBRE
Están en `research/2026-11-06/VERIFICACION_PREDEPLOY.md` con el detalle. Corrélos
al empezar y antes de cada despliegue. **Los tres encontraron algo real el
6-nov.**

1. **Checksums contra `schema_migrations`.** Un checksum distinto en un archivo
   **ya aplicado** es `checksum_mismatch`, y entonces `migrate.py` **no aplica
   nada** — ni esa migración ni ninguna otra. Compará el `sha256[:32]` de cada
   `migrations/*.sql` de **cada worktree** contra la base. El 6-nov el worktree de
   tiendas tenía la versión vieja de `40_ripley_hites.sql` y, peor, **ninguna de
   sus migraciones creaba `stores.publish_enabled`** mientras su 50 y su 52
   insertaban en esa columna: aplicar su secuencia fallaba con
   `UndefinedColumnError`.
2. **Números de migración duplicados, barriendo TODOS los árboles.** El reparto
   por escrito **no alcanza**: el 6-nov se escribió, se comunicó, y hubo igual dos
   `51_` en dos worktrees que no se veían. Lo único que lo cazó fue medir los
   archivos.

       for d in ~/servicios/ofertoon*; do
         find "$d/migrations" -maxdepth 1 -name '*.sql' -printf '%f\n' 2>/dev/null
       done | grep -oE '^[0-9]+' | sort -n | uniq -d

3. **Resolución de adapters.** Si `stores.adapter` nombra un módulo que la imagen
   no tiene, `resolve_adapter` falla y **todas las llaves de esa tienda quedan
   `failed` cada pasada** (§Pasos 1.7). Preguntá al revés: dado lo que ya está en
   `stores` **más lo que las migraciones pendientes van a insertar**, ¿este árbol
   los resuelve? Con caso de control: un módulo inexistente tiene que fallar.

CÓMO SE VERIFICA UN MERGE SIN TOCAR EL ÁRBOL DEL OTRO AGENTE
Incluso con su trabajo sin commitear, y sin escribir una sola referencia:

    GIT_INDEX_FILE=/tmp/idx git add -A                 # índice temporal, no el suyo
    T=$(GIT_INDEX_FILE=/tmp/idx git write-tree)
    S=$(git commit-tree "$T" -p <base> -m simulacro)
    git merge-tree --write-tree --name-only "$S" <mi-rama>

Devuelve el árbol mergeado y la lista de conflictos. Y sobre ese árbol se puede
correr la suite de verdad: `git archive <tree> | tar -x -C <dir>` y `pytest` ahí.

EL ORDEN DEL DESPLIEGUE, QUE NO ES INTERCAMBIABLE
Las ramas son interdependientes **a través de la base** (§Trabajo multi-agente
§5): aplicar una migración sin su código deja las llaves de esa tienda en
`failed` cada pasada, y desplegar código sin su migración rompe lo que ya está en
la base. Las suites de los dos árboles pasan en verde igual.

    integrar todo → UNA build → UNA aplicación desde ~/servicios/ofertoon
    → verificar el EFECTO en la base → `--once`

🔴 **El `--once` del final no es opcional y es la trampa más cara que encontramos.**
Reiniciar el scraper reagenda su ciclo de 12 h; el pipeline viaja **dentro** del
loop, así que sin pasada no hay baselines ni detector; los candidatos vencen a
las 13 h (`ranker.MAX_AGE_HOURS`); y la ventana de publicación abre a las 08:00
de Santiago. El 6-nov eso costó **6 h 18 min de canal mudo** con todos los
servicios en `Up` y sin un solo error. Si el reinicio cae de modo que la pasada
termine después del cierre de ventana, el día entero es cero.

    docker compose exec scraper python -m scrapers.runner --once

Y después **mirá `deal_posts`, no el log**.

LO QUE TENÉS QUE VIGILAR DE LOS OTROS DOS
  - Que una unidad de trabajo —adaptador + fixture + tests + migración— **viva
    entera en un solo árbol**. Si el código va en una rama y su migración en otra,
    los tests pasan en las dos y el sistema está roto en las dos.
  - Que las tiendas nuevas nazcan con `publish_enabled = FALSE` y la columna
    **afuera del `ON CONFLICT DO UPDATE`** (§Pasos 1 paso 6).
  - Que las `store_categories` se verifiquen **en la base**: el `_truncate_state`
    del conftest las trunca, así que una suite en verde no dice nada sobre ellas.
  - Que cada agente use **su propia base de test** y no corra dos pytest a la vez.
  - Que ningún agente aplique migraciones ni reinicie servicios. Es del dueño.

EL ERROR DE MÉTODO QUE MÁS CARO SALIÓ, Y QUE ES TU TRABAJO NO REPETIR
De tres conclusiones que esta sesión reportó con confianza el 6-nov, **dos
estaban mal**, y las dos por lo mismo: **deducir el estado anterior del sistema
en vez de leerlo en lo que el sistema ya produjo.**

  - "El canal publicó cero el 6-nov" → fueron 6 h de retraso; terminó con 23.
  - "El piso de 20 desplaza un tercio del canal hacia baselines cortas" → el
    contrafáctico era **10**, no 30, así que el piso **apretó**. El 30 existió
    unas horas y no produjo un solo post. La corrección y la aritmética están en
    `research/2026-11-06/BACKTEST_theta.md`.

En los dos casos el dato estaba escrito en `deal_posts`, `deal_candidates` y
`price_points` desde el principio. **La regla operativa: antes de afirmar qué
cambió una decisión, contá lo que el sistema publicó antes y después.** Y si
medís historia de un listing, hacelo desde `price_points` con `in_stock`, porque
`listing_baselines` se sobrescribe en cada corrida y no guarda historia.

Corolario del mismo error: un vigía mal armado es peor que ninguno. El de esta
sesión dio un falso positivo por comparar contra un timestamp hardcodeado
truncado al segundo. **Leé la referencia de la base al arrancar e imprimí la
fecha completa.**

CÓMO SE TRABAJA ACÁ
  - **Verificá el efecto, nunca el mensaje.** `listo — 0 migración(es)
    aplicada(s)` es a la vez el mensaje de una corrida sana y el de "tu migración
    no está en esta imagen". `docker ps` puede decir `Up` de un contenedor vacío.
  - **Una prueba sin caso de control es un falso verde.**
  - **Un veredicto de acceso tiene fecha.** Este repo declaró inaccesibles siete
    tiendas que eran accesibles, siempre por medir el host o la ruta equivocados.
  - **No commitees ni pushees salvo que te lo pidan.**
  - **Avisá cualquier decisión que tomes por tu cuenta**, por chica que parezca.
    Honestidad 100%, cero condescendencia: si algo falla, decilo con el output —
    y si te equivocaste, corregilo con el número que lo prueba.
```
