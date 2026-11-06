# Prompt de traspaso — rama `feat/unimarc`, escrito el 2026-11-06

Pegá lo que está dentro del bloque. Está escrito para no tener que leer el
historial de la sesión anterior.

---

```
Continuás el trabajo de la rama `feat/unimarc` de OfertasCL. Hay otro agente
trabajando en paralelo y la separación es estricta: respetala.

PRIMERO, SIN EXCEPCIÓN
Leé CLAUDE.md y su §Trabajo multi-agente. Tu worktree ya existe:
`~/servicios/ofertoon-unimarc`, rama `feat/unimarc`, dos commits y árbol limpio.
NO crees uno nuevo.

    cd ~/servicios/ofertoon-unimarc
    # el venv vive en el checkout principal:
    /home/donaldchavez/servicios/ofertoon/.venv/bin/python

ESTADO REAL, VERIFICADO EL 2026-11-06 — no lo heredes de ningún documento
  - Migraciones aplicadas en producción: **01-46 y 48**. **Falta la 47.** Son 47.
  - `categories.min_history_days = 20` en **las 17** categorías (migración 48,
    aplicada). La excepción de la migración 32 ya no existe.
  - **31 tiendas** en `stores`; `ripley` y `pc-express` con `publish_enabled=false`.
  - Unimarc **no existe todavía en producción**: ni tienda, ni llaves, ni la
    columna `price_condition`. Todo eso lo trae la 47.
  - ⚠️ `main` y los otros worktrees **no tienen los archivos 47-48**, así que allí
    `migrate.py --status` dice "sin pendientes" **falsamente**. Verificá contra
    `schema_migrations` en la base, nunca contra tu árbol.
  - Base de test de esta rama: `ofertas_test_unimarc` (ya existe). Un solo pytest
    a la vez por base.

LO QUE YA ESTÁ HECHO EN ESTA RAMA (no lo rehagas)
  - `42a2776` — Unimarc completo: adaptador, 3 fixtures de payload real, 33 tests,
    migración 47, y `price_points.price_condition` con su camino hasta el copy
    (`scrapers/base.py`, `db.py`, `curation/ranker.py`, `publisher/formatter.py`).
  - `0ad0533` — migración 48 (los 20 días) y la `40_ripley_hites.sql` alineada con
    la versión **aplicada** en producción (otro agente la reescribió para agregar
    `stores.publish_enabled` y conectar pc-express; sin alinearla, esta rama daba
    `checksum_mismatch` y ningún `db-migrate` podía correr desde acá).
  - Suite: **948 passed, 0 fallos** con `TEST_DATABASE_URL` apuntando a
    `ofertas_test_unimarc`.
  - Investigación completa en `research/2026-11-06/INVESTIGACION_unimarc.md` (las
    doce preguntas) + tres scripts reproducibles.

DECISIONES DEL DUEÑO YA TOMADAS — no las vuelvas a plantear
  - **`min_history_days = 20` para las 17 categorías.** Elegida con los números
    delante, sabiendo que ninguna sube y que las 17 bajan de 30. Aplicada.
  - **El precio Club Unimarc cuenta como oferta** (ser Club es solo dar el RUT),
    así que es `price_effective`, no `price_card` — y el copy **declara la
    condición**. De eso se encarga `price_condition`.
  - **Las promos de multicompra van al canal** declarando que el ahorro es por
    cantidad (migración 46, ya aplicada).
  - **El backtest sigue midiendo con `MIN_DAYS = 30` a propósito.** Está
    documentado en la migración 32 §2 y en HANDOFF: medir con 30 preserva la
    calibración vieja y el **Cyber Monday del 5-7 de octubre**, el único evento de
    descuentos reales de la serie. NO es un bug de paridad — yo me equivoqué
    llamándolo así. Ver abajo "la decisión que quedó abierta".

TU TRABAJO, EN ORDEN

1. **ARREGLAR LA 47 ANTES DE QUE SE APLIQUE: Unimarc tiene que nacer con
   `publish_enabled = FALSE`.** Lo detectó el otro agente y es correcto: tal como
   está, la 47 crea Unimarc publicando, y con el piso de 20 días podría publicar
   **antes** de su evaluación formal de aceptación, que es el **2026-12-06**
   (`python -m scripts.aceptacion_tienda --store unimarc`). Es el mismo patrón que
   ya usan `ripley` y `pc-express`.
   La 47 **no está aplicada**, así que se edita en el lugar (no hace falta una
   migración nueva). Al tocarla, actualizá su header: hoy no menciona
   `publish_enabled` porque esa columna no existía cuando se escribió.

2. **INTEGRAR LAS DOS RAMAS, Y ES LO QUE DESTRABA TODO.** Hoy el deploy está
   trabado porque las dos ramas son interdependientes **a través de la base**:
     - aplicar la 47 **sin** desplegar este código inserta `unimarc` con un
       adapter que la imagen no tiene → `resolve_adapter` falla y sus 8 llaves
       quedan `failed` cada pasada (CLAUDE.md §Paso 1.7);
     - desplegar **esta** rama sola rompe `pc-express`, que ya está en la base
       apuntando a `scrapers/stores/pc_express.py`, archivo que esta rama no tiene;
       y además perdería la guarda `publish_enabled` de `detector.py`/`ranker.py`.
   El camino: que el trabajo del otro agente entre a `main`, mergear esta rama,
   **una** build y **una** aplicación desde el checkout de despliegue.
   El conflicto esperable es chico y está mapeado: los dos tocamos
   `curation/ranker.py` (él un `AND s.publish_enabled` en el WHERE de
   `_CANDIDATES_SQL`, yo `pum.price_condition` en el SELECT y un campo en
   `Candidate`, ~24 líneas aparte → git debería resolverlo solo) y `TIENDAS.md`
   (filas distintas). Verificá el merge, no lo asumas.

3. **VERIFICAR EL EFECTO DESPUÉS DE APLICAR LA 47** — el mensaje no sirve:
   `migrate.py` dice "0 aplicadas" igual en una corrida sana y en una imagen vieja.
   Lo que hay que mirar en la base: la tienda en `stores` con
   `publish_enabled=false`, sus **8 llaves** en `store_categories` (7 a
   `supermercado` y `perfumeria` a `belleza`), la columna `price_condition` en
   `price_points`, y `scrape_runs.status` después de la primera pasada real.
   ⚠️ Las `store_categories` **no las puede verificar ningún test**: el
   `_truncate_state` del conftest preserva solo `categories`, `stores` y
   `schema_migrations` y trunca el resto entre tests. Hay que mirarlas en la base.

4. **LOS θ — hay una tabla medida y una decisión del dueño esperando.**
   Backtest corrido el 2026-11-06 (`--from 2026-08-15 --to 2026-10-07`, con
   `--exclude-day` para 2026-09-18, 09-19 y 09-29; 51 días de mercado, 135.880
   listings, ~25 min). Solo **7 de las 17** categorías son medibles en ese rango.
   Con su θ actual:

       categoría            θ hoy   señ./día  precisión  gate   θ que pasaría
       ferre-herramientas   0.250      3.2      91.3%     ✓     0.25 (ya está)
       tecno-celulares      0.150      4.9      93.3%     ✓     0.15 (ya está)
       tecno-tv             0.180    2.3-4.3   93-97%   borde   0.15
       hogar-electro        0.200      2.5      95.3%     ✗     0.15
       tecno-notebooks      0.150      2.5      93.8%     ✗     0.10
       tecno-componentes    0.150      2.3      90.6%     ✗     0.10
       ferre-jardin         0.250      1.2      96.0%     ✗     0.10

   **El limitante es el VOLUMEN, no la precisión**: casi todas las filas están
   entre 90% y 100%, muy por encima del 80% del gate. Hay margen para bajar θ y
   ganar ofertas sin romper la promesa del canal. Mover un θ es **decisión de
   producto**: se reporta y la toma el dueño.
   Dos cautelas: no compares esta tabla de frente con la calibración del 5-nov
   (no se sabe con qué rango se corrió, y el rango cambia el volumen), y una fila
   (`tecno-componentes` θ 0.35) tiene más de la mitad de sus aciertos en
   liquidación, o sea describe un outlet.

5. **LA DECISIÓN QUE QUEDÓ ABIERTA, y que todavía NO hay que tomar.**
   El backtest mide con 30 y producción corre con 20. Eso era un desfase
   *temporal* por diseño —la migración 32 decía "cuando maduren y esto vuelva a
   30, producción y backtest coinciden otra vez sin tocar nada"— y con los 20
   permanentes **ese supuesto se cayó**: el desfase es ahora permanente, y el θ
   que sale del backtest describe un detector que no es el que corre.
   **Pero no tiene consecuencia medible todavía**: en el rango medible, las
   categorías afectadas ni aparecen, porque no tienen 30 días de futuro para
   etiquetar. El efecto recién se podrá medir sobre noviembre, o sea ~diciembre.
   Si llega el momento y se decide que el backtest lea la columna, el cambio son
   cuatro ediciones en `pricing/backtest.py`: `replay_listing` acepta
   `min_history_days` y lo pasa a `evaluate`; `load_series` agrega
   `c.min_history_days` al SELECT y devuelve un tercer dict indexado por
   `category_slug`; `run_backtest` lo propaga. Con dos tests —uno con 20 que emite
   y uno con 30 que no, sobre una serie de 25 días de historia— pasa en verde.
   El costo a declarar: el Cyber Monday del 5-7 oct se mediría contra baselines de
   20 días, que es justo lo que la migración 32 quería evitar.

QUÉ NO TOCAR — es del otro agente
Está en `feat/tiendas-bloqueadas` (worktree `../ofertoon-bloqueadas`) trabajando
las tiendas bloqueadas, y antes hizo PC Express en
`feat/pc-express-historial-persist`. **Suyo:**
  - `TIENDAS_PROHIBIDAS.md` (se le cedió entero), `research/2026-11-07/`
  - `scrapers/stores/pc_express.py` y los adaptadores nuevos que escriba
  - `pricing/detector.py` y el `AND s.publish_enabled` de `curation/ranker.py`
  - **Migraciones de la 50 en adelante.** La **49** es tuya si la necesitás.
En los `.md` compartidos (`TIENDAS.md`, `TRAMPAS.md`, `CLAUDE.md`, `HANDOFF.md`):
**agregá, nunca reordenes** — git mergea inserciones separadas y falla con
reordenamientos.

⚠️ Y hay algo que conviene avisarle al dueño: `main` **sigue con trabajo sin
commitear** del otro agente (`HANDOFF.md`, `TIENDAS.md`, `curation/ranker.py`,
`migrations/40_ripley_hites.sql`, `pricing/detector.py`, `research/2026-11-06/`,
`scrapers/stores/pc_express.py` y sus tests). Sus worktrees nuevos nacieron del
commit `a2d8c06`, así que **no lo contienen**. Es la trampa de §Trabajo
multi-agente §1 y no falla ruidosamente.

EL DUEÑO TE VA A PEDIR UN PROMPT PARA EL OTRO AGENTE EN ESTA SESIÓN
Ya tiene uno andando (tiendas bloqueadas: Imperial primero —es `occ_family`, una
familia nueva, y su obstáculo es inestabilidad de origen y no bloqueo—, después
Spacestore, Rockford/La Polar por TLS roto, y una sonda de confirmación a las
🔴 FIRME). Cuando pida el siguiente, los candidatos naturales, que están medidos
y esperando una decisión acotada:
  - **SPARTA**: lista salvo una decisión — su solapamiento residual de 1,72×
    cruza categorías internas distintas (vestuario × equipamiento 30-36%), así que
    con `dedupe_across_categories` gana la primera llave del orden de
    `db.load_store_targets` y una polera podría puntuar con el θ de equipamiento.
    Hay que ordenar los `store_key` a propósito o renunciar a los ejes que cruzan.
    Ver `INVESTIGACION_deporte_outdoor.md` §1.
  - **LAS OTRAS SALESFORCE**: Tricot, abc.cl y marathon.cl comparten plataforma y
    un `salesforce_family` cubriría las tres (Hites ya tiene adaptador propio).
    Dos trampas medidas: el `data-pid` está en el tile en Hites, en el **PADRE** en
    Tricot y en un **DESCENDIENTE** en abc; y abc cotiza **por zona de inventario**
    (caso Construmart). Ver `INVESTIGACION_ropa.md`.
  - **KLIPER**: bloqueada por presupuesto, no por taxonomía — 706 requests /
    35,7 min dejarían la pasada en ~114 min de los 120 de `PASS_WINDOW`. Hay que
    recortarle llaves.
Al escribirlo, repetí la separación de archivos y el rango de migraciones, que es
lo que evita que se pisen.

CÓMO SE TRABAJA ACÁ, EN CORTO
  - **Verificá el efecto, nunca el mensaje.** `--dry-run` no ejercita el INSERT;
    `docker ps` puede decir `Up` de un contenedor vacío.
  - **Una prueba sin caso de control es un falso verde.**
  - **Un veredicto de acceso tiene fecha.** Este repo declaró inaccesibles siete
    tiendas que eran accesibles, siempre por medir el host o la ruta equivocados.
  - 🔴 **Nunca `docker compose run db-migrate` ni reiniciar scraper/publisher desde
    un worktree.**
  - **No commitees ni pushees salvo que te lo pidan.**
  - **Avisá cualquier decisión que tomes por tu cuenta**, por chica que parezca.
    Honestidad 100%, cero condescendencia: si algo falla, decilo con el output.
```
