# Despliegue del 2026-11-09 — seis migraciones en una sola corrida

Lo que estuvo pendiente cuatro días se aplicó junto, porque las ramas eran
interdependientes **a través de la base** (CLAUDE.md §Trabajo multi-agente §5):
ninguna se podía desplegar sola.

## Lo aplicado

    47  Unimarc + price_points.price_condition
    50  Rockford (rkflife.com)
    51  MercadoPago: price_clp, mercadopago_plan_id, mercadopago_webhook_events
    52  Sparta, tajada disjunta de 63 llaves
    53  min_history_days = 10 y las cinco tiendas abiertas al canal
    55  cuota 20 en los ocho temas  (+ los topes finos a 20 en ranker.py)

La 49 nunca se escribió y queda muerta: un número sin archivo es inofensivo.

## Los tres chequeos pre-deploy, antes de tocar nada

    1. CHECKSUMS   53 archivos, 47 aplicadas, mismatch 0
    2. NÚMEROS     máximo 55, ningún número con dos archivos distintos
    3. ADAPTERS    rockford, unimarc, sparta y pc_express resuelven los cuatro
                   control: un módulo inexistente falla con ModuleNotFoundError

Y la imagen se verificó **antes** de migrar (§Pasos 1.7): `db-migrate` lista las
seis migraciones y los tres adaptadores nuevos dentro del contenedor, no en el
árbol de trabajo.

## El efecto en la base, no el mensaje

    migraciones aplicadas  53
    piso de historia       10 en las 17 categorías
    cuotas                 160 en 8 temas, mínimo 20
    tiendas                34 — publican 34
      unimarc 8 llaves · rockford 4 · sparta 63 · pc-express 8 · ripley 1
    price_points.price_condition              presente
    telegram_tier_plans.mercadopago_plan_id   presente

## El caso de control del webhook, que es el que cobra

El `command` de compose cambió a `subscriptions.webhooks` (entrypoint combinado),
así que el contenedor se recreó. Lo que hay que verificar después **no** es que el
endpoint nuevo responda:

    /health               200
    /webhook/paypal       400   ← rechaza body vacío: la ruta EXISTE
    /webhook/mercadopago  503   ← existe, sin credenciales cargadas
    /webhook/no-existe    404   ← el control: prueba que los otros son reales

Sin el 404 de control, un 400 y un 503 podrían ser de un catch-all y no
significarían nada.

## El error del despliegue, y la trampa que dejó

El ciclo de 12 h disparó una pasada a las **04:50** y el `up -d
--force-recreate` entró a las **04:53**: se cortó una pasada en **79 de ~800
corridas** (72 `ok`, 6 `partial`) y quedó **una fila huérfana con
`status='running'`**, que no se cierra nunca.

No se perdieron observaciones —las 72 escribieron— pero sí `run_pricing`, que
vive al final del loop. Último detector antes del arreglo: 2026-11-08 17:57 UTC.

**Lo que faltó fue una consulta de diez segundos antes de recrear**, y ahora está
en TRAMPAS **F**: el momento más probable de que haya una pasada en vuelo es
justo cuando desplegás, porque el ciclo arranca a una hora derivada de la última
pasada y no de cuándo desplegás vos. Es una lotería de 2 h sobre 12.

## El arreglo: `--once` detached

    docker compose exec -d scraper python -m scrapers.runner --once

Detached a propósito: la pasada tiene que sobrevivir a la sesión que la dispara.
Arrancó 04:55 y la aritmética cierra — termina ~06:55, el pipeline detrás, y los
candidatos viven 13 h (`ranker.MAX_AGE_HOURS`), así que cubren la ventana de
11:00 a ~19:50 UTC.

## Qué queda por verificar, y en qué mirarlo

1. **Las tres tiendas nuevas ingiriendo**: `scrape_runs` por tienda con
   `items_ok > 0` y sin `failed`. Si `resolve_adapter` fallara, sus llaves
   quedarían `failed` **cada pasada** y el síntoma no es un error de despliegue.
2. **El pipeline con los números nuevos**: es la primera corrida con piso 10 y
   cuota 160. Lo anterior fue 22-25 publicados de 33 con piso 20.
3. **`deal_posts` después de las 11:00 UTC** — no el log del publisher, que
   quedó callado seis horas el 6-nov sin un solo error.
