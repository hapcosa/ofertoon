# La Polar — investigada; dominio redirige a ABC

**Medido el 2026-11-06 UTC.** `https://lapolar.cl/` aún falla TLS por
certificado expirado, con verificación normal. `https://www.lapolar.cl/` sí
tiene TLS válido, responde 200 y **redirige a `https://www.abc.cl/`**, cuyo
título es «abc.cl | Lo nuevo por mucho menos». El host `www` es viable, pero
no ofrece un catálogo independiente de La Polar: investigar ABC como tienda
propia si interesa su cobertura, sin duplicarla bajo slug `la-polar`.

Reproducir (una solicitud por host, sin desactivar TLS):

```bash
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py default https://lapolar.cl/
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py default https://www.lapolar.cl/
```
