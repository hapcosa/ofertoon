# El canal publicó CERO el 2026-11-06, y ninguna guarda lo reportó

Encontrado el 2026-11-06 16:35 UTC mirando la base, no un log de error: **no hay
ningún `deal_post` del 6-nov**, contra 21 a 34 por día en los siete días
anteriores.

    fecha        posts   primero   último
    2026-11-06       0        --       --     ← hoy
    2026-11-05      25     11:04     19:25
    2026-11-04      34     11:03     18:59
    2026-11-03      25     11:02     23:03
    2026-11-02      25     11:01     23:07
    2026-11-01      22     11:00     21:30
    2026-10-31      21     11:04     21:04

No hay un solo error en pantalla. El `publisher` dice `Up 13 hours`, su proceso
está vivo (`python -m publisher.daemon`, 12:58 de `etime`) y su última línea de
log es la de arranque: `publisher_daemon_started poll_seconds=300 enabled=True
bot_token=True`. Trece horas de silencio que se leen igual que trece horas sanas.

## La cadena, y cada eslabón es correcto

1. **03:34:08** — se aplica la migración 40 (PC Express).
2. **03:37:30** — se reconstruyen y reinician `scraper` y `publisher` para que la
   imagen traiga `scrapers/stores/pc_express.py`. Correcto: CLAUDE.md §Pasos 1.7
   manda construir antes de migrar.
3. **03:37:30** — el runner arranca y loguea
   `última pasada hace poco; la próxima en 12.0 h`. **También correcto**:
   `espera_hasta_proxima` existe justo para que cada despliegue no meta una pasada
   extra —su docstring cuenta las 562 corridas del crash-loop del 18-sep— y
   ancla el intervalo al arranque de la última pasada, no al del proceso.
4. Entonces **la pasada de ~03:35 no ocurre**, y con ella no ocurre su
   `run_pricing`. El pipeline corre **dentro** del loop, después de `run_once`,
   así que sin pasada no hay baselines nuevas ni detector. Último detector:
   5-nov 18:51 UTC. Verificado: `3:37:30 + 12 h = 15:37:30` y la pasada real
   arrancó **15:34:51**.
5. Los últimos candidatos aceptados son de las **5-nov 18:51 UTC**, y
   `curation.ranker.MAX_AGE_HOURS = 13` los vence a las **6-nov 07:51 UTC**
   (04:51 de Santiago). **También correcto**: un aceptado con más de un ciclo de
   scraping encima tiene un precio sin verificar, y el canal promete no publicar
   un precio que ya no existe.
6. La ventana de publicación abre a las **08:00 locales = 11:00 UTC**
   (`WINDOW_START_HOUR`, `TZ = America/Santiago`). Al abrir, **todos los
   candidatos estaban vencidos hacía más de 3 horas**.

⇒ **Cero publicaciones, sin un solo error, con todas las guardas funcionando como
se diseñaron.**

## Lo que esto cuesta y cómo se evita

El costo no es "una pasada a medias" —que es lo que CLAUDE.md §Trabajo
multi-agente §4 advierte al prohibir reiniciar el scraper desde un worktree—:
es que **un despliegue del scraper le cuesta al canal hasta un día entero de
publicación**, porque reagenda el ciclo de 12 h y el pipeline viaja a bordo de la
pasada. Con 0 suscriptores hoy es gratis. Con suscriptores pagando, es un día sin
producto.

La herramienta ya existe y el propio runner la documenta: **`--once` es una orden
directa del operador y corre sin esperar a que toque.** Después de un despliegue
que reinicie el scraper:

```bash
docker compose exec scraper python -m scrapers.runner --once
```

Eso dispara la pasada y su `run_pricing`, repone candidatos frescos y la ventana
de publicación los encuentra. No desarma ninguna guarda: `espera_hasta_proxima`
sigue protegiendo el caso que le importa, que es el reinicio **no** supervisado.

Hoy se recupera solo: la pasada de las 15:34 termina alrededor de las 17:30 UTC y
su pipeline repone candidatos para la ventana que cierra a las 23:00 locales.
Vale confirmarlo mirando `deal_posts` después de esa hora, no el log.

## Y lo que no cubre ninguna guarda

`runner.pasadas_flacas` vigila pasadas con pocas observaciones y el canario vigila
llaves que traen menos de lo suyo. **Ninguno de los dos mira el canal.** Un día
con cero publicaciones y el publisher sano no dispara nada — ni un log, ni una
alerta. Si el canal tiene que publicar todos los días, eso es una guarda que
falta, y es de una altura distinta a las dos que ya existen.
