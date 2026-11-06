# Backtest del 2026-11-06 — los θ medidos y la decisión que esperan

Corrida: `python -m pricing.backtest --from 2026-08-15 --to 2026-10-07
--exclude-day 2026-09-18 --exclude-day 2026-09-19 --exclude-day 2026-09-29`.
51 días de mercado, 135.880 listings, ~25 min.

Se escribe acá porque el número que importa —el θ que pasaría el gate— es
**evidencia medida esperando una decisión de producto**, y hasta hoy vivía solo
en el prompt de traspaso de la sesión que lo corrió.

## Lo medido

Solo **7 de las 17** categorías son medibles en ese rango: el resto no tiene
30 días de serie **más** 30 de futuro para etiquetar, y ahí un 0 no significa
nada (CLAUDE.md §Pasos 2).

    categoría            θ hoy   señ./día  precisión  gate   θ que pasaría
    ferre-herramientas   0.250      3.2      91.3%     ✓     0.25 (ya está)
    tecno-celulares      0.150      4.9      93.3%     ✓     0.15 (ya está)
    tecno-tv             0.180    2.3-4.3   93-97%   borde   0.15
    hogar-electro        0.200      2.5      95.3%     ✗     0.15
    tecno-notebooks      0.150      2.5      93.8%     ✗     0.10
    tecno-componentes    0.150      2.3      90.6%     ✗     0.10
    ferre-jardin         0.250      1.2      96.0%     ✗     0.10

**El limitante es el VOLUMEN, no la precisión.** Casi todas las filas están
entre 90% y 100%, muy por encima del 80% que pide el gate; lo que no se alcanza
son las 3 ofertas/día. O sea hay margen para bajar θ y ganar ofertas sin romper
la promesa del canal — y es justo al revés de lo que sugiere la intuición de
"bajar θ ensucia el canal".

Mover un θ **es una decisión de producto**: se mide, se reporta y la toma el
dueño. Esta tabla es la parte de medir.

## Dos cautelas, para no sobreleer la tabla

1. **No se compara de frente con la calibración del 5-nov.** No está registrado
   con qué rango se corrió, y el rango cambia el volumen: `señales/día` es
   señales dividido por días de mercado, así que dos rangos distintos dan dos
   números distintos para el mismo θ.
2. **`tecno-componentes` a θ 0.35 tiene más de la mitad de sus aciertos en
   liquidación.** Eso no describe un canal de ofertas, describe un outlet. La
   fila de arriba (θ 0.150) no sufre ese sesgo, pero conviene saber que la
   categoría lo tiene al subir.

## El desfase que esta corrida dejó abierto (no es un bug)

El backtest mide con **30** días de historia mínima y producción corre con
**20** desde la migración 48: `replay_listing` llama a `evaluate` sin
`min_history_days`, así que cae en el default `MIN_DAYS = 30` de
`baselines.py`. Verificado en el código, no deducido.

Era un desfase *temporal* por diseño —la migración 32 contaba con que las
categorías maduraran y la columna volviera a 30— y con los 20 permanentes ese
supuesto se cayó: **el θ que sale del backtest describe un detector que no es el
que corre.**

Pero todavía **no tiene consecuencia medible**: en el rango medible las
categorías afectadas ni aparecen, porque no tienen 30 días de futuro para
etiquetar. El efecto recién se puede medir sobre noviembre, o sea ~diciembre.

Si llegado ese momento se decide que el backtest lea la columna, el cambio son
cuatro ediciones en `pricing/backtest.py`: `replay_listing` acepta
`min_history_days` y lo pasa a `evaluate`; `load_series` agrega
`c.min_history_days` al SELECT y devuelve un tercer dict indexado por
`category_slug`; `run_backtest` lo propaga. Dos tests lo cubren —uno con 20 que
emite y uno con 30 que no, sobre una serie de 25 días de historia.

El costo a declarar antes de hacerlo: el **Cyber Monday del 5-7 de octubre** —el
único evento de descuentos reales de la serie— se mediría contra baselines de 20
días, que es exactamente lo que la migración 32 §2 quería evitar.

---

## Medido el 2026-11-06: qué hace el piso de 20 antes de que publique

El piso de 20 días se aplicó el 6-nov 13:52 UTC y **el pipeline no volvió a
correr desde entonces** (el último fue el 5-nov 18:51 UTC), así que la base no
muestra todavía ni un candidato producido con él. Esto lo mide offline, sin
escribir nada: se repite el SELECT de `detector._load_candidates` —sin su
`NOT EXISTS`, para ver la foto completa— y se corre `evaluate` dos veces por
observación, una con el `min_history_days` de la base (20) y otra forzando 30.

Reloj de la medición: el de las baselines vigentes (5-nov 18:51 UTC). Con `NOW()`
el filtro de `PRICE_MAX_AGE_HOURS` vaciaría la muestra y el resultado sería 0 por
construcción. **66.146 observaciones.**

    veredicto            con 20      con 30     delta
    accepted                515         409      +106
    history               40701       47034     -6333
    threshold             22083       15961     +6122
    ramp                    428         346       +82
    above_floor             178         155       +23
    refurbished            2149        2149        +0
    out_of_stock             64          64        +0
    server_hw                28          28        +0

Lo que dice, y no es lo que uno esperaría:

1. **6.333 observaciones cruzan la guarda de historia** que antes rechazaba, pero
   **6.122 de ellas mueren en θ**. El piso no las convierte en ofertas: las
   convierte en rechazos por umbral, que es un rechazo que **sí se persiste** y
   por lo tanto sí calibra.
2. **El pool de aceptados sube 409 → 515, un +26%.** Los 106 nuevos, por
   categoría: `tecno-audio` 46, `supermercado` 21, `tecno-celulares` 9,
   `deporte-equipamiento` 6, `deporte-vestuario` 6, `hogar-electro` 5,
   `tecno-componentes` 4, `ropa-calzado` 4, `ferre-herramientas` 2, y 1 cada una
   en `ferre-jardin`, `deporte-calzado` y `tecno-tv`.
3. **Y la cuota diaria es 33.** Con 409 aceptados ya había 12 candidatos por
   lugar; con 515 hay 15. O sea el piso de 20 **no publica más ofertas: cambia
   cuáles ganan**, y mete 106 que se miden contra un p50 de 20 a 29 días en una
   competencia que antes era solo entre series de 30 o más. El efecto es de
   composición, no de volumen — que es justo lo que no se ve mirando el total
   publicado.

Dos límites de esta medición, para no sobreleerla: no modela el **cooldown**
(`prior_post=None`), así que los aceptados son un techo —hay 545 `deal_posts`, el
último del 5-nov—; y no modela las promociones de multicompra, que solo pueden
sumar. Reproducible con el script del scratchpad de la sesión; el SELECT es el de
`detector._load_candidates` sin el `NOT EXISTS`.
