# La guarda del canal mudo: escrita, probada y apagada

Escrito el 2026-11-09 desde `feat/mercadopago`. Cierra la propuesta del 7-nov
(`research/2026-11-07/GUARDA_canal_mudo_propuesta.md`), **le corrige el
backtest** y deja el código en el repo con el interruptor del lado del dueño.

Qué hay ahora, que antes era una propuesta:

| | |
|---|---|
| `publisher/guarda_canal.py` | `canal_mudo_hoy` (pura) y `posts_hoy_y_ayer` (la query) |
| `publisher/daemon.py` | `revisar_canal_mudo`, una vuelta por poll, con la memoria del día |
| `tests/test_guarda_canal.py` | 18 tests: 12 puros + 6 contra Postgres, con el backtest de los 49 días adentro y el par que prueba que **el default apagado no habla** |
| `.env.example`, `docker-compose.yml` | `PUBLISHER_ALERTA_CANAL_MUDO` (default **false**) y `PUBLISHER_ALERTA_DEADLINE_HOUR_UTC` (default **13**) |

**Está apagada.** Prenderla es del dueño y son dos líneas — están en
`HANDOFF_MERCADOPAGO.md` §5.

---

## 1. La corrección: el backtest anterior medía 12 días y eso ocultaba el riesgo

La propuesta del 7-nov concluyó "cero falsos positivos en 11 días sanos" para un
deadline de **12:00 UTC**, y dejó la elección 12:00 / 13:00 como decisión del
dueño con el argumento de que 12:00 "avisa de retrasos de una hora".

**Medido contra la historia completa —49 días, del primer post del canal
(2026-09-21) al último día cerrado (2026-11-08)— el deadline de las 12:00 es
inservible: 26 disparos en 49 días, 23 de ellos falsos.**

La causa no es el margen: es que `curation/ranker.WINDOW_START_HOUR` era **9**
hasta el commit `7fef769` (2026-10-21) y es **8** desde entonces. Con la ventana
vieja el canal abría a las 12:00 UTC y el primer post salía 12:00-12:04, o sea
**después** del deadline. La ventana de 12 días que medí el 7-nov caía entera
del lado nuevo, y por eso no vio nada.

La lección es más general que este umbral, y vale escribirla:

> **Un deadline en hora UTC absoluta solo vale para la ventana que lo produjo.**
> La ventana ya se movió una vez por código, y se va a mover otra sola: Santiago
> pasa a UTC-4 el **2027-04-04** (verificado con `zoneinfo`, no deducido), y ahí
> 08:00 local son las 12:00 UTC — la holgura del default baja de 2 h a 1 h.

Es la misma forma del error que el repo ya castiga en otras trampas: el número
estaba bien calculado sobre un recorte que no representaba el sistema.

## 2. El backtest completo

Evaluado llamando a `canal_mudo_hoy` de verdad —no a una reimplementación— en el
instante exacto del deadline de cada día, con `posts_hoy` = publicados hasta ese
instante y `posts_ayer` = total del día anterior. Días calendario **de
Santiago**, los mismos que usa el ranker para la cuota. Los días con cero filas
están incluidos: son los que la guarda existe para ver.

```
                                        deadline
día          total  1er post UTC   12:00    13:00
2026-09-21       6     19:01       calla    calla   ← día uno del canal
2026-09-22       6     12:02       FALSO    calla
   … 23-sep a 28-sep: 6 días iguales (primer post 12:01-12:04 UTC) …
2026-09-29       6     15:44       DISPARA  DISPARA ← pasada a medias
   … 30-sep a 13-oct: 14 días iguales …
2026-10-14       0       —         DISPARA  DISPARA ← primer día del apagón
2026-10-15…18    0       —         calla*   calla*  ← ayer ya venía mudo
2026-10-19       8     18:22       calla*   calla*  ← ayer ya venía mudo
2026-10-20      14     12:03       FALSO    calla
2026-10-21      25     12:03       FALSO    calla   ← último día de la ventana vieja
2026-10-22      26     11:02       calla    calla   ← WINDOW_START_HOUR 9 → 8
   … 23-oct a 5-nov: 14 días sanos, primer post 11:00-11:04 UTC …
2026-11-06      23     17:18       DISPARA  DISPARA ← el incidente del canal mudo
2026-11-07      22     11:00       calla    calla
2026-11-08      23     11:01       calla    calla

deadline 12:00 UTC → 26 disparos / 49 días, 23 falsos
deadline 13:00 UTC →  3 disparos / 49 días,  0 falsos
```

Los 23 falsos del deadline de las 12:00 son 1 + 6 (22-28 sep) + 14 (30-sep a
13-oct) + 2 (20 y 21-oct): todos los días sanos de la ventana vieja, sin
excepción.

(*) esos cinco días los tapa `posts_ayer == 0` y no el umbral, con los dos
deadlines: el canal ya venía mudo y la guarda avisó el 14-oct. Es la regla que
evita que un apagón de cinco días sean cinco avisos.

La tabla entera, día por día, está en `tests/test_guarda_canal.py::BACKTEST`, y
los dos veredictos son dos tests. No es un documento que describe un backtest:
es el backtest, y corre en CI.

### Los tres disparos, los tres diagnosticados

Ninguno es una sospecha; los tres tienen causa conocida y evidencia aparte:

- **2026-09-29** — la pasada a medias de las 03:16 UTC (62 de 129 objetivos
  perdidos, 1.481 observaciones contra ~16.500). Está documentada en
  `tests/test_guarda_volumen.py`. El canal arrancó 15:44 UTC.
- **2026-10-14** — primer día de un apagón de cinco: **cero `scrape_runs` del 14
  al 18** (medido). Los cuatro días siguientes la guarda calla por
  `posts_ayer == 0`: avisó el primer día y no repite.
- **2026-11-06** — el incidente del canal mudo, primer post 17:18 UTC. A las
  13:00 UTC la guarda habría hablado **4 h 18 min antes** de que el canal
  publicara, con la ventana abierta hasta las 23:00 de Santiago.

### El caso de control son los 46 días que callan

Está explícito en `test_backtest_los_46_dias_sanos_callan`. Una alerta que habla
los días sanos se mutea la primera semana, y entonces no existe: el control no es
un extra del test, es la mitad del requisito.

Los demás guardas también tienen su control, y los verifiqué **por mutación**:
sacar el filtro de `telegram_message_id`, agrupar por fecha UTC en vez de por día
de Santiago, quitar el chequeo de ventana, o correr la guarda sin mirar el flag
— cada una de las cuatro rompe exactamente un test y ninguna pasa inadvertida.

## 3. Lo que el prompt pedía verificar: ¿aguanta la cuota de 160?

**Sí, y no por suerte: la condición no mira el total.** Pero la respuesta honesta
tiene dos partes.

**Lo medible hoy.** El backtest ya cruza tres regímenes de cuota: **6/día**
(sep → 19-oct), **14** (19-oct), **30/33** (21-oct → hoy). El día más cargado de
la historia (34 posts, 4-nov) y los más flacos (6) dan **la misma cuenta** a las
13:00 UTC, porque lo que se cuenta es si ya salió el primero. Lo que la cuota
mueve es el total del día, que esta guarda no lee. Está como test
(`test_el_volumen_diario_no_mueve_la_condicion`).

**Y el primer día con cuota 160 ya se midió, en vivo.** El despliegue de la
migración 55 entró a las ~04:53 UTC de hoy, así que seguí el canal desde antes
de que abriera la ventana, llamando a la guarda contra la base de producción
cada 30 s:

```
10:57:43 UTC | hoy=0 ayer=23 | ventana=False | guarda=calla
10:59:44 UTC | hoy=0 ayer=23 | ventana=False | guarda=calla
11:00:14 UTC | hoy=0 ayer=23 | ventana=True  | guarda=calla   ← abre la ventana
11:03:14 UTC | hoy=0 ayer=23 | ventana=True  | guarda=calla
11:03:44 UTC | hoy=1 ayer=23 | ventana=True  | guarda=calla
PRIMER POST: 2026-11-09 11:03:30 UTC (08:03:30 Santiago)
```

**El primer post del primer día con cuota 160 cayó 11:03:30 UTC, dentro de la
misma banda 11:00-11:04 de los 14 días sanos anteriores con cuota 33.** La cuota
no movió el arranque, que es lo que esta guarda mira — ahora medido y no
predicho. De paso quedó verificado en producción el borde de la ventana: a las
10:57 la guarda calla con `ventana=False`, y a las 11:00 sigue callando porque
falta el deadline.

Un día no es una serie. Lo que hay que re-medir cuando haya 3-4 días, y es una
línea:

```sql
SELECT (posted_at AT TIME ZONE 'America/Santiago')::date AS dia,
       count(*) AS total,
       to_char(min(posted_at), 'HH24:MI') AS primero_utc
  FROM deal_posts
 WHERE telegram_message_id IS NOT NULL AND posted_at >= '2026-11-09'
 GROUP BY 1 ORDER BY 1;
```

Lo único que invalidaría el umbral es que **el primer post empiece a salir más
tarde** que 12:00 UTC. Con más candidatos el primer post sale igual o antes — y
el 9-nov, con 331 candidatos aceptados y 160 de cuota, salió a las 11:03:30,
igual que siempre.

## 4. Las decisiones que quedan del dueño

1. **Prender la guarda** (`PUBLISHER_ALERTA_CANAL_MUDO=true`). Necesita
   `ALERT_BOT_TOKEN`/`ALERT_CHAT_ID` cargados, que hoy están vacíos, y recrear
   el contenedor del publisher. Receta exacta en `HANDOFF_MERCADOPAGO.md` §5.
2. **El deadline.** El default es **13:00 UTC** porque es lo que el backtest
   sostiene. Las tres opciones, con su costo medido:
   - **13:00 UTC (default)** — 3 disparos en 49 días, 0 falsos. ~1 h de holgura
     sobre el primer post más tardío observado y 9 h de ventana para reaccionar.
   - **12:00 UTC** — 23 falsos positivos en los días de la ventana vieja. Hoy
     daría 0 falsos y avisaría de retrasos de una hora, pero vuelve a ser
     inservible el **2027-04-04**, cuando Santiago pase a UTC-4. No lo
     recomiendo, y la razón ya no es un argumento sino una medición.
   - **Atarlo a la ventana** en vez de a UTC (p. ej. "2 h después de
     `WINDOW_START_HOUR`): sobrevive al cambio de hora y a mover la ventana.
     Es un cambio de forma del parámetro, no de valor, y **no lo hice porque no
     me lo pidieron**: la decisión pedida era el número. Si el dueño lo quiere,
     son ~5 líneas en `canal_mudo_hoy` y el backtest de arriba se vuelve a
     correr tal como está.
