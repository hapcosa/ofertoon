# PC Express: catálogo público comprobado el 2026-11-06

**Estado actualizado el 2026-11-06:** adaptador `pc_express` conectado y primera
ingesta en producción verificada: **458 `price_points`**, ocho llaves `ok`.
`publish_enabled = false` mantiene la acumulación sin enviar candidatos al
detector ni al curador hasta verificar el control negativo de stock.

El 403 de
`pcexpress.cl` corresponde al host equivocado. El catálogo funciona en
https://tienda.pc-express.cl/ y se consultó con `DEFAULT_USER_AGENT`, sin
credenciales ni evasión. Las cifras son una fotografía de esta fecha, no
ofertas validadas contra la baseline propia del sistema.

| Pregunta de PLAN_EXPANSION §1 | Evidencia y decisión |
|---|---|
| 1. Plataforma | Rutas `index.php?route=product/category&path=…`, `product_id` y cookie `OCSESSID`: OpenCart con plantilla propia. El HTML del listado contiene los productos. |
| 2. Robots | `robots.txt` respondió 200. No declara `Crawl-delay`; prohíbe filtros, orden y `?page=` vacío, no las páginas numeradas de categorías usadas aquí. Tasa propuesta: 0,4 solicitudes/s. |
| 3. User-Agent | `DEFAULT_USER_AGENT` respondió 200 en las 27 páginas de catálogo, la portada y 16 fichas vigentes. No hizo falta otro juego de headers. |
| 4. Paginación | `&page=N`, 20 productos por página. Texto «Mostrando del X al Y de T (P páginas)» indica total y final; no es necesario solicitar una página fuera de rango. |
| 5. Estabilidad | Procesadores: dos recorridos completos, 163 SKU únicos ambos, mismos identificadores. Tarjetas de video: dos lecturas de sus dos páginas, 26 SKU iguales (medición previa). |
| 6. Total | En el pie de cada página. Las ocho llaves suman **458 filas / 458 SKU únicos / 458 declarados**. |
| 7. GTIN | **0/458** fichas de listado muestran EAN/GTIN. Las fichas muestreadas traen MPN, pero el `sku` del JSON-LD es `--`; no se debe inventar GTIN a partir del MPN. |
| 8. Precio normal | **102/458** tienen precio tachado en el listado. Ese valor es solo evidencia: la oferta real depende del p50 propio de 60 días. |
| 9. Stock | **458/458** listados muestran botón «Agregar al carro»; eso no es prueba de stock. **16/16** fichas vigentes muestreadas tenían stock web positivo y JSON-LD `InStock`. No apareció un agotado vigente para control negativo. La ficha expone «Stock web» por separado de «Stock casa matriz»; falta demostrar la semántica del agotado antes de afirmar que el listado da señal fiable. |
| 10. Centinelas | Máximo visto en estas 458 entradas: **$10.577.500**, bajo `MAX_PLAUSIBLE_CLP`. No se observó centinela en la muestra, sin garantía futura. |
| 11. Llaves | Son nodos del menú de categorías, no la vitrina «Ofertas». Las ocho llaves no comparten SKU en esta medición. |
| 12. Costo | **27 páginas**, unas **5 MB** estimadas desde páginas 1 (~149–196 KB); **458 listings/pasada**. A 0,4 solicitudes/s, ~68 s de espera/pasada más red. Abrir cada ficha para verificar stock cambiaría mucho el costo; requiere decisión separada. |

| Categoría de navegación | `path` | Páginas | SKU únicos/total |
|---|---|---:|---:|
| Tarjetas de Video | `460_475` | 2 | 26/26 |
| Procesadores | `460_473` | 9 | 163/163 |
| Unidades SSD NVME PCIex | `62_331_408` | 1 | 20/20 |
| Fuentes de Poder | `460_461` | 4 | 78/78 |
| Placas Madres | `460_472` | 3 | 49/49 |
| Memorias para PC | `72_126` | 3 | 57/57 |
| Notebooks Comercial y Corporativos | `476_136` | 4 | 63/63 |
| Notebooks Gamer | `476_479` | 1 | 2/2 |

**Interpretación de precios:** los 458 listados rotulan el precio principal
«Transferencia». Es el precio de contado/transferencia disponible para cualquiera
y corresponde a `price_effective`. La ficha muestra además «Otros medios», un
recargo por forma de pago, no `price_card` (reservado a tarjeta de tienda).
Ejemplo comprobado: [puente EVGA NVLink](https://tienda.pc-express.cl/8680-bridge-evga-nvidia-nvlink-3-slot-p-n-100-2w-0029-lr)
con $9.900 transferencia, $10.532 otros medios y $53.191 tachado. Esta entrada
de la categoría «Tarjetas de Video» es un accesorio, así que no se debe asignar
una categoría interna de GPU por el nombre de la navegación.

[CSV de los 458 precios observados](pc_express_precios.csv): fecha, categoría,
SKU, precio de transferencia, precio normal declarado y URL pública de la
ficha. Es una muestra de precios publicados; ninguna fila afirma todavía un
descuento real ni stock verificado.

**Siguiente condición para publicar:** conseguir una ficha agotada vigente y
verificar cómo se comportan su botón, su stock web y `offers.availability`, además
de esperar los 30 días observados exigidos por el detector. Los puntos de precio
de hoy no prueban por sí solos una oferta real.
