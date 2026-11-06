# Adidas — investigada; 403 confirmado

**Medido el 2026-11-06 14:25 UTC.** Una solicitud a
`https://www.adidas.cl/` con `BROWSER_HEADERS` respondió **403** con firma
`AkamaiNetStorage`. El `robots.txt` ya era accesible en la medición previa,
pero eso no demuestra acceso al catálogo. La home sigue bloqueada con los
headers del proyecto; se detuvo ahí. Sin fuente de precios comprobada. La vía
pendiente es un feed o acceso acordado.

```bash
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py browser https://www.adidas.cl/
```
