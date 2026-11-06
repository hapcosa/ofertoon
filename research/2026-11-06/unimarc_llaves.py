"""Recorrido completo de las llaves candidatas de Unimarc. No escribe DB ni publica.

Contesta las tres cosas que la migración exige y el camino feliz no da:
  1. ¿Las llaves son disjuntas SOBRE SKUs REALES?
  2. ¿Dónde están los agotados? (el fixture tiene que incluirlos)
  3. ¿La paginación cierra contra el total que la tienda declara?

Fija `co_sc=39` en toda request: el precio de Unimarc DEPENDE del salesChannel
(medido el 2026-11-06, ver INVESTIGACION_unimarc.md §1), así que un recorrido sin
canal fijo mezcla dos series.

    .venv/bin/python research/2026-11-06/unimarc_llaves.py --out /tmp/unimarc-llaves
"""
import argparse, asyncio, csv, json, sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from selectolax.parser import HTMLParser
from scrapers.http import BROWSER_HEADERS, HttpClient

BASE = 'https://www.unimarc.cl'
SALES_CHANNEL = '39'
LLAVES = ['despensa', 'desayuno-y-dulces', 'bebidas-y-licores', 'limpieza', 'mascotas',
          'lacteos-huevos-y-refrigerados', 'congelados', 'perfumeria']
PAGE_SIZE = 50
MAX_PAGES = 80


def extract(html):
    node = HTMLParser(html).css_first('#__NEXT_DATA__')
    if node is None:
        raise ValueError('no hay __NEXT_DATA__')
    pp = json.loads(node.text())['props']['pageProps']
    for q in pp['dehydratedState']['queries']:
        k = q.get('queryKey')
        if isinstance(k, list) and k[0] == 'productsSearch-client':
            d = q['state']['data']
            return pp['page'], int(d['resource']), d['availableProducts'], d['notAvailableProducts']
    raise ValueError('falta productsSearch-client')


def fila(p, llave, pagina, disponible):
    s = (p.get('sellers') or [{}])[0]
    pd = p.get('priceDetail') or {}
    promo = p.get('promotion') or {}
    tag = ((pd.get('promotionalTag') or {}).get('text') or '')
    return {
        'llave': llave, 'pagina': pagina, 'bloque': 'disponible' if disponible else 'agotado',
        'sku': p.get('sku'), 'itemId': p.get('itemId'), 'productId': p.get('productId'),
        'nombre': p.get('name'), 'marca': p.get('brand'), 'ean': p.get('ean'),
        'precio': s.get('price'), 'lista': s.get('listPrice'),
        'disponibles_declarados': s.get('availableQuantity'),
        'ppum': s.get('ppum'), 'club': 'club unimarc' in tag.lower(), 'etiqueta': tag,
        'promo_cantidad': pd.get('itemsRequiredForPromotion'),
        'promo_mensaje': promo.get('descriptionMessage') or '',
        'promo_precio': promo.get('price'), 'promo_tiene_ahorro': promo.get('hasSavings'),
        'medios_pago': json.dumps(pd.get('paymentMethod') or [], ensure_ascii=False),
        'membresias': json.dumps(pd.get('membership') or [], ensure_ascii=False),
        'categoria_tienda': p.get('categorySlug'), 'url': BASE + (p.get('detailUrl') or ''),
    }


async def run(out):
    out.mkdir(parents=True, exist_ok=True)
    headers = {**BROWSER_HEADERS, 'Cookie': f'co_sc={SALES_CHANNEL}'}
    filas, por_llave, requests_hechas = [], {}, 0
    async with HttpClient(max_retries=2) as http:
        for llave in LLAVES:
            skus, declarado, paginas, agotados = set(), None, [], 0
            for page in range(1, MAX_PAGES + 1):
                url = f'{BASE}/category/{llave}?page={page}'
                html = await http.get_text(url, rps=0.4, headers=headers)
                requests_hechas += 1
                recibida, total, disp, nodisp = extract(html)
                if int(recibida) != page:
                    raise SystemExit(f'{llave}: pedí página {page} y la tienda sirvió {recibida}')
                if declarado is None:
                    declarado = total
                nuevos = 0
                for bloque, es_disp in ((disp, True), (nodisp, False)):
                    for p in bloque:
                        if p.get('sku') not in skus:
                            skus.add(p.get('sku'))
                            filas.append(fila(p, llave, page, es_disp))
                            nuevos += 1
                            if not es_disp:
                                agotados += 1
                paginas.append({'page': page, 'filas': len(disp) + len(nodisp),
                                'agotados_en_pagina': len(nodisp), 'nuevos': nuevos})
                print(f'  {llave:30} p{page:<3} {len(disp)+len(nodisp):3} filas '
                      f'({len(nodisp)} agotados)  únicos {len(skus)}/{declarado}', flush=True)
                if not (disp or nodisp) or page * PAGE_SIZE >= declarado or nuevos == 0:
                    break
            por_llave[llave] = {'declarado': declarado, 'unicos': len(skus),
                                'agotados': agotados, 'paginas': len(paginas),
                                'skus': sorted(skus), 'detalle': paginas}
            print(f'== {llave}: {len(skus)} únicos / {declarado} declarados, '
                  f'{len(paginas)} páginas, {agotados} agotados', flush=True)

    # Disjuntas sobre SKUs reales: cada par, no solo el total.
    solapes = []
    for i, a in enumerate(LLAVES):
        for b in LLAVES[i + 1:]:
            comun = set(por_llave[a]['skus']) & set(por_llave[b]['skus'])
            if comun:
                solapes.append({'a': a, 'b': b, 'comunes': len(comun),
                                'frac_a': len(comun) / max(len(por_llave[a]['skus']), 1),
                                'ejemplos': sorted(comun)[:5]})
    todos = [s for l in LLAVES for s in por_llave[l]['skus']]
    reporte = {
        'medido_utc': datetime.now(timezone.utc).isoformat(),
        'sales_channel': SALES_CHANNEL,
        'contexto': 'Visitante anónimo con co_sc=39 fijo. No es cobertura nacional.',
        'requests': requests_hechas,
        'filas_totales': len(todos), 'skus_unicos_globales': len(set(todos)),
        'llaves': {l: {k: v for k, v in d.items() if k != 'skus'} for l, d in por_llave.items()},
        'solapes_entre_llaves': solapes,
        'ean_presente': sum(1 for f in filas if f['ean']),
        'club': sum(1 for f in filas if f['club']),
        'promo_cantidad': sum(1 for f in filas if f['promo_cantidad']),
        'ppum_presente': sum(1 for f in filas if f['ppum']),
        'agotados': sum(1 for f in filas if f['bloque'] == 'agotado'),
        'medios_pago_no_vacios': sum(1 for f in filas if f['medios_pago'] != '[]'),
        'etiquetas': Counter(f['etiqueta'] for f in filas if f['etiqueta']).most_common(20),
    }
    (out / 'llaves.json').write_text(json.dumps(reporte, ensure_ascii=False, indent=2))
    with (out / 'skus.csv').open('w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(filas[0]))
        w.writeheader(); w.writerows(filas)
    print(json.dumps({k: v for k, v in reporte.items() if k not in ('llaves',)},
                     ensure_ascii=False, indent=1))
    for l, d in reporte['llaves'].items():
        print(f'  {l:30} {d["unicos"]:5}/{d["declarado"]:<5} págs {d["paginas"]:3} agotados {d["agotados"]:4}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, required=True)
    asyncio.run(run(ap.parse_args().out))
