# AGENTS.md

**Leé [`CLAUDE.md`](CLAUDE.md) antes de tocar nada.** Es la puerta de entrada de
este repo y te dice qué leer según lo que vas a hacer.

Este archivo existe solo para redirigir. **No duplica las reglas a propósito**:
dos copias de la misma regla se desincronizan, y entonces la que leés no es la que
rige. Si buscás algo acá y no está, está en `CLAUDE.md`.

## Lo mínimo, para que nadie empiece mal

Tres cosas que cuestan caro y están explicadas en `CLAUDE.md`:

1. **El valor del proyecto está en el detector, no en el scraping.** El descuento
   se mide contra nuestra propia baseline de 60 días, nunca contra el precio
   tachado que declara la tienda. Romper eso produce el producto que este
   proyecto existe para no ser.
2. **Verificá el efecto, nunca el mensaje.** Acá el mensaje de éxito y el de "no
   hizo nada" son idénticos en varios lugares (`--dry-run`, `db-migrate` sobre
   una imagen vieja, `docker ps` de un contenedor vacío).
3. **No commitees ni pushees salvo que te lo pidan.**

## Mapa de documentos

| archivo | qué es |
|---|---|
| [`CLAUDE.md`](CLAUDE.md) | **empezá acá.** Reglas, pasos y qué leer según la tarea |
| [`TRAMPAS.md`](TRAMPAS.md) | trampas verificadas contra producción, agrupadas por situación. Buscá tu sección, no lo leas entero |
| [`PLAN_TIENDAS.md`](PLAN_TIENDAS.md) | checklist de conexión de una tienda (§5) |
| [`PLAN_EXPANSION.md`](PLAN_EXPANSION.md) | verticales nuevas y las doce preguntas de investigación (§1) |
| [`PLAN_SUPERMERCADO.md`](PLAN_SUPERMERCADO.md) | supermercado y belleza |
| [`TIENDAS.md`](TIENDAS.md) | censo: qué está conectado y qué va a entrar |
| [`TIENDAS_PROHIBIDAS.md`](TIENDAS_PROHIBIDAS.md) | lo que no se puede, con la razón medida y su fecha |
| [`HANDOFF.md`](HANDOFF.md) | estado y traspaso de sesión |
| [`DEPLOY.md`](DEPLOY.md) | puesta en producción |

**El "por qué" de cada decisión de la base vive en el header de su migración.**
Si algo en el esquema te sorprende, `grep` en `migrations/` antes de preguntar.
