# Prompt — agente de tiendas, rama `feat/tiendas-bloqueadas`

Pegá lo que está dentro del bloque.

---

```
Seguís en `feat/tiendas-bloqueadas` (worktree `~/servicios/ofertoon-bloqueadas`).
Tu trabajo anterior está integrado a `main`: Rockford (migración 50) y la tajada
de Sparta (52). Tu rama no tiene commits que `main` no tenga, así que arrancás
sincronizado — mergeá `main` antes de tocar nada, porque trae la 47 de Unimarc,
la 51 de MercadoPago y la 53 del piso de 10.

PRIMERO
Leé CLAUDE.md: la regla 5 cambió (el piso de historia es **10**, no 20 ni 30),
el §Paso 4 tiene una viñeta 🔴 sobre reiniciar el scraper, y §Trabajo
multi-agente tiene seis subsecciones.

ESTADO REAL, MEDIDO EN LA BASE EL 2026-11-07 — no lo heredes de ningún documento
  - **47 migraciones aplicadas: 01-46 y 48. Pendientes la 47, 50, 51, 52 y 53.**
    Sí: hay un hueco y cinco pendientes. Desde un árbol que no tenga esos
    archivos, `migrate.py --status` contesta "sin pendientes" **y es falso**. La
    verdad está en `SELECT filename FROM schema_migrations`.
  - 31 tiendas, 29 publican. `unimarc`, `rockford` y `sparta` **todavía no
    existen en la base**: sus migraciones están sin aplicar.
  - `min_history_days = 20` en la base; la 53 (sin aplicar) lo baja a **10** y
    abre al canal las cinco tiendas que no publicaban.
  - El canal publica 22-25 por día contra una cuota de 33. **Los 8-11 lugares que
    sobran no los limita el detector**: son `MAX_PER_CATEGORY_PER_DAY = 3` y
    categorías sin candidatos maduros. Medido el 7-nov: Vestuario 0 de 5,
    Belleza 0 de 3, S.Mercado 3 de 5, Viajes 0 de 1.
  - 🔴 **Reiniciar servicios y aplicar migraciones es acción del dueño.** Lo pidió
    explícitamente. No lo hagas ni "para probar".

TU TRABAJO

1. **LA TERNA SALESFORCE — `tricot.cl` y `abc.cl`, migración 54.** Es el mejor
   retorno que queda: un `salesforce_family.py` cubre las dos más Hites, que hoy
   tiene adaptador propio de 4,5 KB. Y alimenta **Vestuario**, que es el tema con
   más lugares vacíos (0 de 5 ayer).
   Lo medido está en `INVESTIGACION_ropa.md` §2 y ya trae las trampas:
     - las tres paginan con **`?start=N&sz=M` sobre la URL de categoría limpia**,
       y eso está permitido; lo que cada `robots.txt` prohíbe es **otra ruta al
       mismo dato** (`/on/demandware.store/*` y `*cgid=*` en ABC,
       `*Search-UpdateGrid*` en Hites, `/search*` en Tricot);
     - **el `data-pid` está en distinto lugar en cada una**: en Hites el selector
       correcto es `.product-tile` porque `[data-pid]` mete carruseles de
       recomendados (108 contra 36); **ABC repite el `data-pid` tres veces por
       tile** (108 pids para 36 productos) ⇒ deduplicar por pid, no contar nodos;
     - ⚠️ **ABC cotiza por zona de inventario** (`zone=inventory_LaPolar_...`,
       Metropolitana por default). Es el caso Construmart: fijala explícita en el
       adaptador y documentá que **cambiarla invalida el histórico entero**;
     - el adaptador de Hites **filtra vendedores marketplace**
       (`.marketplace-info-plp b` == `hites`). Si Tricot o ABC tienen 3P, un
       precio sin filtrar no es de la tienda. Medilo antes de guardar nada.
   De las doce preguntas te faltan **GTIN, `price_normal`, stock, centinelas y
   llaves disjuntas** por tienda. Sin esas cinco no se escribe la migración.

2. **IMPERIAL — re-medir, porque un 403 tiene fecha.** Tu propia ficha del 6-nov
   dice 403 en 6 de 6 intentos, y el 5-nov hubo 11 precios en una respuesta y
   luego 520. Eso es inestabilidad de origen, no bloqueo — y es `occ_family`,
   una familia nueva. Si da una ventana estable, es una familia que no existe y
   vale más que una tienda.

3. **SPACESTORE — está en "investigada" y le falta el recorrido.** Shopify en el
   ápex, una página JSON entrega precios y stock. Falta recorrer el catálogo,
   elegir llaves disjuntas sobre SKUs reales y mapearlas. Es trabajo mecánico
   sobre una fuente ya comprobada.

4. **KLIPER: no la conectes**, aunque `magento_html:KliperAdapter` ya exista.
   706 requests / 35,7 min dejan la pasada en ~114 de los 120 min de
   `PASS_WINDOW` —número de un handoff viejo, **re-medilo antes de citarlo**— y
   Kliper es el distribuidor de `thenorthface`, `mammut`, `marmot` y `andesgear`,
   que están **las cuatro conectadas**. Es el mismo catálogo por quinta vez y la
   misma oferta dos veces al canal. Decisión del dueño, no tuya.

NÚMEROS DE MIGRACIÓN
La **54** es la primera libre. Verificalo igual, con esto y no con `ls` de tu
árbol:

    for d in ~/servicios/ofertoon*; do
      find "$d/migrations" -maxdepth 1 -name '*.sql' -printf '%f\n' 2>/dev/null
    done | grep -oE '^[0-9]+' | sort -n | tail -1

Repartidas: 47 unimarc, 50 rockford, 51 mercadopago, 52 sparta, 53 piso de 10.
La 49 nunca se escribió y queda muerta.

QUÉ NO TOCAR
  - `subscriptions/` entero, `migrations/51` → del agente de MercadoPago.
  - `migrations/53` y la regla 5 de CLAUDE.md → de la rama `feat/piso-diez`.
  - En los `.md` compartidos: **agregá, nunca reordenes**.

CÓMO SE TRABAJA ACÁ
  - **Verificá el efecto, nunca el mensaje.** `listo — 0 migración(es)
    aplicada(s)` es a la vez el mensaje de una corrida sana y el de "tu migración
    no está en esta imagen".
  - **Una prueba sin caso de control es un falso verde.**
  - **Las `store_categories` no las verifica ningún test** (el `_truncate_state`
    del conftest las trunca). Se miran en la base, o aplicando la secuencia
    completa sobre una base descartable propia.
  - **Un pytest a la vez por base**, y avisá antes de una corrida larga: hay tres
    agentes sobre el mismo Postgres `:5436`, que además sirve producción.
  - **No commitees ni pushees salvo que te lo pidan.**
  - **Avisá cualquier decisión que tomes por tu cuenta.** Honestidad 100%: si
    algo falla, decilo con el output.
```
