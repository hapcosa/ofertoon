# Verificación pre-deploy — 2026-11-06

Los tres chequeos que deciden si el despliegue puede correr, con el comando que
los reproduce. Ninguno está cubierto por la suite: los tres miran la **base** o
**varios árboles a la vez**, y un `pytest` en verde no dice nada sobre ellos.

Correrlos **antes** de `docker compose build` y de `db-migrate`, no después.

---

## 1. Checksums: ¿coincide la secuencia del árbol con lo aplicado?

Un checksum distinto en un archivo **ya aplicado** es `checksum_mismatch`, y
entonces `migrate.py` **no aplica nada** — ni esa migración ni ninguna otra. Es
el bloqueo más caro porque no se ve hasta que se intenta, y el mensaje no dice
"tu árbol está viejo", dice el nombre del archivo.

Medido el 2026-11-06 sobre los cuatro árboles:

    árbol                 archivos  mismatch  pendientes
    ofertoon (main)             46         0  --
    ofertoon-unimarc            48         0  47
    ofertoon-bloqueadas         48         1  50, 51   ← 40_ripley_hites.sql
    ofertoon-mercadopago        47         0  51

`ofertoon-bloqueadas` tiene la versión **anterior** de `40_ripley_hites.sql`
(md5 `6dd670…` contra `e5dbca…`): su worktree nació de `a2d8c06` y la reescritura
—la que agrega `stores.publish_enabled` y conecta `pc-express`— se hizo en el
árbol de trabajo de `main` y se commiteó después, en `326057d`. Desde ese árbol
el deploy entero está bloqueado.

🟢 No contamina `main` al mergear, verificado: la rama **nunca tocó** el archivo
(`git log a2d8c06..HEAD -- migrations/40_…` vacío), así que git conserva el de
`main` y el árbol mergeado trae el correcto.

## 2. Números de migración: ¿hay dos archivos con el mismo?

El reparto por escrito **no alcanza** — se escribió, se comunicó, y el 6-nov
hubo igual dos `51_` en dos worktrees que no se veían (Sparta y MercadoPago),
porque el aviso llegó tarde a un tercer agente. La primera vez que pasó, dos días
antes, obligó a renumerar la tanda 40-44 entera.

El número libre **no es** `ls migrations/ | tail -1` del árbol propio:

```bash
for d in ~/servicios/ofertoon*; do
  find "$d/migrations" -maxdepth 1 -name '*.sql' -printf '%f\n' 2>/dev/null
done | grep -oE '^[0-9]+' | sort -n | tail -1
```

## 3. Adapters: ¿los resuelve la imagen que vas a construir?

CLAUDE.md §Pasos 1.7: si `stores.adapter` nombra un módulo que la imagen no
tiene, `resolve_adapter` falla y **todas las llaves de esa tienda quedan
`failed` cada pasada**. La pregunta correcta no es "¿están los archivos?" sino
"¿resuelve este árbol todo lo que la base va a nombrar, incluido lo que las
migraciones pendientes van a insertar?".

El 2026-11-06 sobre el árbol mergeado: **31 adapters en `stores` + `unimarc` de
la 47 pendiente, los 32 resuelven**. Con caso de control — un módulo inexistente
tiene que fallar, y falla con `ModuleNotFoundError`.

Los scripts de los tres chequeos son cortos y se rehacen en minutos; lo que
importa es que existan como paso, no el código. La lógica: leer
`schema_migrations`, comparar `sha256[:32]` como hace `migrate.checksum`, y
llamar a `runner.resolve_adapter` sobre cada `stores.adapter` más los que
aparezcan en las migraciones pendientes.

---

## Lo que queda fuera de estos tres, y hay que mirar igual

- **Las `store_categories` no las verifica ningún test** (el `_truncate_state`
  del conftest las trunca entre tests). Se miran en la base, o se aplica la
  secuencia completa sobre una base descartable propia.
- **`listo — 0 migración(es) aplicada(s)`** es a la vez el mensaje de una corrida
  sana y el de "tu migración no está en esta imagen".
- **`docker ps` puede decir `Up` de un contenedor vacío**, y un `command` de
  compose desactualizado deja un endpoint nuevo en 404 con el servicio en `Up`.
