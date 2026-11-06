# Prompt de traspaso — rama `feat/tiendas-bloqueadas`, escrito el 2026-11-06

Pegá lo que está dentro del bloque. Está escrito para no tener que leer el
historial de la sesión anterior.

---

```
Seguís en la rama `feat/tiendas-bloqueadas` de OfertasCL (worktree
`~/servicios/ofertoon-bloqueadas`). Rockford quedó cerrado: adaptador, fixture,
28 tests y la migración 50 escrita sin aplicar. Esta sesión tiene tres cosas que
el dueño autoriza explícitamente —commitear, abrir un PR y aplicar migraciones—
y una tienda nueva que es la más barata del repo.

Hay **dos** agentes trabajando en paralelo —`feat/unimarc` y `feat/mercadopago`—
y la separación de archivos y de números de migración es estricta: está al final y
es lo que evita que se pisen.

PRIMERO, SIN EXCEPCIÓN
Leé CLAUDE.md y su §Trabajo multi-agente — **ahora tiene seis subsecciones y la
§5 es nueva y te toca**: dos ramas pueden quedar interdependientes a través de la
base. No crees un worktree nuevo: usá el que ya tenés.

    cd ~/servicios/ofertoon-bloqueadas
    /home/donaldchavez/servicios/ofertoon/.venv/bin/python   # el venv vive en el checkout principal

Base de test propia de esta rama: `ofertas_test_bloqueadas` (creala si no
existe). **Un solo pytest a la vez por base**, o el síntoma es un
`UndefinedTableError` en tests que no tocaste.

⚠️ **Todo tu trabajo está SIN COMMITEAR en los dos árboles.** Es la trampa de
§Trabajo multi-agente §1 y no falla ruidosamente:

  * en tu worktree: `TIENDAS_PROHIBIDAS.md` modificado, `migrations/50_*.sql`,
    `scrapers/stores/rockford.py`, `tests/test_rockford.py`,
    `tests/fixtures/rockford_hombre_vestuario.json` y `research/2026-11-07/`;
  * en `main`: `HANDOFF.md`, `TIENDAS.md`, `curation/ranker.py`,
    `migrations/40_ripley_hites.sql`, `pricing/detector.py`,
    `research/2026-11-06/` (IMPERIAL.md, PC_EXPRESS.md, el CSV),
    `scrapers/stores/pc_express.py`, `tests/test_pc_express.py` y
    `tests/test_store_ingest_only.py`.

Commitealos **antes de cualquier otra cosa**, cada uno en el árbol donde vive. No
commitees `research/2026-11-07/__pycache__`.

ESTADO REAL, MEDIDO EN LA BASE EL 2026-11-06 — no lo heredes de ningún documento
  - **47 migraciones aplicadas: 01-46 y 48. Falta la 47**, que está escrita en
    `feat/unimarc` y sin aplicar. Sí: hay un hueco en el medio de la secuencia.
  - ⚠️ Desde `main` y desde tu worktree, `migrate.py --status` contesta "sin
    pendientes" **y es falso**, porque ninguno de los dos tiene los archivos 47 y
    48. El único lugar donde se ve la verdad es
    `SELECT filename FROM schema_migrations`.
  - **31 tiendas**, 727 llaves activas, **17 categorías**. `ripley` y
    `pc-express` con `publish_enabled=false`; `unimarc` todavía no existe.
  - **`min_history_days = 20` en las 17 categorías** (migración 48, aplicada el
    6-nov 13:52 UTC). La excepción de 10 días de la migración 32 ya no existe, y
    los 20 **no tienen fecha de reversión**.
  - **El piso de 20 todavía no produjo ni un candidato**: el último pipeline
    corrió el 5-nov 18:51 UTC. Lo que hay en `deal_candidates` es el detector con
    el piso viejo.
  - Publisher y gate **encendidos**, 7 servicios `running`, cero suscriptores
    activos. 8 temas cableados, cuota 33/día.
  - Última pasada (5-nov 17:00 → 6-nov 04:00 UTC): 727 corridas, 606 `ok`, 115
    `partial`, 6 `failed`, ~73.000 observaciones. Los `failed` son 4 de
    `spdigital`, 1 de `lippi` y 1 de `prat`.
  - **CLAUDE.md, TRAMPAS.md y HANDOFF.md se actualizaron hoy.** Leé solo lo que
    cambió: regla 5 (los 20 días y el desfase con el backtest), §Pasos 1 paso 6
    (`publish_enabled = FALSE`), §Paso 4 (hay filas que ningún test puede ver),
    §Trabajo multi-agente §5, §Estado, y de TRAMPAS las dos viñetas nuevas de
    **F** y la de **G**. Son 79 trampas, no 72.

LO QUE EL DUEÑO AUTORIZA EN ESTE PROMPT, y nada más
Commitear tu trabajo, abrir el PR de `feat/unimarc` y aplicar migraciones.
Cualquier otra cosa sigue necesitando pedido explícito: si algo no está en esta
lista, preguntá antes.

TU TRABAJO, EN ORDEN

1. **COMMITEAR Y ABRIR EL PR DE `feat/unimarc`.** Esa rama trae dos commits
   (`42a2776` Unimarc completo + `price_condition`, `0ad0533` la migración 48 y la
   `40_ripley_hites.sql` alineada con la versión aplicada) más el trabajo del
   6-nov sin commitear en su worktree: la 47 corregida para que Unimarc nazca con
   `publish_enabled = FALSE`, `research/2026-11-06/BACKTEST_theta.md`, y las
   actualizaciones de CLAUDE.md, TRAMPAS.md, HANDOFF.md y la fila de `unimarc` en
   TIENDAS.md. **Esos cambios los commitea su propio agente, no vos** — pedí que
   estén commiteados antes de abrir el PR.
   Dos cosas medidas que te van a frenar si no las sabés:
     - **`gh` está instalado pero sin sesión** (`gh auth status`: "not logged into
       any GitHub hosts"). El PR no se puede abrir hasta que el dueño corra
       `gh auth login` — sugerile `! gh auth login` en la sesión.
     - **`main` local y `origin/main` divergen**: origin tiene 1 commit que local
       no tiene y local 7 que origin no tiene, pero `git diff main...origin/main`
       es **vacío** — o sea no hay diferencia de contenido, solo de historia
       (`7fad162` es el merge del PR #2). Hay que mergear `origin/main` antes de
       pushear; no hay riesgo de conflicto de contenido.

2. **INTEGRAR LAS DOS RAMAS. Ya está verificado, no lo rehagas.** Simulado hoy con
   `git merge-tree` contra un commit sintético del árbol de `main`: **un solo
   conflicto**, dos filas adyacentes de `TIENDAS.md` (`unimarc` y `pc-express`)
   que las dos ramas reescribieron. La resolución es quedarse con la fila de
   `unimarc` de `feat/unimarc` y la de `pc-express` de tu trabajo — cada una
   describe lo suyo. `curation/ranker.py` **auto-mergea bien**: conviven tu
   `AND s.publish_enabled` en el WHERE y su `pum.price_condition` en el SELECT.
   La suite sobre el árbol mergeado dio **954 passed**.
   Y el orden del despliegue no es intercambiable, porque las dos ramas son
   interdependientes **a través de la base** (CLAUDE.md §Trabajo multi-agente §5):
   aplicar la 47 sin ese código deja las 8 llaves de Unimarc en `failed` cada
   pasada, y desplegar ese código sin el tuyo rompe `pc-express`, que ya está en
   la base apuntando a un módulo que esa rama no tiene.
   **Primero integrar, después UNA build, después UNA aplicación.**

3. **APLICAR LAS MIGRACIONES.** Con estas reglas, que no son opinables:
     - 🔴 **Nunca desde un worktree.** Se aplica desde `~/servicios/ofertoon`, el
       checkout de despliegue, y **solo con la secuencia completa delante** —si
       falta un archivo, `migrate.py` lo saltea en silencio.
     - **`docker compose build` ANTES de migrar.** Si `stores.adapter` nombra un
       módulo que la imagen no tiene, `resolve_adapter` falla y las llaves quedan
       `failed`. La imagen tiene que traer `unimarc.py`, `pc_express.py` y
       `rockford.py` si la 50 entra en esta vuelta.
     - Orden: **47** (Unimarc), después **50** (Rockford), la **51** de MercadoPago
       si su agente la deja lista, y la **52** que escribas.
       El hueco no es problema: `migrate.py` aplica lo que no esté en
       `schema_migrations`, no exige orden.
     - **Verificá el efecto, nunca el mensaje**: `listo — 0 migración(es)
       aplicada(s)` es a la vez el mensaje de una corrida sana y el de "tu
       migración no está en esta imagen". Lo que hay que mirar en la base: la fila
       en `stores` con `publish_enabled=false`, las llaves en `store_categories`
       (8 de Unimarc —7 a `supermercado` y `perfumeria` a `belleza`—, 4 de
       Rockford), la columna `price_points.price_condition`, y `scrape_runs.status`
       después de la primera pasada real.
     - ⚠️ **Las `store_categories` no las puede verificar ningún test**: el
       `_truncate_state` del conftest las trunca entre tests. Se miran en la base.

4. **SPARTA — migración 52, y es la tienda más barata del repo: el adaptador YA
   EXISTE.** `scrapers.stores.magento_html:SpartaAdapter` está escrito, con su
   `rate_limit_rps = 1.0`, `page_size = None`, `paginates = False`,
   `dedupe_across_categories = True`, su fixture `sparta_zapatillas.html` y sus
   tests pasando. **No hay código que escribir**: falta la fila, las llaves y una
   decisión.
   Lo medido (2026-11-04, `INVESTIGACION_deporte_outdoor.md` §1): Magento;
   `Crawl-delay: 1`; **su robots prohíbe toda query string** (`Disallow: /*?`), así
   que no pagina y el techo de catálogo es **24-27%** (3.157 de 13.448 fichas);
   orden estable (8 de 9 hojas con Jaccard 1,000); `price_normal` en **41,6%** ⇒ θ
   medible; oculta los agotados en vez de marcarlos; "Desde" en 6-15 filas por
   categoría = el precio del grid de un configurable es el **mínimo entre talles**;
   sin centinelas (pmax $10.990.000); costo **340 requests, ~6 min, ~157 MB**, que
   se come el 10% de `PASS_WINDOW`.
   **La decisión, y corregida con lo medido hoy**: el conjunto recomendado son las
   9 raíces de taxonomía (340 hojas, 87,3% de lo alcanzable, **1,72× residual**), y
   ese residual **cruza categorías internas distintas** —`vestuario-deportivo` ×
   `deportes-individuales` 30%, `entrenamiento-funcional` × `deportes-individuales`
   36%—, que es justo lo que el precedente de Andesgear NO cubre.
   El docstring de `SpartaAdapter` dice "hay que ordenar los `store_key` a
   propósito", **y eso no alcanza**: `db.load_store_targets` ordena
   `ORDER BY s.slug, c.slug, sc.store_key`, así que el que gana el dedupe lo
   decide el **slug de categoría alfabético** antes que el `store_key`. Y
   `deporte-equipamiento` < `deporte-vestuario`, o sea una polera cross-listada
   queda puntuando con θ **0.250** en vez de **0.350**: la dirección mala, porque
   baja la vara. Las salidas reales son tres: renunciar a los ejes que se cruzan
   (menos cobertura), mapear los ejes cruzados a la misma categoría interna, o
   aceptarlo y declararlo en el header. **No toques el `ORDER BY` de `db.py`**: es
   código compartido y cambiaría la asignación de Andesgear en silencio.
   La fila nace con **`publish_enabled = FALSE`** (CLAUDE.md §Pasos 1 paso 6), con
   la fecha de conexión y la de evaluación —conexión + 30 días— anotadas en el
   header.

5. **SI QUEDA SESIÓN: la terna Salesforce.** `tricot.cl` y `abc.cl` comparten
   plataforma con Hites, así que un `salesforce_family.py` cubriría las tres
   (Hites hoy tiene adaptador propio, 4,5 KB). Lo medido está en
   `INVESTIGACION_ropa.md` §2 y ya trae las trampas:
     - las tres paginan con **`?start=N&sz=M` sobre la URL de categoría limpia**, y
       eso está permitido; lo que cada robots prohíbe es **otra ruta al mismo
       dato** (`/on/demandware.store/*` y `*cgid=*` en ABC,
       `*Search-UpdateGrid*` en Hites, `/search*` en Tricot);
     - **el `data-pid` está en distinto lugar en cada una**: en Hites el selector
       correcto es `.product-tile` porque `[data-pid]` mete carruseles de
       recomendados (108 contra 36); **ABC repite el `data-pid` tres veces por
       tile** (108 pids para 36 productos) ⇒ deduplicar por pid, no contar nodos;
     - ⚠️ **ABC cotiza por zona de inventario** (`zone=inventory_LaPolar_...`,
       Metropolitana por default). Es el caso Construmart exacto: hay que fijarla
       explícita en el adaptador y documentar que **cambiarla invalida el
       histórico entero de la tienda**;
     - y una que conviene medir antes de guardar un precio: el adaptador de Hites
       **filtra vendedores marketplace** (`.marketplace-info-plp b` == `hites`).
       Si Tricot o ABC tienen 3P, un precio sin filtrar no es de la tienda.
   De las doce preguntas faltan GTIN, `price_normal`, stock, centinelas y llaves
   disjuntas por tienda. Migración **53**.

6. **KLIPER: NO la conectes, aunque el adaptador ya exista**
   (`magento_html:KliperAdapter`). Dos razones, y la segunda cambió esta semana:
   su costo declarado son **706 requests / 35,7 min** —de
   `PROMPT_SIGUIENTE_SESION.md` §5, que es un handoff viejo: **re-medilo antes de
   citarlo**—, lo que deja la pasada en ~114 de los 120 min de `PASS_WINDOW`; y
   Kliper es el distribuidor de `thenorthface`, `mammut`, `marmot` y `andesgear`,
   que hoy están **las cuatro conectadas**. Conectarla es contar el mismo catálogo
   por quinta vez y habilitar que la misma oferta salga dos veces al canal. Es
   decisión del dueño, no tuya.

AL TERMINAR: DEJÁ UN RESUMEN ESCRITO
En `research/2026-11-07/` (o actualizando su `README.md`, que ya tiene la tabla de
estados). Que diga, sin adornos: **qué se hizo**, **qué quedó sin hacer y por
qué**, **qué se midió y con qué fecha**, **qué migración quedó escrita y si está
aplicada**, y **qué decisiones del dueño quedan abiertas**. Usá los cinco estados
de una tienda de CLAUDE.md (investigada / fuente comprobada / adaptador probado /
ingesta activa / catálogo completo) y no los mezcles.
Cada trampa nueva va a `TRAMPAS.md` en su sección, **agregando al final de la
sección**, y actualizá el conteo del índice y el de CLAUDE.md (hoy 79).

QUÉ NO TOCAR — es de `feat/unimarc`
  - `migrations/47_unimarc_y_condicion_del_precio.sql`, `scrapers/stores/unimarc.py`,
    `publisher/formatter.py`, el `price_condition` de `scrapers/base.py`, `db.py`,
    el **SELECT** de `curation/ranker.py` y `research/2026-11-06/`.
  - **Migraciones: la 50 es tuya (Rockford) y la 52 en adelante también.**
    ⚠️ **La 51 ya NO está libre**: la tomó un tercer agente en `feat/mercadopago`
    (`migrations/51_mercadopago_suscripciones.sql`, worktree
    `~/servicios/ofertoon-mercadopago`), medido el 2026-11-06 después de escribir
    este prompt. La 47 y la 48 son de `feat/unimarc`. La **49 nunca se escribió y
    queda muerta a propósito**: un número sin archivo es inofensivo —`migrate.py`
    aplica lo que encuentra—; lo que duele es el mismo número en dos ramas.
    Antes de tomar un número, mirá **todos** los árboles, no el tuyo:
    `for d in ~/servicios/ofertoon*; do find $d/migrations -maxdepth 1 -name '*.sql' -printf '%f\n'; done | grep -oE '^[0-9]+' | sort -n | tail -1`
  - Tuyo y sin discusión: `TIENDAS_PROHIBIDAS.md`, `research/2026-11-07/`,
    `scrapers/stores/pc_express.py`, `scrapers/stores/rockford.py`, los adaptadores
    nuevos que escribas, `pricing/detector.py` y el `AND s.publish_enabled` de
    `curation/ranker.py`.
  - En los `.md` compartidos (`CLAUDE.md`, `TRAMPAS.md`, `TIENDAS.md`,
    `HANDOFF.md`): **agregá, nunca reordenes** — git mergea inserciones separadas y
    falla con reordenamientos.

CÓMO SE TRABAJA ACÁ, EN CORTO
  - **Verificá el efecto, nunca el mensaje.** `--dry-run` no ejercita el INSERT;
    `docker ps` puede decir `Up` de un contenedor vacío.
  - **Una prueba sin caso de control es un falso verde.**
  - **Un veredicto de acceso tiene fecha.** Este repo declaró inaccesibles siete
    tiendas que eran accesibles, siempre por medir el host o la ruta equivocados.
  - 🔴 **Nunca reiniciar scraper ni publisher desde un worktree**, y nunca
    `db-migrate` desde uno.
  - **No pegarle a la misma tienda desde dos procesos**: el `RateLimiter` es por
    proceso y dos agentes a 0,33 rps le pegan a 0,66.
  - **Avisá cualquier decisión que tomes por tu cuenta**, por chica que parezca.
    Honestidad 100%, cero condescendencia: si algo falla, decilo con el output.
```
