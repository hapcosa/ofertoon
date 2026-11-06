# Nice One — investigada; desafío confirmado

**Medido el 2026-11-06 14:25 UTC.** Una solicitud a
`https://www.niceone.cl/` con `BROWSER_HEADERS` siguió la redirección
normal a `https://n1g.cl/Home/` y recibió **403**, `cf-mitigated: challenge`.
El destino `n1g.cl` es el host vigente observado, pero tampoco entrega
catálogo con los headers del proyecto. Confirma bot management; se detuvo ahí.
La vía pendiente es un feed o acceso acordado.

```bash
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py browser https://www.niceone.cl/
```
