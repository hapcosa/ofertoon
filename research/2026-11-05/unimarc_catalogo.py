"""Investigación reproducible: precios públicos de Unimarc, sin DB ni Telegram.

Ejecutar desde la raíz del repositorio:
.venv/bin/python research/2026-11-05/unimarc_catalogo.py --out /tmp/unimarc-auditoria

Club Unimarc se incluye por decisión del dueño del 5-nov-2026. Las condiciones
se conservan: este archivo NO incorpora precios al detector ni afirma que
promociones de varias unidades sean precios unitarios sin condiciones.
"""
import argparse
import asyncio
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from selectolax.parser import HTMLParser
from scrapers.http import BROWSER_HEADERS, HttpClient

BASE = 'https://www.unimarc.cl'
CATEGORY = 'lacteos-huevos-y-refrigerados'


def extract(html):
    node = HTMLParser(html).css_first('#__NEXT_DATA__')
    if node is None:
        raise ValueError('No hay datos Next.js: no es un catálogo válido')
    props = json.loads(node.text())['props']['pageProps']
    for query in props['dehydratedState']['queries']:
        key = query.get('queryKey')
        if isinstance(key, list) and key[0] == 'productsSearch-client':
            data = query['state']['data']
            return props['page'], int(data['resource']), data['availableProducts'] + data['notAvailableProducts']
    raise ValueError('Falta productsSearch-client')


def row(product):
    offer = (product.get('sellers') or [{}])[0]
    detail = product.get('priceDetail') or {}
    tag = (detail.get('promotionalTag') or {}).get('text', '')
    conditions = {
        'etiqueta': tag,
        'tipo': detail.get('promotionType'),
        'cantidad': detail.get('itemsRequiredForPromotion'),
        'mensaje': detail.get('promotionMessage'),
        'medios_pago': detail.get('paymentMethod'),
        'membresias': detail.get('membership'),
        'promocion': product.get('promotion'),
    }
    return {
        'sku': product['sku'], 'nombre': product['name'], 'ean': product.get('ean'),
        'precio_publicado_CLP': offer.get('price'),
        'precio_lista_declarado_CLP': offer.get('listPrice'),
        'club_unimarc': 'club unimarc' in tag.lower(),
        'cantidad_disponible_declarada': offer.get('availableQuantity'),
        'precio_por_unidad_texto': offer.get('ppum'),
        'categoria_tienda': product.get('categorySlug'),
        'condiciones': json.dumps(conditions, ensure_ascii=False),
        'url': BASE + product['detailUrl'],
    }


async def run(out):
    out.mkdir(parents=True, exist_ok=True)
    rows, seen, pages = [], set(), []
    total = None
    async with HttpClient(max_retries=1) as http:
        for page in range(1, 41):
            url = f'{BASE}/category/{CATEGORY}?page={page}'
            html = await http.get_text(url, rps=0.5, headers=BROWSER_HEADERS)
            received, declared, products = extract(html)
            if int(received) != page:
                raise ValueError('La tienda ignoró el número de página')
            if total is None:
                total = declared
            before = len(seen)
            for product in products:
                if product['sku'] not in seen:
                    seen.add(product['sku'])
                    rows.append(row(product))
            pages.append({'page': page, 'url': url, 'declared': declared,
                          'rows': len(products), 'new_skus': len(seen)-before})
            print(f'Página {page}: {len(products)} filas, {len(seen)} SKU únicos / {total}', flush=True)
            if not products or page * 50 >= total or len(seen) == before:
                break
    report = {'captured_at_utc': datetime.now(timezone.utc).isoformat(),
              'category': CATEGORY, 'declared_initial': total, 'unique_skus': len(rows),
              'club_rows': sum(r['club_unimarc'] for r in rows),
              'context': 'Visitante anónimo; sin sucursal fijada. No es cobertura nacional.',
              'pages': pages}
    (out/'resumen.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if rows:
        with (out/'precios.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({k:v for k,v in report.items() if k!='pages'},ensure_ascii=False))
    if len(rows) != total:
        raise SystemExit('Cobertura parcial: revisar resumen.json')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    asyncio.run(run(parser.parse_args().out))
