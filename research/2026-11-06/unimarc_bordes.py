"""Las cuatro preguntas que el recorrido completo no contesta (PLAN_EXPANSION §1).

  #3  ¿Qué juego de headers hace falta? Los tres, 4 intentos cada uno, aislando
      la variable: un 429 persistente puede ser el UA y no la tasa (caso Prat).
  #5  ¿El orden es estable entre requests? Dos recorridos de la misma llave,
      contando únicos: un SKU intermitente nunca llega a MIN_DAYS y por lo tanto
      nunca produce baseline (caso Tottus).
  #4  ¿Cómo señala el final? Una página pasada del último.
  #10 ¿Precios centinela? Se calcula sobre el CSV del recorrido completo.

    .venv/bin/python research/2026-11-06/unimarc_bordes.py
"""
import asyncio, csv, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import httpx
from selectolax.parser import HTMLParser
from scrapers.http import BROWSER_HEADERS, BROWSER_USER_AGENT, DEFAULT_USER_AGENT

BASE = 'https://www.unimarc.cl'
SC = {'Cookie': 'co_sc=39'}


def catalogo(html):
    node = HTMLParser(html).css_first('#__NEXT_DATA__')
    if node is None:
        return None
    pp = json.loads(node.text())['props']['pageProps']
    for q in pp['dehydratedState']['queries']:
        if isinstance(q.get('queryKey'), list) and q['queryKey'][0] == 'productsSearch-client':
            d = q['state']['data']
            return int(d['resource']), d['availableProducts'] + d['notAvailableProducts']
    return None


async def pregunta_3(c):
    print('--- #3 headers (4 intentos de cada uno, misma URL) ---')
    url = f'{BASE}/category/mascotas'
    juegos = {
        'DEFAULT_USER_AGENT':  {'User-Agent': DEFAULT_USER_AGENT, **SC},
        'BROWSER_USER_AGENT':  {'User-Agent': BROWSER_USER_AGENT, **SC},
        'BROWSER_HEADERS':     {**BROWSER_HEADERS, **SC},
    }
    for nombre, headers in juegos.items():
        codigos, catalogos = [], 0
        for _ in range(4):
            try:
                r = await c.get(url, headers=headers)
                codigos.append(r.status_code)
                if r.status_code == 200 and catalogo(r.text):
                    catalogos += 1
            except Exception as e:
                codigos.append(type(e).__name__)
            await asyncio.sleep(3)
        print(f'  {nombre:20} {codigos}  con catálogo: {catalogos}/4')


async def pregunta_5(c):
    print('--- #5 estabilidad del orden: segundo recorrido de `mascotas` ---')
    vistos, orden = set(), []
    for page in range(1, 9):
        r = await c.get(f'{BASE}/category/mascotas?page={page}', headers={**BROWSER_HEADERS, **SC})
        out = catalogo(r.text)
        if out is None:
            print(f'  p{page}: sin catálogo'); break
        total, prods = out
        for p in prods:
            orden.append(str(p.get('sku')))
            vistos.add(str(p.get('sku')))
        print(f'  p{page}: {len(prods)} filas, {len(vistos)} únicos / {total}')
        if not prods or page * 50 >= total:
            break
        await asyncio.sleep(3)
    return vistos, orden


async def pregunta_4(c):
    print('--- #4 una página pasada del final (`mascotas` tiene 5) ---')
    for page in (6, 9):
        r = await c.get(f'{BASE}/category/mascotas?page={page}', headers={**BROWSER_HEADERS, **SC})
        out = catalogo(r.text)
        if out is None:
            print(f'  p{page}: HTTP {r.status_code}, SIN catálogo en el payload')
        else:
            total, prods = out
            print(f'  p{page}: HTTP {r.status_code}, {len(prods)} filas (declara {total})')
        await asyncio.sleep(3)


def pregunta_10(csv_path):
    print('--- #10 precios centinela (catálogo completo del recorrido) ---')
    precios = []
    for r in csv.DictReader(open(csv_path, encoding='utf-8-sig')):
        for campo in ('precio', 'lista'):
            try:
                precios.append((int(float(r[campo])), r['sku'], r['nombre'][:40]))
            except (TypeError, ValueError):
                pass
    precios.sort(reverse=True)
    print(f'  máximo observado: ${precios[0][0]:,} ({precios[0][1]} {precios[0][2]})')
    print(f'  top 5: {[p[0] for p in precios[:5]]}')
    print(f'  por encima de 100.000.000 (MAX_PLAUSIBLE_CLP): '
          f'{sum(1 for p in precios if p[0] > 100_000_000)}')
    print(f'  en cero: {sum(1 for p in precios if p[0] == 0)}')


async def main():
    csv_path = Path(__file__).parent / 'unimarc_skus.csv'
    async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
        await pregunta_3(c)
        vistos, orden = await pregunta_5(c)
        await pregunta_4(c)
    primero = {r['sku'] for r in csv.DictReader(open(csv_path, encoding='utf-8-sig'))
               if r['llave'] == 'mascotas'}
    print(f'  recorrido 1: {len(primero)} únicos | recorrido 2: {len(vistos)} únicos')
    print(f'  en ambos: {len(primero & vistos)} | solo en 1: {len(primero - vistos)} '
          f'| solo en 2: {len(vistos - primero)}')
    print(f'  filas recorrido 2: {len(orden)} -> únicos {len(set(orden))} '
          f'(cobertura {len(set(orden))/max(len(orden),1):.4f})')
    if csv_path.exists():
        pregunta_10(csv_path)

asyncio.run(main())
