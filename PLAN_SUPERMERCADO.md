# PLAN_SUPERMERCADO.md

Plan para las ofertas de supermercado. Escrito el **2026-10-19**, con todo lo
medido ese día contra producción.

Vive aparte de [`PLAN_TIENDAS.md`](PLAN_TIENDAS.md) porque no es una fase más de
conexión de tiendas: el supermercado rompe dos supuestos del sistema —el rango de
ticket y la unidad de compra— y eso cambia el copy y el destino, no solo el
adaptador.

**Actualizado el 2026-10-19 con tres decisiones del dueño del producto** (§2 y §6),
que simplificaron el plan: el supermercado va como tema del canal, Belleza va
aparte, y el ahorro unitario bajo vale porque se compran varias unidades de algo
almacenable. Con eso, la fase bloqueante dejó de ser "cambiar el score" y pasó a
ser "cablear el tema y guardar el precio por unidad de medida".

---

## 1. La tesis: el supermercado no entra con la vara actual, y el problema está medido

`detector.compute_score` es `discount_real*100 + below_floor*50`, y su docstring
dice por qué excluye el precio absoluto:

> No entra el precio absoluto: un 40% en un notebook y un 40% en un taladro valen
> lo mismo para el suscriptor de su canal, y ponderar por ticket inundaría los
> canales de electrónica cara.

**Ese razonamiento es correcto dentro de un rango de ticket comparable**, y
notebook contra taladro lo es. El supermercado no: medido el 2026-10-19 sobre los
candidatos aceptados reales, el ahorro p50 por categoría va de $12.000 a $220.000,
y el catálogo de supermercado que ya está conectado tiene ticket p50 **$2.690**.

    categoría               ahorro p50 de sus aceptados
    tecno-tv                    $220.000
    tecno-notebooks             $170.000
    tecno-celulares             $110.000
    hogar-electro                $80.000
    ferre-herramientas           $40.000
    tecno-componentes            $12.000
    supermercado (proyectado)       ~$670     ← θ 0.25 sobre $2.690

Con el score actual, un 25% de supermercado puntúa **igual** que un 25% de un
televisor. Y no es teórico: el 2026-10-19, con `deporte-equipamiento` y
`tecno-audio` recién habilitados, el canal ya mostró la inversión:

    score 45,0   −30%   ahorro $9.000    Banano Jester Lumbar
    score 38,6   −26%   ahorro $1.800    Estuche para AirPods
    score 37,5   −25%   ahorro $20.000   Taladro atornillador

El estuche de $1.800 de ahorro le gana el lugar a un taladro que ahorra once veces
más. Con supermercado adentro y ahorros de $670, el efecto se multiplica.

**Esa era la conclusión hasta la decisión de la §2**, y ahí cambia: el problema
real no es el ahorro unitario bajo sino que compita de igual a igual con un
televisor en la misma cuota. Resuelto eso con un destino separado, el piso en CLP
deja de ser bloqueante. Lo que sigue en pie de esta sección es el diagnóstico: **el
score no distingue $1.800 de $20.000**, y eso sigue siendo cierto dentro del canal
general — el estuche de AirPods le está ganando el lugar a un taladro hoy.

---

## 2. La unidad de compra: resuelto, y cambia el diseño

**Decidido el 2026-10-19 por el dueño del producto**, y la respuesta corrige el
encuadre de la §1:

> «Sí vale el ahorro de $670. Generalmente son cosas que vale la pena porque se
> compran varias unidades, y son cosas consumibles que puedes guardar harto
> tiempo.»

O sea el ahorro relevante de una oferta de supermercado **no es el unitario**, es
`ahorro_unitario × unidades que uno carga`, y lo que lo vuelve real es que el
producto sea **almacenable**. Un detergente a −30% con $670 de ahorro por unidad
son $4.000 si llevás seis, y se pueden llevar seis porque no se vencen la semana
que viene.

Tres consecuencias de diseño, en orden de importancia:

1. **El piso de ahorro en CLP deja de ser el prerrequisito** (ver §5, Fase 1). Un
   piso duro sobre el ahorro unitario haría justo lo contrario de lo que se quiere:
   rechazaría los $670 que en la práctica valen $4.000. Y como el supermercado va a
   su propio tema (decisión 1 de abajo), tampoco compite con el televisor, que era
   el otro motivo para el piso.
2. **El copy tiene que mostrar el precio por unidad de medida.** Es lo que convierte
   "−30%" en una decisión de stockear: *"el kilo a $3.242 contra $4.600 habitual"*.
   Y el dato **ya está disponible y lo estamos tirando** — ver §2bis.
3. **Refuerza la exclusión de perecederos**, ahora por una segunda razón
   independiente de la estacionalidad: lo que no se puede guardar no se compra en
   cantidad, así que no participa del mecanismo que hace valer la oferta.

### Decisiones tomadas el 2026-10-19

| pregunta | decisión |
|---|---|
| ¿Categoría del canal o formato propio? | **Tema del canal** — va al tema S.Mercado, no se construye un resumen de canasta |
| ¿Belleza con supermercado? | **Aparte**, categoría propia con su propio θ |
| ¿Vale el ahorro de $670? | **Sí**, por unidades y almacenabilidad (arriba) |
| ¿Alcohol? | sigue pendiente |

## 2bis. El precio por unidad de medida está en el payload y se descarta

Medido el 2026-10-19 sobre tres llaves de Tottus (144 productos):

    Despensa          48/48  con pum (100%)
    Mascotas          48/48  (100%)
    Aseo-y-Limpieza   42/48  (87%)
    ──────────────────────────────────
    TOTAL            138/144 (95%)

    unidades: KG 72 · 10GR 32 · UN 17 · LT 11 · MT 4 · 100UN 1 · MR 1

Viene dentro de `prices[].pum` en el mismo `__NEXT_DATA__` que ya parseamos:

    "prices": [{"type": "internetPrice", "price": ["3.890"],
                "pum": {"label": "KG", "price": ["3.242"]}}]

**Y no se guarda en ninguna parte**: `falabella_family.parse_listing` no lo mira,
`RawProduct` no tiene campo, y `price_points` no tiene columna. `raw_payload` existe
en el dataclass pero tampoco se persiste.

Para el resto del catálogo eso es correcto —el precio por kilo de un notebook no
significa nada— pero para supermercado es **el** dato que hace comparable una
oferta, y el que sostiene el argumento de las varias unidades. Es trabajo chico: un
campo opcional en `RawProduct`, una columna en `price_points` y una línea en el
parser.

⚠️ Ojo con la unidad: `10GR` y `100UN` no son errores, son la base que la tienda
elige para que el número sea legible. Compararlo entre productos exige normalizar a
una unidad común (KG, LT, UN) o no compararlo.

---

## 3. Estado actual: Tottus conectada, sin publicar todavía

| | |
|---|---|
| Tienda | Tottus (migración 27, conectada el 2026-10-01) |
| Llaves | 5, todas no perecederas: Despensa, Desayuno-y-Dulces, Aseo-y-Limpieza, Congelados, Mascotas |
| Listings | 5.772 |
| Ticket p50 | $2.690 |
| Historia | 13 días máximos al 2026-10-19 |
| θ | 0.250, sin calibrar |
| Candidatos | **0** — ni con `min_history_days = 10` (migración 32) |
| Madura | ~5 de noviembre; se evalúa con `scripts.aceptacion_tienda` |

Que dé 0 candidatos con el umbral relajado es informativo: su catálogo no tiene
todavía diez días con diez observaciones por listing. No es un problema, es el
reloj.

### Lo que Tottus tiene y no está conectado

De sus 19 paraguas de nivel 1, entraron 5. Quedan fuera, por razones distintas:

| llave | SKUs | por qué quedó afuera |
|---|---|---|
| `Vinos-y-licores` | 2.008 | **alcohol: decisión de producto sin tomar** |
| `Cervezas` | 209 | idem |
| `Belleza` | 1.106 | no es supermercado estricto; cabría en una categoría propia |
| `Panaderia-y-Pasteleria` | 498 | perecedero de rotación diaria |
| `Frutas-y-Verduras` | 167 | **precio estacional**: el p50 de 60 días de un tomate es el promedio de dos temporadas |
| `Carnes` | 240 | idem, y además peso variable |
| `Bebidas-Aguas-y-Jugos` | 88 | chica; entra cuando se quiera |

La exclusión de perecederos es la regla que CLAUDE.md ya documenta y **no se
revisa**: el detector marcaría "oferta real" cada vez que baja la estacionalidad.

---

## 4. Las cadenas: la auditoría de PLAN_TIENDAS estaba equivocada en dos

PLAN_TIENDAS §2.6 dio por bloqueadas las seis grandes. Reauditado el 2026-10-19 con
el método que funcionó en Tottus —headers completos, **identificar la plataforma
real y no inventar rutas**—, dos se abren:

| cadena | estado 1-oct | estado 19-oct | veredicto |
|---|---|---|---|
| **Tottus** | L (403/503) | conectada | ✅ en producción |
| **Jumbo** | L, "sin API pública" | **HTTP 200, listado en el HTML** | 🟢 **VIABLE** |
| **Santa Isabel** | L, "idéntico a Jumbo" | **HTTP 200, listado en el HTML** | 🟢 **VIABLE** |
| **Lider** | tajada chica | sin cambios | 🟡 costo por SKU |
| **Unimarc** | 403 hasta en robots | **403, sin cambios** | ❌ |
| **aCuenta** | certificado inválido | **`CERTIFICATE_VERIFY_FAILED`** | ❌ |

### Jumbo y Santa Isabel: lo medido

Las dos son el mismo stack (Cencosud, VTEX + Next) así que **un adaptador cubre las
dos**. Su API VTEX sí devuelve 404 —eso del plan era correcto— pero **no hace
falta**: el listado viene renderizado en un JSON-LD `ItemList` dentro del HTML.

Lo bueno, medido sobre `jumbo.cl/lacteos-y-quesos/leches`:

- **40 productos por categoría, 100% con precio** (`offers.price: 10990`).
- **`availability: schema.org/InStock`** — sería la **primera tienda de supermercado
  con stock real en el listado**; Tottus, Falabella y Paris son ciegas ahí.
- `brand` normalizable, `name`, `url`, `image`.
- **El total de la categoría viene declarado** ("309 productos" en el HTML), o sea
  alcanza para el canario exacto.
- `robots.txt` responde 200 y ofrece su sitemap: **816 URLs, 45 raíces y 771
  hojas**.

Lo malo, y define la estrategia:

- **No paginan.** Probadas ocho variantes (`?page=`, `?PageNumber=`, `?from/to=`,
  `?_from/_to=`, `?PS=&From=`, `?O=OrderBy…`, `?sort=`, `?order=`): las ocho
  devuelven los **mismos 40 primeros**. Es el caso del SSR de Paris.
- **No traen GTIN.** Las claves del item son `@type, brand, image, name, offers,
  url` y nada más. Así que no resuelven el cross-store, que hoy da cero.

**Estrategia obligada: hojas de ≤40 productos.** Es el mismo principio que el repo
ya aplica a VTEX ("las llaves son las subcategorías, nunca la raíz"). Muestreadas 14
hojas al azar de las 771:

    entran completas en 40:  6 de 14  (42%)
    productos declarados:    2.205 en la muestra, promedio 157 por hoja

O sea **hay que elegir las hojas a mano**, llave por llave, verificando que cada una
declare ≤40. Las que no entren quedan con cobertura parcial y sin canario exacto,
igual que Zapatillas y Audífonos en Falabella.

⚠️ **Lo que NO se midió de Jumbo/Santa Isabel**, y hace falta antes de conectar:
la estabilidad del orden entre días (la lección de Tottus: un orden inestable deja
SKUs sin ver nunca y nada madura), el `rate_limit_rps` que su `robots.txt` admite,
y si `availability` es confiable o es otra trampa como el `availability` del
listado de Tottus, que habla de modos de envío.

---

## 5. Fases propuestas

El orden importa: **la fase 1 es bloqueante** y las demás no valen nada sin ella.

### Fase 1 — Cablear el tema S.Mercado y guardar el `pum`

La decisión del 2026-10-19 (supermercado = tema del canal) resuelve el problema de
la §1 **sin tocar el score**: en su propio tema no compite con el televisor, así
que el piso en CLP deja de ser bloqueante. Quedan dos trabajos chicos:

1. **Cablear el tema.** `telegram_topics` ya tiene S.Mercado con cuota 2 desde la
   migración 26; le falta el `message_thread_id`, que sale del link de un mensaje
   del tema. Es el único paso que necesita acción humana.
2. **Guardar el precio por unidad de medida** (§2bis): campo opcional en
   `RawProduct`, columna en `price_points`, una línea en el parser de
   `falabella_family`. Sin esto el copy no puede sostener el argumento de las varias
   unidades, que es lo que hace valer la oferta.

**Lo que NO se hace**: tocar `compute_score`. Su docstring tiene razón para el
rango de ticket del canal general, y el problema que quedaba —el estuche de $1.800
ganándole al taladro de $20.000— es un asunto del canal general, no del
supermercado. Si se quiere arreglar, es una decisión aparte con su propia
medición.

### Fase 2 — Calibrar θ de supermercado contra datos propios

θ 0.250 es un valor de partida sin medición: salió de que el descuento declarado
por Tottus tiene p50 ~20% y solo el 0-9% de su catálogo declara 30%. Cuando
`supermercado` madure (~5-nov) y tenga 30 días de futuro para etiquetar (~5-dic),
sale del backtest como el resto.

Hasta entonces, **no tocar θ**: el canal publicará con un valor sin calibrar, que
es la situación aceptada el 2026-10-19 mientras no haya usuarios.

### Fase 3 — Completar Tottus

Las llaves que quedaron afuera por decisión y no por técnica: alcohol (2.217 SKUs),
Belleza (1.106), Bebidas (88). Costo ya conocido: ~30 páginas por pasada cada 1.400
SKUs, con el adaptador que ya existe. Cero código.

### Fase 4 — Jumbo + Santa Isabel, con un adaptador compartido

Un `cencosud_family.py` que lea el `ItemList` del JSON-LD. Prerrequisitos de la
§4: medir estabilidad de orden, `rate_limit_rps` y la confiabilidad de
`availability`. Después, elegir las hojas de ≤40 a mano desde su sitemap.

Es la fase que de verdad hace al supermercado un producto: **tres cadenas** sobre
la misma canasta permite por primera vez decir "más barato que en Jumbo"… salvo que
ninguna trae GTIN, así que el match tendría que ser por (marca, nombre), que la
regla 6 del CLAUDE.md mantiene deliberadamente afuera. **Eso hay que resolverlo
antes de prometer comparación entre cadenas.**

### Fase 5 — Lider, solo si hace falta

Sigue siendo costo por SKU (752 KB por ficha, 102.880 SKUs). Su valor único es el
**100% de EAN en la URL**, que resolvería el cross-store de un golpe. Entra solo
como tajada elegida a mano y con el presupuesto de red medido: ~3.500 SKUs por
pasada es el techo de este host.

---

## 6. Decisiones

Tomadas el 2026-10-19 (ver §2):

1. ✅ **Supermercado es un tema del canal**, no un formato propio. No se construye
   resumen de canasta; va al tema S.Mercado.
2. ✅ **Belleza va aparte**, como categoría propia con su propio θ — no entra en
   `supermercado`. Son 1.106 SKUs de Tottus y habilita después Preunic, Salcobrand y
   Maicao, que PLAN_TIENDAS §2.6 ya tenía listadas sin auditar.
3. ✅ **El ahorro de $670 vale**, porque se compran varias unidades de algo que se
   puede guardar. De ahí salen las tres consecuencias de diseño de la §2.

Pendiente:

4. **¿El canal publica alcohol?** 2.217 SKUs de Tottus esperando (Vinos-y-licores
   2.008 + Cervezas 209), no perecederos y con ticket $2.490-$6.390. Es la única
   decisión que queda para completar Tottus.

## 7. Lo que NO se va a hacer, y por qué

- **Perecederos** (frutas, verduras, carnes, panadería): el p50 de 60 días de un
  producto estacional no es una baseline. Es la misma regla que excluye los días
  degradados del backtest.
- **Unimarc y aCuenta**: 403 en todo y certificado inválido respectivamente,
  reconfirmado el 2026-10-19. Sin vía limpia y sin construir evasión.
- **Bajar `MIN_DAYS` para apurar supermercado**: ya está hecho vía
  `min_history_days = 10` y es temporal, con reversión el 2026-11-06 (migración 32).
  No se extiende.
- **Prometer comparación entre cadenas antes de resolver la identidad sin GTIN**:
  ninguna de las tres cadenas viables expone GTIN en el listado.
