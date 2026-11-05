"""Exporta precios actuales sin DB ni publicación en Telegram.

python -m scripts.precios_tienda --store ripley --out /tmp/ripley.csv
"""
import argparse
import asyncio
import csv
from pathlib import Path

from scrapers.base import CategoryRef
from scrapers.http import HttpClient
from scrapers.stores.hites import HitesAdapter
from scrapers.stores.ripley import RipleyAdapter

STORES = {
    'ripley': (RipleyAdapter, 'tecno/computacion/notebooks'),
    'hites': (HitesAdapter, 'tecnologia/computacion/notebook'),
}


async def run(args):
    cls, key = STORES[args.store]
    category = CategoryRef('tecno-notebooks', key)
    async with HttpClient() as http:
        adapter = cls(http, [category])
        products = [p async for p in adapter.discover(category)]
    path = Path(args.out)
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['tienda', 'sku', 'producto', 'precio_CLP', 'tarjeta_CLP',
                         'normal_declarado_CLP', 'stock', 'fecha_UTC', 'url'])
        for p in products:
            writer.writerow([p.store_slug, p.store_sku, p.name, p.price_effective,
                             p.price_card, p.price_normal, p.in_stock,
                             p.scraped_at.isoformat(), p.url])
    count = adapter.completeness(category)
    print(f'{len(products)} precios de venta directa exportados a {path}. Catálogo: {count}.')
    print('Son precios actuales; una oferta real requiere historial en el detector.')
    if count is None or count[0] < count[1]:
        raise SystemExit('Catálogo incompleto: el CSV contiene solo los precios recuperados.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', choices=STORES, required=True)
    parser.add_argument('--out', required=True)
    asyncio.run(run(parser.parse_args()))
