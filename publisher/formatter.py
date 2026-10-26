"""El mensaje que ve el suscriptor. Puro: entra un Candidate, sale texto.

Las decisiones de producto que están adentro, porque el formato ES el producto:

1. **El precio tachado es el `p50` de 60 días, no el `price_normal` de la
   tienda.** El proyecto existe para desmentir ese número; mostrarlo aunque sea
   como referencia sería repetirlo. Por eso la etiqueta dice "antes real": es la
   promesa del canal escrita en cada mensaje.
2. **Un pie fijo que explica de dónde sale ese número.** Se paga una línea por
   mensaje a cambio de que el diferencial no dependa de que alguien haya leído
   la descripción del canal. Es lo único que separa a Ofertoon de una cuenta que
   reenvía el banner de la tienda.
3. **Sin foto propia, con preview de link.** `sendPhoto` contra una URL remota
   falla en silencio cuando la tienda cambia el CDN y te deja sin mensaje;
   dejando que Telegram arme la card se consigue la misma imagen sin ese modo de
   falla. El precio del preview es que la imagen la elige Telegram.
4. **`price_card` no aparece.** El canal promete el precio que paga cualquiera,
   sin tarjeta de la casa. Mezclarlos es la mentira de la que vive el retail.
5. **URL sin tag de afiliado.** No hay programa dado de alta; cuando lo haya, el
   único punto a tocar es `deal_url()`.
6. **El precio por unidad de medida sale solo en supermercado.** Es el dato que
   convierte un "−30%" de $670 de ahorro en una decisión de stockear
   (PLAN_SUPERMERCADO §2), y es exactamente lo que no significa nada en el resto
   del canal: el precio por kilo de un notebook no le dice nada a nadie.
"""
from __future__ import annotations

import html
from decimal import ROUND_HALF_UP, Decimal

from curation.ranker import Candidate

#: Telegram corta los captions en 1024 y los mensajes en 4096. Ni cerca, pero el
#: nombre crudo de un listing de Falabella puede traer 200 caracteres de specs.
MAX_NAME_CHARS = 90

#: Categorías cuyo copy lleva precio por unidad de medida. Es una lista blanca y
#: no un "si el dato existe, mostralo": el `pum` llega en el 95% del supermercado
#: y también en alguna llave de otras tiendas, pero "el precio por metro" de un
#: cable o "por unidad" de un pack de pilas no es el argumento de compra que
#: sostiene al supermercado — ahí sí lo es, porque lo que vuelve real un ahorro de
#: $670 es llevarse varias unidades de algo que se puede guardar.
PUM_CATEGORIES = frozenset({"supermercado"})


def format_clp(value: Decimal) -> str:
    """`Decimal('399990.00')` → `'$399.990'`. Punto de miles, sin decimales.

    Los precios chilenos son enteros; mostrar centavos delata que el número salió
    de una columna NUMERIC y no de una vidriera.

    Redondeo HALF_UP y no el `round()` de Python, que es bancario: `round(0.5)`
    da 0 y para plata eso se lee como un error de un peso.
    """
    entero = value.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return "$" + f"{int(entero):,}".replace(",", ".")


def format_discount(discount_real: Decimal) -> str:
    """`Decimal('0.3846')` → `'−38%'`. Con menos U+2212, no guion."""
    puntos = (discount_real * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return f"−{int(puntos)}%"


def truncate(text: str, limit: int = MAX_NAME_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def evidence_line(candidate: Candidate) -> str:
    """La razón por la que esto es noticia, en una línea.

    `min_prior` excluye la observación actual (ver `curation.ranker.Candidate`),
    así que "el más barato en 60 días" es una afirmación con contenido y no una
    tautología. Cuando no lo es, el fallback sigue siendo verdadero: el detector
    rechaza todo lo que esté por encima del p10, así que un aceptado siempre está
    en el decil más barato de su propia historia.
    """
    if candidate.min_prior is not None and candidate.price <= candidate.min_prior:
        return "🏆 El más barato en 60 días"
    return "📉 Por debajo de su piso habitual de 60 días"


def pum_habitual(candidate: Candidate) -> Decimal | None:
    """El precio por unidad de medida que tenía este producto habitualmente.

    Se **deriva** del p50, no se guarda: `pum = price / tamaño`, así que
    `pum / price` es `1 / tamaño` y entonces

        pum_habitual = p50 × (pum_hoy / price_hoy)

    es exactamente el p50 llevado a la misma base que la tienda eligió. Es exacto
    mientras el envase del SKU no cambie de tamaño, que es lo normal: un formato
    nuevo es un SKU nuevo.

    No se calcula una baseline de `pum` a propósito, por dos razones. La primera
    es la regla de no-look-ahead: una segunda serie con su propio p50 sería una
    segunda implementación de la baseline, y dos implementaciones divergen. La
    segunda es la frontera del dato: el `pum` es copy, no señal, y meterlo en el
    job de baselines lo pone del lado de la señal.

    `None` cuando no hay con qué: sin `pum`, o con un `price` en cero que haría
    estallar la división.
    """
    if candidate.pum_price is None or candidate.price <= 0:
        return None
    derivado = candidate.p50 * candidate.pum_price / candidate.price
    return derivado.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def pum_line(candidate: Candidate) -> str | None:
    """"$3.242 por KG · antes real $4.600", y `None` si no corresponde.

    Tres razones para no emitirla, y ninguna frena la publicación — el `pum` es
    opcional de verdad (el 5% del supermercado no lo trae, y el mensaje de ese 5%
    sale igual, sin la línea):

    * la categoría no es de supermercado;
    * la tienda no declaró el `pum` de esta observación;
    * el "antes" derivado no es mayor que el de hoy, o sea no hay contraste que
      mostrar. Pasa con los `pum` de pocos pesos (una base `100UN` a $8), donde el
      redondeo a CLP entero deja los dos números iguales y la línea diría "$8 ·
      antes real $8". En ese caso sale el precio por unidad solo, que ya es el
      dato que el comprador compara en la góndola.

    **La etiqueta va tal como la manda la tienda** (`KG`, `LT`, `10GR`, `100UN`).
    No se traduce a palabras: traducir `KG` a "kilo" obliga a decidir qué es `MR`
    o `MT` —las dos aparecen en el catálogo— y una traducción equivocada miente
    sobre la unidad, que es justo la mitad del dato que no se puede perder.
    """
    if candidate.category_slug not in PUM_CATEGORIES:
        return None
    if candidate.pum_price is None or not candidate.pum_label:
        return None

    unidad = html.escape(candidate.pum_label)
    linea = f"📦 {format_clp(candidate.pum_price)} por {unidad}"
    habitual = pum_habitual(candidate)
    if habitual is not None and habitual > candidate.pum_price:
        linea += f"  ·  antes real {format_clp(habitual)}"
    return linea


def deal_url(candidate: Candidate) -> str:
    """La URL a publicar. Único punto a tocar el día que haya afiliados."""
    return candidate.url


def format_deal(candidate: Candidate) -> str:
    """El mensaje completo, listo para `parse_mode='HTML'`."""
    category = candidate.category_name or "Ofertas"
    parts = [
        f"🔥 <b>{format_discount(candidate.discount_real)}</b> · {html.escape(category)}",
        "",
        f"<b>{html.escape(truncate(candidate.name))}</b>",
        html.escape(candidate.store_name),
        "",
        f"<b>{format_clp(candidate.price)}</b>  ·  "
        f"antes real <s>{format_clp(candidate.p50)}</s>",
    ]
    unitario = pum_line(candidate)
    if unitario is not None:
        parts.append(unitario)
    parts += [
        evidence_line(candidate),
        "",
        f'<a href="{html.escape(deal_url(candidate), quote=True)}">Ver oferta →</a>',
        "",
        "<i>«antes real» = precio mediano de este producto en los últimos "
        "60 días, medido por nosotros. No es el precio tachado que declara "
        "la tienda.</i>",
    ]
    return "\n".join(parts)
