"""Rockford Chile en su tienda oficial vigente, rkflife.com.

`rockford.cl` falla TLS por cadena de certificados, pero el catálogo oficial
`rkflife.com` sirve Shopify con TLS válido y `products.json` público. Cuatro
colecciones de vestuario/calzado aportaron 2.933 productos únicos el 6-nov-2026.
Las variantes son talles: 16.962 variantes en 2.934 filas, sin un solo producto
con precios distintos entre talles. Se emite una serie por producto.

Una sola coincidencia entre las cuatro llaves cae entre las dos de vestuario,
ambas mapeadas a `ropa-vestuario`: deduplicar por pasada es seguro para esas
llaves medidas. Re-medir antes de agregar otra llave.
"""
from scrapers.stores.shopify_family import _ShopifyFamilyAdapter


class RockfordAdapter(_ShopifyFamilyAdapter):
    slug = "rockford"
    base_url = "https://www.rkflife.com"
    rate_limit_rps = 0.5
    emitir_por_producto = True
    dedupe_across_categories = True
    # Son identificadores internos de las fuentes, no marcas utilizables:
    # `rockfordcl` aparece incluso en un polar Columbia agotado del fixture.
    non_brand_vendors = frozenset({"rockfordcl", "merrellcl", "bsoulcl"})
