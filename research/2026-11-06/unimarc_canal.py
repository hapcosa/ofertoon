"""¿El precio del listado de Unimarc depende del salesChannel (co_sc)?

Caso de control incluido: un co_sc inexistente TIENE que comportarse distinto a
uno válido (o fallar), si no la medición no prueba nada.
"""
import asyncio, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import httpx
from selectolax.parser import HTMLParser
from scrapers.http import BROWSER_HEADERS

URL='https://www.unimarc.cl/category/lacteos-huevos-y-refrigerados/leches-y-cremas/leches-blancas'

def extract(html):
    node=HTMLParser(html).css_first('#__NEXT_DATA__')
    if node is None: return None
    props=json.loads(node.text())['props']['pageProps']
    for q in props['dehydratedState']['queries']:
        k=q.get('queryKey')
        if isinstance(k,list) and k[0]=='productsSearch-client':
            d=q['state']['data']
            prods=d['availableProducts']+d['notAvailableProducts']
            return int(d['resource']), {p['sku']:((p.get('sellers') or [{}])[0].get('price'),
                                                  (p.get('sellers') or [{}])[0].get('listPrice'))
                                        for p in prods}
    return None

async def main():
    casos=[('sin cookie',None),('co_sc=39','39'),('co_sc=1','1'),('co_sc=2','2'),
           ('co_sc=40','40'),('co_sc=99999 (control)','99999')]
    res={}
    async with httpx.AsyncClient(timeout=40, follow_redirects=True) as c:
        for nombre,sc in casos:
            h=dict(BROWSER_HEADERS)
            if sc: h['Cookie']=f'co_sc={sc}'
            try:
                r=await c.get(URL,headers=h)
                out=extract(r.text)
                if out is None:
                    print(f'{nombre:24} HTTP {r.status_code}  SIN __NEXT_DATA__/query')
                else:
                    tot,prices=out
                    res[nombre]=prices
                    print(f'{nombre:24} HTTP {r.status_code}  declara {tot}  skus {len(prices)}')
            except Exception as e:
                print(f'{nombre:24} ERROR {type(e).__name__}: {e}')
            await asyncio.sleep(4)
    base=res.get('sin cookie')
    if base:
        print('\n--- diffs contra "sin cookie" (mismo sku, precio distinto) ---')
        for n,p in res.items():
            if n=='sin cookie': continue
            comunes=set(base)&set(p)
            dif=[(s,base[s],p[s]) for s in comunes if base[s]!=p[s]]
            print(f'{n:24} comunes {len(comunes):3}  distintos {len(dif):3}  solo-en-base {len(set(base)-set(p)):3}  solo-en-otro {len(set(p)-set(base)):3}')
            for d in dif[:5]: print('      ',d)
    salida = Path(__file__).parent / 'unimarc_canal_precios.json'
    salida.write_text(json.dumps({k: {s: list(v) for s, v in p.items()} for k, p in res.items()},
                                 ensure_ascii=False, indent=1))
    print('precios por canal ->', salida)
asyncio.run(main())
