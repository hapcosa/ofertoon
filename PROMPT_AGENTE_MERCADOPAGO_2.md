# Prompt — agente de pagos, continuación del 2026-11-09

Pegá lo que está dentro del bloque.

---

```
Seguís en `feat/mercadopago` (worktree `~/servicios/ofertoon-mercadopago`). Tus
dos entregables del 7-nov están commiteados (`f2dfe7f`) y revisados:
`HANDOFF_MERCADOPAGO.md` con el runbook completo, y la propuesta de guarda del
canal con su backtest contra los 12 días reales. Los dos están bien hechos — en
particular que hayas corregido tu propia propuesta al descubrir que el margen es
de un post y lo hayas dejado como decisión del dueño en vez de elegir vos.

ESTADO REAL, MEDIDO EL 2026-11-09 — y lo primero que hacés es volver a medirlo
  - **El despliegue está en curso en esta misma sesión**: se están integrando y
    aplicando las seis migraciones pendientes (47, 50, 51, 52, 53 y 55), tu 51
    incluida, con una sola build y una sola aplicación. **Mergeá `main` antes de
    tocar nada** y verificá contra `schema_migrations`, no contra tu árbol: desde
    un worktree sin esos archivos, `migrate.py --status` contesta "sin
    pendientes" y es falso.
  - Cambios que te afectan y no son tuyos: el piso de historia bajó a **10**
    (migración 53), las cinco tiendas que no publicaban se abrieron, y la cuota
    de cada tema pasó a **20** con los topes finos de `curation/ranker.py`
    también en 20 (migración 55). El techo del canal ahora es **8 × 20 = 160/día**
    contra los 22-25 que venía publicando.
  - 🔴 **GATE_ENABLED=true + `vip.gate_enabled=true` + canal cargado**, y
    **ninguna variable `MERCADOPAGO_*` en el `.env` de producción**. Tu webhook
    contesta 503 y eso es correcto.

TU TRABAJO, EN ORDEN

1. **ESCRIBÍ LA GUARDA, CON EL DEADLINE CONFIGURABLE Y SIN ELEGIRLO VOS.** Tu
   propuesta dejó la elección al dueño —aceptar que avise de retrasos de una hora
   con deadline 12:00, o moverlo a 13:00 y comprar 2 h de holgura— y eso sigue
   siendo suyo: es un umbral, y los umbrales los decide él (§Pasos 2).
   Implementalo como **parámetro con default 13:00 UTC**, que es la opción que
   recomendaste y la que deja 9 h de ventana para reaccionar, y dejá en el
   HANDOFF la línea para cambiarlo a 12:00 si el dueño prefiere que avise de
   retrasos. Así la guarda se puede escribir y probar sin que la decisión quede
   trabada, y cambiarla después es una variable y no un rediseño.
   Escribí `canal_mudo_hoy` donde tu propuesta dice que va, con estas dos cosas
   que tu propio documento pide y que son el núcleo de la guarda:
     - **mirar el PRIMER post del día, no el total** — es lo que distingue "no
       arrancó" de "publicó poco", y son dos fallas distintas;
     - **no disparar fuera de la ventana** (`ranker.WINDOW_START_HOUR` /
       `WINDOW_END_HOUR`, hora de Santiago): antes de que abra no hay nada que
       reportar.
   Con tests, y con el caso de control que la guarda necesita: **un día sano no
   tiene que disparar**. Una guarda que avisa siempre es ruido y se mutea, que es
   peor que no tenerla.
   ⚠️ Y re-backtesteala contra los días **posteriores al despliegue**: con la
   cuota en 160 el volumen diario cambia, y un umbral calibrado sobre días de 22
   posts puede no significar lo mismo sobre días de 100. Si tu condición mira el
   primer post y no el total, debería aguantar — **verificalo, no lo supongas**.

2. **PRENDER LA ALERTA ES DEL DUEÑO, PERO PREPARALE EL INTERRUPTOR.** `alerts.py`
   lee `ALERT_CHAT_ID` y `send_alert`. Dejá la guarda escrita, probada y
   **apagada por default**, con la variable de entorno documentada en
   `.env.example` y el `UPDATE`/flag exacto para encenderla en el HANDOFF. Es el
   mismo patrón que la regla 8: el gate se prende último y su default es apagado.

3. **VERIFICAR TU PROPIO RUNBOOK CONTRA EL DESPLIEGUE QUE ACABA DE PASAR.** Tu
   §2.4 y §2.5 describen aplicar la 51 y recrear el webhook. Eso ocurrió en esta
   sesión como parte del despliegue conjunto, así que **el runbook ya no arranca
   donde dice**: revisalo y marcá qué pasos quedaron hechos y qué queda. Lo que
   sigue pendiente de verdad es §2.1 (credenciales), §2.2 (el plan), §2.3 (cargar
   `price_clp` y `mercadopago_plan_id`) y §2.7-2.8 (registrar la notificación y
   verificar un pago real). Un runbook que empieza en un paso ya hecho se abandona
   a la mitad.
   Y el **caso de control de tu §2.6 hay que correrlo ahora**, no después: el
   webhook se recreó con el `command` nuevo, así que verificá que
   **`/webhook/paypal` siga respondiendo** — es el único endpoint que cobra hoy y
   una regresión ahí es silenciosa porque PayPal reintenta.

4. **SI QUEDA SESIÓN: el tier `ferre` está incoherente y nadie lo mira.** Tiene
   `is_active=false`, sin `telegram_channel_id` y sin ids de plan, pero su plan
   mensual de USD 3,99 está marcado `is_active=true`. Hoy es inofensivo porque
   `fetch_active_plans` exige `t.is_active`, así que tu código ya lo neutraliza —
   pero es una fila que miente y el día que alguien active el tier va a ofrecer un
   plan que no se puede cobrar. Proponé: o se completa (canal + ids + precios) o
   se desactiva el plan. **Medí qué falta y reportá; la decisión es del dueño.**

NÚMEROS DE MIGRACIÓN
Tomadas: 47 · 50 · 51 (tuya) · 52 · 53 · 55. La 49 nunca se escribió. La **54 es
del agente de tiendas** (Tricot/ABC). Si necesitás una, tomá la **56** y avisá.
Verificalo con esto y no con `ls` de tu árbol:

    for d in ~/servicios/ofertoon*; do
      find "$d/migrations" -maxdepth 1 -name '*.sql' -printf '%f\n' 2>/dev/null
    done | grep -oE '^[0-9]+' | sort -n | tail -1

QUÉ NO TOCAR
  * `scrapers/`, `migrations/47`, `50`, `52`, `54` → del agente de tiendas.
  * `migrations/53`, `migrations/55` y los topes de `curation/ranker.py` → de
    `feat/piso-diez`. ⚠️ Si tu guarda necesita leer la ventana o la cuota,
    **importalas de `ranker`**, no las copies: son los números que acaban de
    cambiar y una copia queda vieja en silencio.
  * 🔴 **Nunca aplicar migraciones ni reiniciar servicios.** Es del dueño.
  * En los `.md` compartidos: **agregá, nunca reordenes**.
    `HANDOFF_MERCADOPAGO.md` es entero tuyo.

CÓMO SE TRABAJA ACÁ
  * **Verificá el efecto, nunca el mensaje.**
  * **Una prueba sin caso de control es un falso verde** — en una alerta, el caso
    de control es el día sano que NO tiene que disparar.
  * **Un pytest a la vez por base** (`ofertas_test_mercadopago`), y avisá antes de
    una corrida larga: hay tres agentes sobre el mismo Postgres `:5436`, que
    además sirve producción.
  * **No commitees ni pushees salvo que te lo pidan.**
  * **Avisá cualquier decisión que tomes por tu cuenta.** Honestidad 100%: si
    algo falla, decilo con el output.
```
