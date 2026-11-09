# Salesforce (Tricot y ABC) — re-medición del 2026-11-07 UTC

## Decisión de acceso

La premisa del prompt cambió durante la medición. `https://www.tricot.cl/robots.txt`
respondió 200 y hoy **prohíbe `/*?start*` y `/*&start*`** para `User-agent: *`.
La ruta `/accesorios/hombre?start=0&sz=60` respondió 200, con 60 productos,
antes de leer esa regla; no se paginó más tras hallarla. Tampoco se usa
`/search*` ni los controladores Demandware. Una categoría sin paginación no
permite responder cobertura, orden, centinelas, GTIN entre páginas ni llaves
disjuntas. **Tricot queda sin adaptador ni migración** hasta hallar una fuente
permitida o recibir acceso acordado. La afirmación de
`INVESTIGACION_ropa.md` §2 sobre `?start` permitido está corregida allí.

| Pregunta del plan | Tricot | ABC, candidata `/mujer/ropa-mujer/` |
|---|---|---|
| 1. Plataforma | Salesforce Commerce Cloud | Salesforce Commerce Cloud |
| 2. Robots | 200; `?start` prohibido ahora | 200; categoría con `zone` y `start` permitida; sin Crawl-delay |
| 3. Headers | La categoría limpia respondió 200; no se hizo batería por ruta de paginación prohibida | Tres modos, 200×4 cada uno en `/mujer/` |
| 4. Paginación | Ruta necesaria prohibida | `start=N&sz=36`; 23 páginas con tiles y una vacía |
| 5. Orden | No se re-mide por política de ruta | Dos recorridos completos, 824/824 IDs iguales |
| 6. Total | No medido ahora | 824 declarados y 824 enumerados en la hoja; el paraguas falla por dos |
| 7. GTIN | No medido ahora | 0/824 tiles, en 23 páginas |
| 8. Precio normal | No medido ahora | 774/824 tiles con `Normal`; no se usa como baseline |
| 9. Stock | No medido ahora | Ninguna señal en el tile; falta un agotado de control |
| 10. Centinelas | No medido ahora | máximo $29.990 en los 824 precios de la hoja |
| 11. Llaves | No medido ahora | Solo la hoja de ropa es candidata; cruza 2 IDs con calzado |
| 12. Costo | No se estima pasada sin ruta permitida | 24 requests, 45,31 MB y 824 filas por pasada de la hoja; a 0,5 rps serían ~48 s de pausas |

La fila de stock y la ausencia de una señal para separar vendedores terceros
impiden escribir un adaptador seguro. La migración 54 sigue libre.

`https://www.abc.cl/robots.txt` respondió 200 y no prohíbe `?zone=...&start=N&sz=36`
en la URL de categoría. Sí prohíbe `/on/demandware.store/*`, `*cgid=*`,
`*srule*` y `*page=*`: no se usaron. La zona se fijó en
`inventory_LaPolar_whven|t_ecom_metropolitana`, publicada por los enlaces de
la propia tienda. **Cambiarla después invalidaría el histórico de precios**.
En la categoría limpia `/mujer/`, `DEFAULT_USER_AGENT`, `BROWSER_USER_AGENT`
y `BROWSER_HEADERS` dieron **200/200/200/200** cada uno. El detalle reproducible
está en `abc_headers_2026-11-07.ndjson`.

## ABC: recorrido de `/mujer/`

Dos recorridos completos con `abc_audit.py` enumeraron **los mismos 2.040 IDs
únicos** (Jaccard **1,0000**), 57 páginas
con productos y una final sin tiles, **110,67 MB** decodificados en 58 requests.
El listado declaró **2.042 productos** en la primera página, diferencia de dos;
por eso no se activa un canario exacto sin resolverla. Los 2.040 tiles dieron
precio Internet parseable, de **$1.500 a $69.990**; 1.541 expusieron precio
`Normal` declarado. El parser considera Internet como precio efectivo; el
descuento real sigue saliendo exclusivamente de la baseline propia. En los
tiles no apareció `itemprop=gtin*`, texto de agotado ni marcas
`marketplace`/`vendedor`/`vendido por`/`seller`. Esto **no demuestra** que toda
ABC carezca de vendedores terceros o que el listado filtre agotados. Falta un
caso de control de producto agotado y revisar otras categorías.

En la primera página de `/hombre/`, `/belleza/` y `/tecnologia/` tampoco se
observó una señal de stock ni vendedor en los tiles. `/tecnologia/` tuvo **40
tiles con `sz=36`**, otro motivo para no generalizar el conteo de `/mujer/` a
todo ABC sin estudiar el grid. En 30 fichas de producto elegidas de
`sitemap_2-product.xml` con semilla 20261107 y 20 de `sitemap_0-product.xml`
con semilla 20261108, la etiqueta schema.org fue `InStock` en las **50/50**:
sigue faltando un agotado como control. Primera y última página de `/mujer/`
tampoco tienen `stock`, `availability` ni `inventory` en los HTML de sus tiles.

Los IDs y estadísticas de los dos recorridos están en
`abc_mujer_{first,second}_*.json`. `/mujer/` mezcla ropa, calzado y accesorios,
así que no es una llave apta para una sola categoría interna. Se recorrieron
dos hojas de navegación para medir llaves mapeables.

La hoja canónica `/mujer/ropa-mujer/` entregó **824 IDs únicos en dos pasadas
idénticas** (Jaccard 1,0000), exactamente los 824 declarados; 23 páginas con
datos y una final vacía, **45,31 MB** por pasada. Precio Internet en 824/824,
precio Normal en 774/824, rango $2.000–$29.990, sin GTIN ni señal de stock en
los tiles. **822 IDs aparecen también en `/mujer/`, pero dos faltan allí**:
los dos IDs son `652201` y `652202`. Su unión da exactamente 2.042, el total
que el paraguas declaraba aunque enumeró solo 2.040. Así, el total del
paraguas no prueba cobertura completa.
La llave de calzado que publica el menú como `/mujer/zapatos-mujer/` redirige
a `/calzado/zapatos-mujer/`; el recorrido usa esa ruta canónica. Tiene **284
IDs para 284 declarados**, 8 páginas con datos y una final vacía (**15,45 MB**),
precio Internet $3.990–$69.990 y Normal en 228/284. **Comparte dos IDs con
`/mujer/ropa-mujer/` (`29234787`, `29234795`)**. No se pueden conectar juntas
como llaves disjuntas; por ahora, la única candidata de vestuario aislada es
`/mujer/ropa-mujer/`. Falta también confirmar ausencia de solapes con otras
llaves que se eligieran en el futuro.

Hasta resolver stock y vendedor y seleccionar un conjunto de llaves disjunto,
**no se escribe la migración
54 ni se conecta ABC**. No se cambia el adaptador aplicado de Hites por este
estudio parcial.

## Reproducir

```bash
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py default https://www.tricot.cl/robots.txt
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py default https://www.abc.cl/robots.txt
for mode in default browser_ua browser; do PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/probe.py "$mode" https://www.abc.cl/mujer/ --repeat 4 --delay 2; done
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/abc_audit.py mujer first
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/abc_audit.py mujer second
PYTHONPATH=. /home/donaldchavez/servicios/ofertoon/.venv/bin/python research/2026-11-07/compare_ids.py research/2026-11-07/abc_mujer_first_ids.json research/2026-11-07/abc_mujer_second_ids.json
```

## Revisión del 2026-11-09 UTC — Tricot y ABC conectables, pendiente despliegue

El veredicto anterior de Tricot fue demasiado fuerte: robots sigue prohibiendo
`?start` (confirmado el 9-nov, con los 18 User-agent que comparten reglas),
pero la primera página limpia es una tajada estable, igual que Sparta. No se
pidió ninguna URL `?start` de Tricot. En
`/accesorios/mujer/bananos` hay **10** `.tri-product-tile.product-tile`, 10
URLs de ficha y 10 IDs diferentes. La página declara `Resultados (10)` en
`.js-result-count`; el «30 productos» citado en el prompt venía del texto
genérico de Wishlist, no del total. Se replicó el conteo en las otras ocho
hojas.

Dos pasadas de las nueve hojas, comenzadas **04:36:13 y 04:51:21 UTC** (15 min
08 s de separación real), dieron **Jaccard 1,0000 en cada hoja**, con exactamente
los mismos 465 IDs. Seis hojas muestran menos de lo declarado, pero su primera
página no rotó. Los 465 IDs fueron disjuntos entre todas las hojas, incluso
entre categorías internas.

| Hoja limpia Tricot | Vistos / declarados | Categoría interna |
|---|---:|---|
| `accesorios/mujer/bananos` | 10 / 10 | `ropa-accesorios` |
| `hombre/pijamas` | 60 / 62 | `ropa-vestuario` |
| `mujer/poleras` | 60 / 516 | `ropa-vestuario` |
| `calzado/mujer/zapatillas` | 56 / 56 | `ropa-calzado` |
| `mujer/jeans` | 60 / 96 | `ropa-vestuario` |
| `hombre/jeans` | 39 / 39 | `ropa-vestuario` |
| `infantil/ninas/poleras` | 60 / 72 | `ropa-vestuario` |
| `mujer/ropa-interior/calzones` | 60 / 193 | `ropa-vestuario` |
| `hombre/camisas` | 60 / 78 | `ropa-vestuario` |

**Techo medido:** 465/1.122 (41,4%) de esas nueve hojas, no de todo Tricot.
Una pasada cuesta nueve requests y **12,34 MB** de HTML descomprimido. Los 465
tiles tenían precio efectivo y `Normal`; precio efectivo $490–$16.990; cero
GTIN y cero texto de agotado en los tiles. La señal de descuento del sistema
seguirá siendo la baseline propia de 60 días; `Normal` se conserva solo como
evidencia. `completeness()` reporta el total declarado, por lo que las seis
hojas parciales quedarán visibles como `partial`, no como cobertura completa.

**Control de stock Tricot:** las diez fichas listadas de la hoja completa
`bananos` y las 39 de `hombre/jeans` dieron `schema.org/InStock` en su PDP
(archivos `tricot_stock_*`). Una ficha de jeans con PDP 200,
`jeans-hombre-parches-540141.html`, dio `schema.org/OutOfStock`, botón Agregar
deshabilitado y aviso «AGOTADO»; no está entre los 39 IDs de la hoja completa
`hombre/jeans`. Una ficha antigua de banano (`640664`) también seguía como
PDP 200 agotado y faltaba de la hoja completa de 10. Sus breadcrumbs ya no
apuntan a la hoja actual, por lo que esto respalda el filtrado de agotados,
pero no prueba que jamás pueda aparecer un agotado en otra hoja. El adaptador
marca `in_stock=True` para los tiles de estas nueve hojas y se debe vigilar
el primer ciclo real. No se consultó el sitemap como feed de precios: mezcla
fichas antiguas y agotadas.

**Control de stock ABC:** con la zona fija
`inventory_LaPolar_whven|t_ecom_metropolitana`, el PDP 200 de la chaqueta
Mujer Alma **611179** mantiene breadcrumb `Mujer > Ropa Mujer > Chaquetas y
Parkas`, botón «Agotado» deshabilitado y URL canónica con el mismo ID. No
apareció entre los **820/820** IDs del recorrido completo de
`/mujer/ropa-mujer/` del 9-nov. Tampoco aparecieron otras fichas agotadas
comprobadas, pero algunas cambian de ID canónico o pertenecen a otra hoja;
611179 es el control limpio. Como positivo, la polera **635116**, primer tile
del listado actual, tuvo botón «Agregar a la bolsa» habilitado en su PDP con
la misma zona. El listado tuvo 23 páginas con productos y una final vacía;
frente al 7-nov, bajó de 824 a 820 (siete IDs salieron, tres entraron). Así
se explica la ausencia de marca de stock en los tiles: en la hoja medida, los
agotados comprobados no se listan. No se extiende la conclusión a otras hojas
ABC. La hoja de ropa conserva su coste de ~24 requests y ~45 MB por pasada.

`migrations/54_abc_tricot_vestuario.sql` conecta solo estas tajadas, con
`publish_enabled=false`, **sin aplicar**. Los parsers viven en
`scrapers/stores/salesforce_family.py`; fixtures reales de dos tiles por tienda
y contrato en `tests/test_salesforce_family.py`. No se toca Hites ni su
migración aplicada. El 7-nov la hoja ABC de calzado tenía dos IDs compartidos
con ropa; calzado queda fuera de esta migración, y añadirlo exige decidir ese
solape entre categorías internas. La fecha de conexión de cada tienda será su
primera ingesta real en `scrape_runs`; evaluar 30 días observados después con
`scripts.aceptacion_tienda` antes de habilitar publicación.

Evidencia reproducible: `tricot_firstnine_2026-11-09.json`,
`tricot_secondnine_2026-11-09.json`, `tricot_stock_*`, `tricot_pdp_*`,
`abc_stock_controls_2026-11-09.json` y
`abc_mujer_ropa-mujer_2026-11-09.json`. Para re-medir en otra sesión:

```bash
PYTHONPATH=. .venv/bin/python research/2026-11-07/tricot_audit.py robots
PYTHONPATH=. .venv/bin/python research/2026-11-07/tricot_audit.py snapshot firstnine_2026-11-09 /accesorios/mujer/bananos /hombre/pijamas /mujer/poleras /calzado/mujer/zapatillas /mujer/jeans /hombre/jeans /infantil/ninas/poleras /mujer/ropa-interior/calzones /hombre/camisas
# Esperar unos 15 minutos reales antes de la segunda pasada, con las mismas hojas.
PYTHONPATH=. .venv/bin/python research/2026-11-07/tricot_audit.py stock_listing /hombre/jeans
PYTHONPATH=. .venv/bin/python research/2026-11-07/abc_stock_audit.py pdp
PYTHONPATH=. .venv/bin/python research/2026-11-07/abc_stock_audit.py category mujer/ropa-mujer
PYTHONPATH=. .venv/bin/python research/2026-11-07/salesforce_smoke.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. .venv/bin/python -m pytest -p no:cacheprovider -q tests/test_salesforce_family.py
```

La pasada de lectura final del adaptador (sin base de datos) emitió **820 ABC**
con `completeness=(820,820)` y **465 Tricot** en las nueve hojas, todos con
`completeness()` visible. Durante esta pasada el total de `mujer/jeans` cambió
de 96 a 95, mientras sus 60 tiles siguieron presentes; el adaptador leyó el
total vivo y reportó `(60,95)`. La última página ABC omitió contador y grid,
pero conservó la URL canónica de la misma hoja; el parser acepta ese final
solo con esa prueba, para no confundir un 200 extraño con cobertura terminada.
