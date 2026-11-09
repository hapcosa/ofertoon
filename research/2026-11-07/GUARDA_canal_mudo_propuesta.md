# Propuesta: guarda de "el canal no publicó", medida contra `deal_posts`

Escrito el 2026-11-07, desde `feat/mercadopago`. Es una propuesta y una
medición, **no una implementación**: la decisión de prender una alerta es del
dueño (CLAUDE.md, convenciones), y esto queda documentado para que la tome con
números delante, no a ojo. No toqué `alerts.py` ni `publisher/` — ninguna de
las dos tiene código nuevo por esta propuesta.

## Por qué esto, y por qué ahora

`research/2026-11-06/INCIDENTE_canal_mudo.md` ya diagnosticó la causa (un
despliegue del scraper reagenda el ciclo de 12h y el pipeline viaja a bordo de
la pasada) y la mitigación operativa (`scrapers.runner --once` después de un
redeploy). Lo que esa nota deja explícitamente abierto es que **ninguna guarda
mira el canal**: `runner.pasadas_flacas` y el canario miran la ingesta: un día
con 0 publicaciones y todos los servicios `Up` no dispara nada.

Queda en mi lado porque una vez que haya suscriptores pagando por MercadoPago
o PayPal, un día sin publicar es un día de servicio no entregado — no un
detalle de scraping.

## Medido contra producción (SELECT, sin escribir nada)

```
fecha        posts
2026-10-27       6   ← parcial, es el primer día de una ventana más corta
2026-10-28      21
2026-10-29      23
2026-10-30      24
2026-10-31      21
2026-11-01      22
2026-11-02      25
2026-11-03      25
2026-11-04      34
2026-11-05      25
2026-11-06       0   ← el incidente ya diagnosticado
2026-11-07       0   ← medido hoy; puede ser recuperación en curso, no asumir que es otro incidente sin mirar scrape_runs primero
```

Los siete días sanos (28-oct a 5-nov) van de **21 a 34**, mediana 25. El primer
post del día, en esos mismos días, cae siempre entre **11:00 y 11:04 UTC**
(dato de `INCIDENTE_canal_mudo.md`), que es justo después de que abre la
ventana de publicación (`WINDOW_START_HOUR`, 08:00 Santiago = 11:00 UTC).

## La propuesta: mirar el PRIMER post del día, no el total

Un chequeo de "posts totales hoy" solo puede disparar al final del día, cuando
ya no hay nada que hacer. El patrón del incidente —y el de cualquier repetición—
es que el canal se queda mudo **desde la apertura de la ventana**, así que la
señal útil es más temprana: ¿ya pasó la hora en que históricamente sale el
primer post, y todavía no salió ninguno?

```python
def canal_mudo_hoy(
    posts_hoy: int,
    posts_ayer: int,
    ahora: datetime,            # UTC
    deadline_hour_utc: int = 12,  # 1h de margen sobre el 11:00-11:04 medido
) -> str | None:
    """None si no hay nada que reportar.

    `posts_ayer > 0` es la guarda contra falsos positivos de una categoría
    recién conectada o un día de verdad sin candidatos maduros: si AYER
    tampoco publicó nada, esto no es una caída nueva y no es esta alerta la
    que tiene que hablar.
    """
    if posts_ayer == 0:
        return None
    if posts_hoy > 0:
        return None
    if ahora.hour < deadline_hour_utc:
        return None
    return (
        f"🔇 OfertasCL — el canal no publicó nada hoy y ya son las "
        f"{ahora:%H:%M} UTC (el primer post suele salir 11:00-11:04). "
        f"Ayer publicó {posts_ayer}."
    )
```

Mismo estilo que `alerts.format_summary`: función pura, `None` cuando no hay
nada que decir, un dato (`posts_ayer`) que evita alarmar sobre un día que ya
viene mudo por una razón de producto (sin candidatos maduros) y no por una
falla operativa.

## Dónde iría, si se decide escribirla

**No en `scrapers/runner.py` ni en `alerts.py` tal como están.** Las dos
viven del lado de la ingesta y no saben nada de `deal_posts`. El lugar natural
es el loop de `publisher/daemon.py`, que ya tiene reloj propio
(`PUBLISHER_POLL_SECONDS`) y ya sabe leer `deal_posts` para decidir qué
publicar — agregar una consulta de "cuántos posteé hoy y ayer" en el mismo
lugar es la extensión mínima, no una guarda nueva y aislada.

No escribí ese wiring: abrir `publisher/daemon.py` y tocarlo es crear
superficie en un proceso que ya está posteando de verdad, y esta sesión tenía
como mandato MercadoPago, no el publisher. Si se decide activar esto, la
función de arriba ya está pensada para no necesitar más que:
1. Una query a `deal_posts` por los dos días (misma query de este documento).
2. Un llamado a `alerts.send_alert(canal_mudo_hoy(...))` dentro del poll del
   publisher.
3. Decidir `deadline_hour_utc` con el dueño — 12:00 UTC es una propuesta con
   1h de margen sobre lo medido, no una medición en sí misma.

---

## ⚠️ Corrección y backtest del 2026-11-07 (más tarde el mismo día)

**La tabla de arriba tiene mal las dos filas que motivan la propuesta.** Medido
contra `deal_posts` con la ventana completa de cada día:

    fecha        posts   primer post
    2026-11-05      25     11:04 UTC
    2026-11-06      23     17:18 UTC   ← NO fue 0: publicó, pero 6 h 18 min tarde
    2026-11-07      22     11:00 UTC   ← NO fue 0: día normal

El error vino de leer con una ventana relativa (`now() - interval 'N days'`),
que **trunca el día del borde** y lo hace ver vacío o corto. Es la misma forma
del error que este repo castiga en otras diez trampas: el número estaba bien
calculado sobre datos mal recortados. Al medir por `posted_at::date` completo,
los dos ceros desaparecen.

Esto **no invalida la propuesta: la fortalece**, y hay que decir por qué. Si el
6-nov hubiera sido de verdad 0 posts, un chequeo de total diario lo habría
visto. Lo que de verdad pasó —publicó 23, pero recién desde las 17:18, perdiendo
6 h 18 min de una ventana de 15 h— **un chequeo de total diario NO lo ve**:
a las 23:00 el total era 23, perfectamente sano. Solo lo ve el chequeo del
**primer post**, que es exactamente lo que esta propuesta eligió.

### Backtest de `canal_mudo_hoy` contra los 12 días reales

Evaluada a las 12:00 UTC de cada día, con `posts_hoy` = los publicados hasta esa
hora y `posts_ayer` = el total del día anterior:

    día           total   ≤12:00   veredicto
    2026-10-27       19        2   — calla
    2026-10-28       21        2   — calla
    2026-10-29       23        2   — calla
    2026-10-30       24        2   — calla
    2026-10-31       21        2   — calla
    2026-11-01       22        2   — calla
    2026-11-02       25        2   — calla
    2026-11-03       25        2   — calla
    2026-11-04       34        2   — calla
    2026-11-05       25       10   — calla
    2026-11-06       23        0   🔇 DISPARA   ← el incidente
    2026-11-07       22       10   — calla

**Cero falsos positivos en 11 días sanos, y dispara exactamente en el único día
malo.** El caso de control está adentro de la tabla: son las 11 filas que tienen
que callar.

### Pero el margen es de UN post, y eso sí hay que decidirlo

En los días sanos hay **2 posts** publicados a las 12:00 UTC, no veinte: el
primero sale 11:00-11:04 y el siguiente ~30 min después (`MIN_MINUTES_BETWEEN`).
Así que el `deadline_hour_utc = 12` tiene **~56 minutos de holgura** sobre el
primer post más tardío observado (11:04), y la condición se cumple por 2 posts
de margen, no por un colchón cómodo.

Consecuencia práctica: cualquier cosa que retrase el primer post una hora
—un pipeline lento, un reinicio del publisher a las 10:30, una pasada que
termina justo— dispara la alerta sin que haya una caída. Eso no la invalida (una
alerta que avisa de un retraso de una hora es útil), pero **hay que decidirlo a
propósito**: o se acepta que avise de retrasos además de caídas, o el deadline
se mueve a 13:00 UTC, que compra 2 h de holgura y sigue dejando 9 h de ventana
para reaccionar. **Es decisión del dueño y no la toma un agente.**
