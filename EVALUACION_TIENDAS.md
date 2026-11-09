# Evaluación de Ofertoon — 5 de noviembre de 2026

## Conclusión

El sistema tiene una buena separación entre extracción, historial, detección y
publicación. Su mejor decisión es comparar contra precios observados y mantener
separados el precio general, el de tarjeta y el normal declarado. El principal
obstáculo para ampliar cobertura es que la investigación de tiendas quedó
repartida en planes con estados de distintas fechas. Una portada accesible no
prueba que su catálogo se pueda recorrer; un 403 antiguo tampoco prueba que
siga bloqueado.

Esta evaluación revisó código y documentación y probó fuentes públicas desde
este servidor. No consultó la base de producción ni verificó sus servicios.
No equivale a una auditoría operativa de las tiendas ya conectadas.

## Entregado

- `scrapers/stores/hites.py`: extracción del grid, paginación por enlaces reales,
  stock visible, separación de tarjeta y venta directa. Recorrido en vivo:
  **276/276 entradas enumeradas, 18 productos de venta directa**.
- `scrapers/stores/ripley.py`: extracción de `__NEXT_DATA__` de páginas públicas,
  stock explícito y precios general/tarjeta separados. Anuncios deduplicados;
  vendedores externos excluidos de las series. El canario compara SKUs orgánicos
  únicos con el total declarado y conserva la advertencia de cobertura parcial.
  Segundo recorrido: **907/917 entradas únicas y 95 productos de venta directa**.
  Las 20 páginas suman 917 filas orgánicas, pero hay duplicados entre páginas;
  por eso sumar filas daría una completitud falsa. Ripley queda **inactiva** en
  la migración hasta resolverlo. El primer recorrido obtuvo 903/917 y 94 de
  venta directa: la composición también varía entre recorridos.
- `migrations/40_ripley_hites.sql`: incorporación inicial de notebooks, usando la
  categoría existente y sin bajar sus requisitos de historia. **No aplicada**.
- `scripts/precios_tienda.py`: exportación CSV sin DB ni Telegram. Una extracción
  incompleta guarda lo recuperado y termina con error explícito.
- Fixtures extraídos de respuestas reales: se conservan bloques del catálogo y
  enlaces; se quitan menús y publicidad ajena al listado para reducir tamaño.
- Pruebas para precios con tarjeta, vendedores, stock oculto, centinelas,
  respuestas sin catálogo y paginación repetida.

```bash
.venv/bin/python -m scripts.precios_tienda --store hites --out /tmp/hites.csv
.venv/bin/python -m scripts.precios_tienda --store ripley --out /tmp/ripley.csv
```

El alcance implementado es **notebooks**, no el catálogo completo de estas dos
tiendas. Los precios recuperados hoy no son ofertas históricas confirmadas.
La primera ingesta persistida iniciará su historia; la fecha de escritura del
adaptador no es fecha de conexión.

## Verificaciones de tiendas pendientes

HTTP medido con los headers ya utilizados por el proyecto, sin navegador ni
sesiones privadas. Las respuestas originales quedaron en `/tmp/ofertoon-probes`;
son evidencia temporal, no fixtures permanentes de todas estas tiendas.

| Tienda | Evidencia de esta revisión | Trabajo pendiente |
|---|---|---|
| Ripley | robots y listado públicos 200; precios en Next.js | Resolver cobertura parcial y ampliar categorías |
| Hites | Listado y paginación públicos funcionan | Ampliar categorías y conectar el adaptador |
| Colloky | Árbol público 200; catálogo VTEX 206, 3.673 productos declarados | Dividir categorías por debajo del límite VTEX y validar identidad/variantes |
| Tricot | Listado de poleras 200 con HTML | Su robots excluye `start`: estudiar sitemaps/fichas, no copiar paginación de Hites |
| La Polar / ABCDin | Ambos redirigen a `www.abc.cl` | Una integración ABC; descubrir rutas actuales (la ruta probada de notebooks dio 404) |
| Doite | Portada y robots 200 | Verificar colecciones y precios actuales, no asumir Shopify por el plan viejo |
| Lippi | Portada y robots 200 | Validar colecciones, stock y solapamientos |
| MacOnline | Portada y robots 200 | Identificar fuente de catálogo y probar precios |
| Winpy | Portada y robots 200 | Catálogo con presupuesto ajustado a su Crawl-delay |
| Maicao | Portada 200 con `mobify-data` | Ya no asumir que comparte el mismo grid HTML de Hites |
| Cruz Verde | Portada 200 de solo 2.863 bytes | Ese 200 no demuestra catálogo: comprobar si es shell o bloqueo |
| Salcobrand | Portada y robots 200 | Identificar listado, sucursal y restricciones de promociones |
| Farmacias Ahumada | Portada y robots 200 | Verificar listados y precios generales frente a convenios |
| Unimarc | Catálogo Next.js paginado comprobado: 719/719 SKU; 243 Club Unimarc | Fuente viable; integrar condiciones, contexto de sucursal y publicación |
| Imperial | Listado con 11 precios; luego 520 incluso al repetir la misma URL | Resolver estabilidad y verificar stock antes de activar |
| Lider | Portada y robots 200 | Seguir sitemaps y fichas; acotar volumen por categorías y sucursal |
| PC Express | `pcexpress.cl` da 403, pero `tienda.pc-express.cl` entrega catálogo, precios y paginación | Fuente viable; separar precio por transferencia y otros medios, verificar stock |
| Decathlon | Portada y robots 403 | Solicitar feed/API o acceso autorizado; no integración comprobada |
| MTS | Portada y robots 403 | Solicitar feed/API o acceso autorizado |
| Adidas | Robots 200, portada 403 | Acceso a robots no significa acceso a precios |

Los robots se revisaron en sus dominios, por ejemplo
https://simple.ripley.cl/robots.txt y https://www.hites.com/robots.txt.
Para cualquier nueva ruta hay que revisar su regla concreta. No se ha probado
cada tienda de PLAN_EXPANSION ni cada área de AREAS.md: servicios, eventos y
mayoristas necesitan fuentes y unidades de comparación propias.

## Hallazgos que afectan la calidad

1. **Identidad VTEX por variante:** `_elegir_item` elige el talle disponible más
   barato y `store_sku` usa su `itemId`. Si cambia el talle elegido, cambia la
   serie aunque sea el mismo producto. Antes de reutilizarlo masivamente hay que
   definir series por variante estable o por producto sin mezclar sus GTIN.
2. **Completitud VTEX:** actualmente suma filas, incluso si una página se repite.
   El canario podría alcanzar el total por duplicados. Los nuevos adaptadores
   cuentan identificadores únicos antes de filtrar por vendedor/precio.
3. **Stock:** hay adaptadores anteriores que asumen disponibilidad; conviene
   distinguirla de stock explícito. Los dos nuevos fallan de forma conservadora
   cuando falta evidencia de stock.
4. **Historial y calibración:** CLAUDE.md documenta umbrales sin calibrar y una
   reducción temporal de días mínimos hasta el 6 de noviembre. Hay que contrastar
   ese estado con producción; no se cambió durante esta revisión.
5. **Publicación:** la documentación registra espaciado por tema y cuotas que
   pueden agotarse temprano. Más tiendas no corrige ese reparto.
6. **Cobertura:** registrar por separado tienda investigada, fuente comprobada,
   adaptador probado, ingesta activa y catálogo completo. Son cinco estados
   distintos y los planes antiguos los mezclan.

## Orden de continuación

1. Desplegar Hites tras aplicar la migración y comprobar la primera ingesta.
2. Resolver la discrepancia de Ripley antes de activar su ingesta automática.
3. Colloky, después de resolver la identidad VTEX; Doite/Lippi tras validar las
   colecciones actuales; luego ABC con rutas comprobadas.
4. Unimarc e Imperial merecen una nueva inspección de catálogo: sus portadas
   ahora responden. Farmacias requieren precio general, convenio y sucursal
   explícitos, conservando promociones de varias unidades por separado.
5. Para bloqueos persistentes, pedir una fuente acordada (feed de afiliados,
   exportación o API). No prometer cobertura completa mientras falte esa fuente.

La migración queda preparada para revisión y no se desplegaron servicios ni se
publicaron mensajes. La prueba SQL necesita PostgreSQL descartable; no se usó
la base operativa para ejecutar tests.

## Validación final

`python -m pytest -q -p no:cacheprovider`: **682 passed, 116 skipped**.
Los 116 omitidos requieren una base de pruebas configurada. Las 17 pruebas
nuevas sí pasaron. No se comprobó la migración contra PostgreSQL.
