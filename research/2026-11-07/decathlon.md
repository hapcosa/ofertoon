# Decathlon — investigada; 403 confirmado

**Medido el 2026-11-06 14:25 UTC.** Una solicitud a
`https://www.decathlon.cl/` con `BROWSER_HEADERS` del proyecto devolvió
**403** y `cf-mitigated: challenge` de Cloudflare. Confirma el bloqueo previo
en este host; no se reintentó ni se intentó resolver el desafío. No hay fuente
de precios comprobada en esta medición. La vía pendiente es un feed o acceso
acordado con la tienda.

```bash
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py browser https://www.decathlon.cl/
```
