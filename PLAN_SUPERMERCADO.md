# PLAN_SUPERMERCADO.md

Plan para las ofertas de supermercado. Escrito el **2026-10-19**, con todo lo
medido ese día contra producción.

Vive aparte de [`PLAN_TIENDAS.md`](PLAN_TIENDAS.md) porque no es una fase más de
conexión de tiendas: el supermercado rompe dos supuestos del sistema —el rango de
ticket y la unidad de compra— y eso cambia el detector, el ranker y el copy, no
solo el adaptador.

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

**Conclusión: el piso de ahorro en CLP no es una mejora deseable, es el
prerrequisito.** Ya estaba anotado como tal en PLAN_TIENDAS §2.6; acá queda con
números.

---

## 2. Y hay un segundo supuesto que se rompe: la unidad de compra

Esto no está en ninguna medición y es una afirmación de producto, así que va
marcada como tal: **en supermercado nadie compra por oportunidad individual.**

Nadie va a Tottus porque un paquete de fideos está a −30%. La compra de
supermercado es por **canasta y recurrencia**: lo que ahorra plata de verdad es
saber que esta semana conviene cargar detergente y café, no que un SKU puntual
bajó. El canal, tal como está construido, publica ofertas unitarias — y eso le
sirve a un taladro, no a un paquete de arroz.

Esto tiene una consecuencia de diseño que conviene decidir ANTES de conectar más
cadenas, porque cambia qué hay que construir:

- **Si el supermercado es "una categoría más"**, hay que resolver el piso en CLP y
  nada más. El canal publicará ofertas unitarias de súper, que es lo que hoy sabe
  hacer, con el riesgo de que sean irrelevantes para el suscriptor.
- **Si el supermercado es su propio formato**, lo que hay que construir es otra
  cosa: un resumen periódico ("los 10 productos de la canasta que están en su
  precio más bajo en 60 días") en vez de un mensaje por oferta. Eso es trabajo de
  `publisher/` nuevo, no un ajuste del ranker.

El grupo con temas ya tiene **S.Mercado** creado para esto, así que la
infraestructura para separarlo existe. La decisión no es mía.

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

### Fase 1 — El piso de ahorro en CLP (bloqueante)

Sin esto, conectar más supermercado empeora el canal en vez de mejorarlo. Tres
caminos, de menor a mayor alcance:

1. **Piso duro por categoría.** Una columna `categories.min_ahorro_clp` y un
   rechazo nuevo del detector. Barato, explícito, y deja el score intacto. El costo
   es que un piso fijo es arbitrario: ¿$500? ¿$2.000?
2. **Ponderar el score por ahorro absoluto, con tope.** Cambia
   `compute_score`, que es el corazón de la curación, y contradice su docstring: hay
   que reescribirlo con el nuevo razonamiento, no a escondidas. Riesgo real de
   "inundar de electrónica cara", que es exactamente lo que ese docstring evita.
3. **Separar el destino.** Supermercado a su propio tema/canal con cuota propia, y
   entonces no compite con el televisor y el piso en CLP deja de ser urgente. El
   tema **S.Mercado ya existe** (migración 26) y solo le falta el
   `message_thread_id`.

**La 3 es la más barata y la que menos toca el núcleo**, y además es la que el
grupo con temas ya anticipó. La 1 sigue haciendo falta dentro del tema de
supermercado para no publicar ahorros de $200.

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

## 6. Decisiones que no son mías

1. **¿Supermercado es una categoría del canal o su propio formato?** (§2). Define
   si la Fase 1 es "piso en CLP" o "construir un resumen de canasta".
2. **¿El canal publica alcohol?** 2.217 SKUs de Tottus esperando, no perecederos y
   con ticket razonable ($2.490-$6.390).
3. **¿Belleza y cuidado personal entran como supermercado o como categoría propia?**
   El plan original decía que "un canal que mezcla shampoo y detergente es otro
   producto".
4. **¿Vale el ahorro de $670?** Es la pregunta de fondo. El backtest no la
   responde: un 25% es igual de real a cualquier precio, y lo que está en juego es
   si al suscriptor le mueve la aguja.

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
