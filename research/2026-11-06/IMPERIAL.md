# Imperial: nueva comprobación del 403 (2026-11-06)

Se hicieron tres pares de consultas, con intervalos de tres segundos y el
`DEFAULT_USER_AGENT` del proyecto, la misma URL pública que el 5-nov había
entregado 11 precios una vez y luego errores 520:

https://www.imperial.cl/herramientas-de-banco/category/14341

Las seis respuestas fueron **HTTP 403**, 1.535 bytes, título «Access Denied»
y texto «You don't have permission to access … on this server». El cuerpo
incluye una referencia a `errors.edgesuite.net` (página de error de borde);
el header `Server` dice `cloudflare`, sin `cf-mitigated: challenge`. No vino
`window.state` ni un precio. El lector web independiente tampoco pudo
recuperar esta URL (timeout), lo cual por sí solo no identifica la causa.

El diagnóstico operativo hoy es **acceso denegado desde este entorno**. El 200
aislado y los 11 precios del 5-nov siguen siendo evidencia de que la tienda
publicó datos, pero no prueban que haya una fuente estable para ingesta.
Un 403 con esta página no demuestra qué regla concreta lo causa, ni autoriza
a evadirla. Mantener Imperial sin adaptador activo y buscar un feed/API
acordado o volver a medir en otra fecha.
