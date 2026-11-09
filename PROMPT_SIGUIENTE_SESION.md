# Prompt para la sesión siguiente

Pegá todo lo que está dentro del bloque. Está escrito para que no haga falta leer
el historial de la sesión anterior.

---

```
Continuás el trabajo de expansión de tiendas de OfertasCL. Todo lo de abajo está
commiteado en `main` y los 790 tests pasan.

PRIMERO, SIN EXCEPCIÓN
Leé CLAUDE.md. Es la puerta de entrada y te dice qué leer según la tarea. Y leé
su §Trabajo multi-agente ANTES de crear nada: hay otros agentes en este repo y
las cuatro formas de pisarse que documenta ya ocurrieron, ninguna ruidosamente.
Creá tu propia rama y tu propio worktree:

    cd ~/servicios/ofertoon
    git worktree add ../ofertoon-<tema> -b feat/<tema>

El próximo número de migración libre sale del comando de §Trabajo multi-agente
§2 (hoy el mayor es 46). NO uses `ls migrations/ | tail -1` de tu árbol.

DOS COSAS VENCIDAS QUE MIRAR ANTES DE EMPEZAR
1. `categories.min_history_days` sigue en 10 en siete categorías
   (deporte-calzado, deporte-equipamiento, deporte-vestuario, ropa-accesorios,
   ropa-calzado, supermercado, tecno-audio). CLAUDE.md mandaba revertirlo a 30
   el 2026-11-06 y no se hizo. Es un write a producción: reportalo y que lo
   decida el dueño, no lo apliques solo.
2. Las migraciones 40 a 46 están escritas y SIN APLICAR. Suman 11 tiendas y 552
   llaves. La secuencia completa está en un solo checkout, que es lo que exige
   CLAUDE.md §Paso 3 — si creás un worktree, aplicarlas desde ahí saltearía en
   silencio las que no estén en tu árbol.

DECISIONES DEL DUEÑO YA TOMADAS — no las vuelvas a plantear
- Las promociones de multicompra VAN al canal, y el mensaje declara que el
  ahorro es por cantidad y no una rebaja por unidad. Ya está implementado
  (detector + copy + migración 46).
- Ofertas en USD y EUR también sirven. Lo prohibido sigue siendo CONVERTIR: la
  moneda viaja con el precio y una serie nunca mezcla dos. Eso habilita
  cruceros.cl (14.285 zarpadas) y las otras monedas de nomades, y requiere
  trabajo de esquema acotado en INVESTIGACION_viajes.md §2.bis.
- Club Unimarc cuenta como oferta (ser Club es solo dar el RUT). No es tarjeta
  de la casa, pero el copy conserva la condición visible.
- New Balance entra con las vitrinas EXCLUIDAS, asumiendo la pérdida del 35%.

LO SIGUIENTE, EN ORDEN DE VALOR
1. ADAPTADOR DE UNIMARC. Es donde la promo de multicompra se encuentra con la
   tienda que la motivó. La investigación está hecha en
   research/2026-11-05/INVESTIGACION.md: catálogo en `__NEXT_DATA__` de las
   páginas `/category/...`, query `productsSearch-client`, pagina con `?page=N`,
   719 de 719 SKUs con EAN al 100%.
   Lo que falta y es del dominio, no del scraping:
   - Llenar `scrapers.base.PromoCantidad` desde `promocion.descriptionMessage`
     ("4 x $1.000") y `cantidad`. El detector ya sabe qué hacer con eso.
   - ⚠️ RESOLVER LA SUCURSAL ANTES DE CONECTARLA. El recorrido fue anónimo y sin
     sucursal fijada. Si el precio es por sucursal, la serie es de esa sucursal y
     cambiarla después invalida el histórico entero — es el caso Construmart.
   - La etiqueta Club vive en `priceDetail.promotionalTag.text`, y `membership`
     viene VACÍO en ofertas que sí dicen Club: mirar ese arreglo no alcanza.
2. SPARTA. Medida y lista salvo una decisión: su 1,72× de solapamiento residual
   cruza categorías internas distintas (vestuario × equipamiento 30-36%), así que
   con `dedupe_across_categories` gana la primera llave del orden de
   `db.load_store_targets` y una polera podría puntuar con el θ de equipamiento.
   Hay que ordenar los `store_key` a propósito o renunciar a los ejes que cruzan.
   Ver INVESTIGACION_deporte_outdoor.md §1.
3. PC EXPRESS. Host real `tienda.pc-express.cl` (su `www` redirige 301). Hoy
   solo está respondido el borde; faltan once de las doce preguntas.
4. LAS OTRAS SALESFORCE. Hites ya tiene adaptador propio (lo escribió otra
   sesión). Tricot, abc.cl y marathon.cl siguen sin nada y comparten plataforma:
   un `salesforce_family` cubriría las tres. Lo medido está en
   INVESTIGACION_ropa.md — orden estable (Jaccard 1,0000 en las tres), y dos
   trampas: en Hites el `data-pid` está en el tile pero en Tricot en el PADRE y
   en abc en un DESCENDIENTE, y abc cotiza POR ZONA DE INVENTARIO (caso
   Construmart).
5. KLIPER. Bloqueada por presupuesto, no por taxonomía: 706 requests / 35,7 min
   dejarían la pasada en ~114 min de los 120 de PASS_WINDOW. Si se quiere, hay
   que recortarle llaves.

CÓMO SE TRABAJA ACÁ, EN CORTO
- Verificá el efecto, nunca el mensaje. `--dry-run` no ejercita el INSERT;
  `db-migrate` sobre una imagen vieja dice "0 aplicadas" igual que una corrida
  sana; `docker ps` puede decir `Up` de un contenedor vacío.
- Una prueba sin caso de control es un falso verde. Si validás un límite, incluí
  el caso que TIENE que fallar.
- Un veredicto de acceso tiene fecha. Este repo declaró cuatro tiendas
  inaccesibles y las cuatro eran accesibles; el error fue siempre el mismo —
  medir el host o la ruta equivocados y concluir sobre la tienda.
- Las llaves se verifican disjuntas SOBRE SKUs REALES antes de la migración.
- No commitees ni pushees salvo que te lo pidan.
- Avisá cualquier decisión que tomes por tu cuenta, por chica que parezca.

DOCUMENTOS DE ESTA TANDA
TIENDAS.md (censo: conectado vs lo que entra, y el orden sugerido),
TIENDAS_PROHIBIDAS.md (lo que no se puede, con la razón medida y su fecha),
INVESTIGACION_{deporte_outdoor,ropa,hardware,viajes,TANDA2}.md.
```
