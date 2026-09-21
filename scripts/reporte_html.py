"""Genera un reporte HTML del estado del detector: qué aceptó y qué descartó.

Es una foto, no un servicio: consulta la base y escribe un archivo. Se regenera
corriéndolo de nuevo, que es lo correcto para un pipeline que produce dos veces
al día — un dashboard con reloj propio agregaría un proceso más para mirar datos
que cambian cada 12 h.

Deliberadamente NO muestra los candidatos como "ofertas publicadas": hasta que θ
esté calibrado (~2026-09-17) son materia prima del backtest. La página lo dice
arriba de todo, porque un reporte que se lee como catálogo de ofertas es
exactamente el malentendido caro.

Uso:
    docker compose cp scripts/reporte_html.py scraper:/tmp/
    docker compose exec -T scraper python /tmp/reporte_html.py --out /tmp/reporte.html
    docker compose cp scraper:/tmp/reporte.html ./reporte.html
"""
from __future__ import annotations

import argparse
import asyncio
import html
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import asyncpg

TZ = ZoneInfo("America/Santiago")

#: Qué guarda rechazó y por qué importa. El reporte explica cada motivo en vez de
#: mostrar el enum crudo: el valor del sistema está en las guardas, no en el conteo.
MOTIVOS = {
    "threshold": (
        "Bajo el umbral",
        "El descuento contra el precio real no llega al θ de su categoría. "
        "Es fluctuación normal, no una oferta.",
    ),
    "ramp": (
        "Precio inflado antes",
        "Subió y se sostuvo antes de esta “baja”. Es la estafa que el sistema "
        "existe para no publicar.",
    ),
    "above_floor": (
        "Sobre el piso habitual",
        "Está por encima del p10: este precio ya se vio varias veces en dos "
        "meses. No es noticia.",
    ),
    "history": (
        "Sin historia suficiente",
        "Menos de 30 días de serie. Sin eso el “precio real” es una opinión. "
        "No deja fila en la tabla; se cuenta en el log.",
    ),
    "out_of_stock": (
        "Sin stock",
        "Publicar lo que no se puede comprar quema la credibilidad más rápido "
        "que cualquier error de precio.",
    ),
    "cooldown": (
        "Repetido",
        "Ya se publicó hace menos de 21 días y no bajó lo suficiente como para "
        "volver a contarlo.",
    ),
}


#: `strftime('%B')` depende del locale del contenedor, que es C. Se arma a mano.
MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def fecha_larga(d) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def num(value: int) -> str:
    """Miles con punto, como se escriben en Chile."""
    return f"{int(value):,}".replace(",", ".")


def clp(value: Decimal | int | None) -> str:
    if value is None:
        return "—"
    return f"${num(value)}"


def pct(value: Decimal | None, decimals: int = 1) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.{decimals}f}%"


def e(text: object) -> str:
    return html.escape(str(text if text is not None else ""))


#: Ventana del reporte. Es la misma que usa `curation.ranker.MAX_AGE_HOURS`: un
#: candidato con más de un ciclo de scraping encima tiene un precio que ya no está
#: verificado. Sin este corte el reporte suma las dos pasadas del día y muestra el
#: mismo producto dos veces.
VENTANA_HORAS = 13

#: Un listing puede tener varios candidatos aceptados en la ventana (uno por
#: observación). Vale el último: es el precio vigente.
ACEPTADOS = """
    SELECT DISTINCT ON (dc.listing_id)
           dc.price, dc.p50_60d, dc.discount_real, dc.score, dc.detected_at,
           l.name_raw, l.url, s.name AS tienda, cat.name AS categoria,
           b.p10_60d, b.min_60d, b.n_days, b.n_points
      FROM deal_candidates AS dc
      JOIN listings        AS l   ON l.id = dc.listing_id
      JOIN stores          AS s   ON s.id = l.store_id
      LEFT JOIN categories AS cat ON cat.id = l.category_id
      LEFT JOIN listing_baselines AS b ON b.listing_id = dc.listing_id
     WHERE dc.verdict = 'accepted'
       AND dc.detected_at >= NOW() - ($1 || ' hours')::INTERVAL
     ORDER BY dc.listing_id, dc.detected_at DESC
"""


async def fetch_all(conn: asyncpg.Connection) -> dict:
    ventana = str(VENTANA_HORAS)
    aceptados = sorted(
        [dict(r) for r in await conn.fetch(ACEPTADOS, ventana)],
        key=lambda r: r["score"] or 0,
        reverse=True,
    )
    rechazos = await conn.fetch(
        """
        SELECT reject_reason, COUNT(DISTINCT listing_id) AS n
          FROM deal_candidates
         WHERE verdict = 'rejected'
           AND detected_at >= NOW() - ($1 || ' hours')::INTERVAL
         GROUP BY 1 ORDER BY 2 DESC
        """,
        ventana,
    )
    por_tienda = await conn.fetch(
        """
        SELECT s.name AS tienda, COUNT(DISTINCT dc.listing_id) AS n
          FROM deal_candidates AS dc
          JOIN listings AS l ON l.id = dc.listing_id
          JOIN stores   AS s ON s.id = l.store_id
         WHERE dc.verdict = 'accepted'
           AND dc.detected_at >= NOW() - ($1 || ' hours')::INTERVAL
         GROUP BY 1 ORDER BY 2 DESC
        """,
        ventana,
    )
    resumen = await conn.fetchrow(
        """
        SELECT (SELECT COUNT(*) FROM listings WHERE is_active)          AS listings,
               (SELECT COUNT(*) FROM listing_baselines
                 WHERE n_points >= 30 AND n_days >= 30)                 AS publicables,
               (SELECT COUNT(*) FROM listing_baselines)                 AS baselines,
               (SELECT MAX(computed_at) FROM listing_baselines)         AS computed_at,
               (SELECT COUNT(*) FROM deal_posts)                        AS publicados,
               (SELECT MIN(observed_at)::date FROM price_points)        AS serie_desde
        """
    )
    return {
        "aceptados": aceptados,
        "rechazos": [dict(r) for r in rechazos],
        "por_tienda": [dict(r) for r in por_tienda],
        "resumen": dict(resumen),
    }


def fila_candidato(i: int, r: dict) -> str:
    """Una fila con su bullet chart: cuánto del precio real estás pagando.

    La escala es 0..p50 (el precio de verdad). La barra llena es lo que se paga,
    así que el hueco ES el descuento; la marca fina es el p10, el piso habitual.
    Es el encoding que dice la tesis del producto sin texto de apoyo.
    """
    p50 = float(r["p50_60d"] or 0)
    price = float(r["price"])
    ancho = max(2.0, min(100.0, price / p50 * 100)) if p50 else 0.0
    p10 = float(r["p10_60d"]) if r["p10_60d"] is not None else None
    marca = min(100.0, p10 / p50 * 100) if (p10 and p50) else None

    tick = (
        f'<span class="tick" style="left:{marca:.2f}%" '
        f'title="piso habitual (p10): {e(clp(r["p10_60d"]))}"></span>'
        if marca is not None
        else ""
    )
    return f"""
      <li class="deal">
        <span class="rank">{i}</span>
        <div class="deal-head">
          <a class="deal-name" href="{e(r['url'])}" target="_blank" rel="noopener">{e(r['name_raw'])}</a>
          <p class="deal-meta">
            <span class="chip">{e(r['tienda'])}</span>
            <span>{e(r['categoria'] or 'sin categoría')}</span>
            <span class="sep" aria-hidden="true">·</span>
            <span>{int(r['n_days'] or 0)} días de serie</span>
          </p>
        </div>
        <div class="deal-figure">
          <div class="track" role="img"
               aria-label="Paga {e(clp(r['price']))} de un precio real de {e(clp(r['p50_60d']))}">
            <span class="fill" style="width:{ancho:.2f}%"></span>{tick}
          </div>
          <p class="scale">
            <span class="now">{e(clp(r['price']))}</span>
            <span class="ref">precio real {e(clp(r['p50_60d']))}</span>
          </p>
        </div>
        <span class="deal-cut">−{e(pct(r['discount_real'], 0))}</span>
      </li>"""


def render(data: dict) -> str:
    resumen = data["resumen"]
    aceptados = data["aceptados"]
    ahora = datetime.now(timezone.utc).astimezone(TZ)
    computed = resumen["computed_at"]
    computed_txt = (
        computed.astimezone(TZ).strftime("%d/%m %H:%M") if computed else "nunca"
    )
    evaluados = sum(r["n"] for r in data["rechazos"]) + len(aceptados)

    filas = "\n".join(fila_candidato(i, r) for i, r in enumerate(aceptados, 1))

    max_rechazo = max((r["n"] for r in data["rechazos"]), default=1) or 1
    rechazos_html = "\n".join(
        f"""
        <li class="reason">
          <div class="reason-head">
            <span class="reason-name">{e(MOTIVOS.get(r['reject_reason'], (r['reject_reason'], ''))[0])}</span>
            <span class="reason-n">{num(r['n'])}</span>
          </div>
          <div class="bar"><span style="width:{r['n'] / max_rechazo * 100:.2f}%"></span></div>
          <p class="reason-why">{e(MOTIVOS.get(r['reject_reason'], ('', '—'))[1])}</p>
        </li>"""
        for r in data["rechazos"]
    )

    tiendas_html = "\n".join(
        f'<li><span>{e(r["tienda"])}</span><b>{r["n"]}</b></li>'
        for r in data["por_tienda"]
    )

    return f"""<title>Detector Ofertoon</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600&display=swap">
<style>
  :root {{
    --ground:#f5f7f4; --surface:#ffffff; --ink:#151a17; --muted:#5f6a63;
    --hair:#e1e6e1; --track:#eaeee9; --accent:#0e6b57; --accent-soft:#dceee8;
    --attention:#9c5a18; --attention-soft:#f6ead9;
    --serif:"IBM Plex Serif",Georgia,serif;
    --sans:"IBM Plex Sans",system-ui,-apple-system,sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,monospace;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --ground:#0e1211; --surface:#161b19; --ink:#e7ebe8; --muted:#94a09a;
      --hair:#252c29; --track:#212724; --accent:#43be9d; --accent-soft:#17322b;
      --attention:#d08a3e; --attention-soft:#332514;
    }}
  }}
  :root[data-theme="dark"] {{
    --ground:#0e1211; --surface:#161b19; --ink:#e7ebe8; --muted:#94a09a;
    --hair:#252c29; --track:#212724; --accent:#43be9d; --accent-soft:#17322b;
    --attention:#d08a3e; --attention-soft:#332514;
  }}

  *,*::before,*::after {{ box-sizing:border-box; }}
  body {{ background:var(--ground); color:var(--ink); font-family:var(--sans);
         line-height:1.5; -webkit-font-smoothing:antialiased; }}
  .wrap {{ max-width:1000px; margin:0 auto; padding:48px 24px 72px;
           display:flex; flex-direction:column; gap:40px; }}
  a {{ color:inherit; }}
  :focus-visible {{ outline:2px solid var(--accent); outline-offset:3px; border-radius:2px; }}

  /* Masthead */
  .mast {{ display:flex; flex-direction:column; gap:14px; }}
  .eyebrow {{ font-family:var(--mono); font-size:11px; letter-spacing:.14em;
              text-transform:uppercase; color:var(--muted); margin:0; }}
  h1 {{ font-family:var(--serif); font-weight:600; font-size:clamp(30px,5vw,42px);
        margin:0; letter-spacing:-.015em; text-wrap:balance; }}
  .lede {{ margin:0; max-width:62ch; color:var(--muted); font-size:15.5px; }}
  .lede b {{ color:var(--ink); font-weight:600; }}

  .notice {{ display:flex; gap:12px; align-items:flex-start; padding:14px 16px;
             background:var(--attention-soft); border-left:3px solid var(--attention);
             border-radius:0 6px 6px 0; }}
  .notice p {{ margin:0; font-size:14px; }}
  .notice .label {{ font-family:var(--mono); font-size:11px; letter-spacing:.1em;
                    text-transform:uppercase; color:var(--attention); font-weight:600;
                    white-space:nowrap; padding-top:2px; }}

  /* Tiles */
  .tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
            gap:1px; background:var(--hair); border:1px solid var(--hair);
            border-radius:8px; overflow:hidden; }}
  .tile {{ background:var(--surface); padding:18px 20px;
           display:flex; flex-direction:column; gap:4px; }}
  .tile dt {{ font-family:var(--mono); font-size:10.5px; letter-spacing:.11em;
              text-transform:uppercase; color:var(--muted); }}
  .tile dd {{ margin:0; font-family:var(--mono); font-size:28px; font-weight:500;
              font-variant-numeric:tabular-nums; letter-spacing:-.02em; }}
  .tile .sub {{ font-size:12.5px; color:var(--muted); font-family:var(--sans); }}
  .tile.key dd {{ color:var(--accent); }}

  section > h2 {{ font-family:var(--serif); font-weight:600; font-size:21px;
                  margin:0 0 4px; letter-spacing:-.01em; }}
  .section-note {{ margin:0 0 20px; color:var(--muted); font-size:14px; max-width:62ch; }}

  /* Candidatos */
  .deals {{ list-style:none; margin:0; padding:0;
            border:1px solid var(--hair); border-radius:8px; background:var(--surface); }}
  .deal {{ display:grid; gap:4px 16px; padding:16px 20px;
           grid-template-columns:28px minmax(0,1fr) 230px 76px; align-items:center; }}
  .deal + .deal {{ border-top:1px solid var(--hair); }}
  .rank {{ font-family:var(--mono); font-size:12px; color:var(--muted);
           font-variant-numeric:tabular-nums; }}
  .deal-head {{ min-width:0; }}
  .deal-name {{ font-weight:500; font-size:14.5px; text-decoration:none;
                display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .deal-name:hover {{ text-decoration:underline; text-decoration-color:var(--accent); }}
  .deal-meta {{ margin:3px 0 0; display:flex; gap:8px; align-items:center;
                flex-wrap:wrap; font-size:12px; color:var(--muted); }}
  .chip {{ font-family:var(--mono); font-size:10.5px; letter-spacing:.05em;
           text-transform:uppercase; background:var(--accent-soft); color:var(--accent);
           padding:2px 7px; border-radius:3px; font-weight:600; }}
  .sep {{ color:var(--hair); }}

  .deal-figure {{ display:flex; flex-direction:column; gap:5px; }}
  .track {{ position:relative; height:8px; background:var(--track); border-radius:2px; }}
  .fill {{ position:absolute; inset:0 auto 0 0; background:var(--accent);
           border-radius:2px 4px 4px 2px; }}
  /* El p10 nunca cae a la izquierda de la barra: la guarda 5 exige precio <= p10.
     Cuando coinciden, el anillo de superficie es lo que lo despega del relleno. */
  .tick {{ position:absolute; top:-3px; bottom:-3px; width:2px; background:var(--ink);
           opacity:.55; border-radius:1px; box-shadow:0 0 0 1.5px var(--surface); }}
  .scale {{ margin:0; display:flex; justify-content:space-between; gap:10px;
            font-family:var(--mono); font-size:11.5px; font-variant-numeric:tabular-nums; }}
  .scale .now {{ font-weight:600; }}
  .scale .ref {{ color:var(--muted); }}
  .deal-cut {{ font-family:var(--mono); font-size:19px; font-weight:600;
               color:var(--accent); text-align:right; font-variant-numeric:tabular-nums;
               letter-spacing:-.02em; }}

  /* Rechazos */
  .cols {{ display:grid; grid-template-columns:minmax(0,1.55fr) minmax(0,1fr); gap:36px; }}
  .reasons {{ list-style:none; margin:0; padding:0; display:flex;
              flex-direction:column; gap:18px; }}
  .reason-head {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px; }}
  .reason-name {{ font-size:14px; font-weight:500; }}
  .reason-n {{ font-family:var(--mono); font-size:13px; color:var(--muted);
               font-variant-numeric:tabular-nums; }}
  .bar {{ height:6px; background:var(--track); border-radius:2px; margin:6px 0 5px; }}
  .bar span {{ display:block; height:100%; background:var(--accent);
               opacity:.55; border-radius:2px; }}
  .reason-why {{ margin:0; font-size:13px; color:var(--muted); max-width:56ch; }}

  .aside {{ border:1px solid var(--hair); border-radius:8px;
            background:var(--surface); padding:20px; align-self:start; }}
  .aside h3 {{ font-family:var(--mono); font-size:10.5px; letter-spacing:.11em;
               text-transform:uppercase; color:var(--muted); margin:0 0 12px; font-weight:500; }}
  .aside ul {{ list-style:none; margin:0; padding:0; display:flex;
               flex-direction:column; gap:9px; }}
  .aside li {{ display:flex; justify-content:space-between; gap:12px;
               font-size:13.5px; align-items:baseline; }}
  .aside b {{ font-family:var(--mono); font-weight:500; font-variant-numeric:tabular-nums; }}

  .formula {{ border-top:1px solid var(--hair); padding-top:24px;
              display:flex; flex-direction:column; gap:10px; }}
  .formula code {{ font-family:var(--mono); font-size:14px; background:var(--surface);
                   border:1px solid var(--hair); border-radius:5px;
                   padding:10px 14px; display:inline-block; align-self:flex-start; }}
  .formula p {{ margin:0; color:var(--muted); font-size:13.5px; max-width:66ch; }}
  footer {{ color:var(--muted); font-size:12.5px; font-family:var(--mono);
            border-top:1px solid var(--hair); padding-top:18px; }}

  @media (max-width:820px) {{
    .deal {{ grid-template-columns:24px minmax(0,1fr) 64px; }}
    .deal-figure {{ grid-column:2 / -1; margin-top:6px; }}
    .cols {{ grid-template-columns:1fr; gap:28px; }}
  }}
  @media (prefers-reduced-motion:reduce) {{ * {{ animation:none !important; transition:none !important; }} }}
</style>

<div class="wrap">
  <header class="mast">
    <p class="eyebrow">Ofertoon · retail chileno · {e(fecha_larga(ahora))}, {e(ahora.strftime('%H:%M'))} Santiago</p>
    <h1>Qué encontró el detector</h1>
    <p class="lede">El descuento se mide contra lo que ese producto <b>costó de verdad
      las últimas 8 semanas</b>, no contra el precio tachado que declara la tienda.
      Serie desde el {e(fecha_larga(resumen['serie_desde']))}; baselines recalculadas
      el {e(computed_txt)}.</p>
    <div class="notice">
      <span class="label">Todavía no se publica</span>
      <p>Estos son <b>candidatos</b>, no ofertas enviadas al canal. Los umbrales por
        categoría no están calibrados —eso necesita 45 días de serie, alrededor del
        17 de septiembre— y el publisher está apagado a propósito hasta entonces.</p>
    </div>
  </header>

  <dl class="tiles">
    <div class="tile key">
      <dt>Ofertas reales</dt><dd>{len(aceptados)}</dd>
      <span class="sub">pasan las seis guardas</span>
    </div>
    <div class="tile">
      <dt>Evaluados</dt><dd>{num(evaluados)}</dd>
      <span class="sub">productos con precio fresco</span>
    </div>
    <div class="tile">
      <dt>Con historia</dt><dd>{num(resumen['publicables'])}</dd>
      <span class="sub">de {num(resumen['listings'])} productos vigilados</span>
    </div>
    <div class="tile">
      <dt>Publicadas</dt><dd>{resumen['publicados']}</dd>
      <span class="sub">el canal arranca tras calibrar</span>
    </div>
  </dl>

  <section>
    <h2>Las {len(aceptados)} que pasaron</h2>
    <p class="section-note">La barra es cuánto del precio real estás pagando: el hueco
      es el descuento. La marca fina es el piso habitual de los últimos 60 días —
      todo lo que está a su izquierda es un precio que casi nunca se vio.</p>
    <ol class="deals">
{filas}
    </ol>
  </section>

  <section>
    <h2>Y las {num(evaluados - len(aceptados))} que no</h2>
    <p class="section-note">Cada descarte queda guardado con su motivo. Ese registro es
      lo que después permite mover un umbral con evidencia en vez de a ojo.</p>
    <div class="cols">
      <ul class="reasons">
{rechazos_html}
      </ul>
      <div class="aside">
        <h3>Aceptadas por tienda</h3>
        <ul>
{tiendas_html}
        </ul>
      </div>
    </div>
  </section>

  <section class="formula">
    <h2>Cómo se calcula</h2>
    <code>descuento_real = 1 − precio_hoy / p50_60d</code>
    <p>El <b>p50_60d</b> es la mediana de lo que ese producto costó en los últimos 60
      días, calculada sobre nuestra propia serie. Un producto necesita 30 días y 30
      observaciones antes de que el sistema se anime a decir qué es caro y qué es
      barato para él.</p>
  </section>

  <footer>
    Generado por <code>scripts/reporte_html.py</code> · {e(ahora.strftime('%Y-%m-%d %H:%M'))} ·
    regenerar tras cada pasada del scraper
  </footer>
</div>
"""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reporte.html", help="archivo de salida")
    args = ap.parse_args()

    conn = await asyncpg.connect(os.environ["DATABASE_URL"])
    try:
        data = await fetch_all(conn)
    finally:
        await conn.close()

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(render(data))
    print(f"escrito {args.out}: {len(data['aceptados'])} aceptados")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
