import asyncio
from scrapers.base import CategoryRef
from scrapers.http import HttpClient
from scrapers.stores.salesforce_family import ABCAdapter, TricotAdapter


async def main():
    abc_categories = [CategoryRef("ropa-vestuario", "mujer/ropa-mujer")]
    tri_categories = [
        CategoryRef("ropa-accesorios", "accesorios/mujer/bananos"),
        CategoryRef("ropa-vestuario", "hombre/pijamas"),
        CategoryRef("ropa-vestuario", "mujer/poleras"),
        CategoryRef("ropa-calzado", "calzado/mujer/zapatillas"),
        CategoryRef("ropa-vestuario", "mujer/jeans"),
        CategoryRef("ropa-vestuario", "hombre/jeans"),
        CategoryRef("ropa-vestuario", "infantil/ninas/poleras"),
        CategoryRef("ropa-vestuario", "mujer/ropa-interior/calzones"),
        CategoryRef("ropa-vestuario", "hombre/camisas"),
    ]
    async with HttpClient(max_retries=1) as http:
        for adapter in (ABCAdapter(http, abc_categories), TricotAdapter(http, tri_categories)):
            total = 0
            for category in adapter.categories():
                products = [p async for p in adapter.discover(category)]
                total += len(products)
                print(adapter.slug, category.store_key, "emitted", len(products),
                      "completeness", adapter.completeness(category), flush=True)
            print(adapter.slug, "total_emitted", total, flush=True)


asyncio.run(main())
