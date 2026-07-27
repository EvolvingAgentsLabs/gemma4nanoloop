# Cómo llegar a "crew autónomo" que haga algo real

No es una hoja de ruta de features. Es una tesis, sacada de lo que rompió de
verdad en este proyecto, y lo que se sigue de ella.

---

## La observación que lo cambia todo

Lleva la cuenta de lo que falló en toda la sesión:

| causa | casos |
|---|---|
| **runtime / harness** | razonamiento en `/v1` (8×), gates sin venv en PATH, cap de tokens ahogando el plan, repo map sin símbolos, rutas rotas del planner |
| **verificación mal diseñada** | schema con campos opcionales → dos mecanismos inertes; gates verdes ≠ objetivo hecho; recall@5 saturado; criterios que solo miran existencia |
| **capacidad del modelo** | generar ficheros enteros. Y poco más. |

Y el A/B lo confirmó: **12B y 26B empatan al 100%** en anchor-hit. Un modelo el
doble de grande no arregló nada — y habría *tapado* el bug del repo map.

**Tesis: la autonomía no está limitada por la inteligencia del modelo, sino por
la densidad de señal verificable que le rodea.** Cada vez que convertimos una
opinión en una comprobación determinista, el 12B se volvió competente. Cada vez
que dejamos un hueco sin verificar, el sistema mintió en verde.

Corolario incómodo: **invertir en prompts o en modelos más grandes es la
inversión de peor retorno aquí.** Lo que paga es construir oráculos.

---

## El cuello de botella real: de dónde salen las tareas

Hoy el crew necesita que un humano escriba (a) el objetivo y (b) los criterios de
aceptación. Eso no es un crew autónomo; es un ejecutor con supervisión.

Y hay una razón por la que no podemos delegar (b) en el modelo: **ya lo medimos**
— inventa criterios (`text_item`) y olvida otros. La definición de "hecho" es
justo lo que peor delega.

Aquí está el giro:

> **Un repo real ya está lleno de tareas que vienen con su criterio de aceptación
> incorporado. No hace falta que nadie las escriba.**

Un test que falla **es** una especificación completa:

| lo que necesita el crew | lo que da un test que falla |
|---|---|
| objetivo | "haz que este test pase" |
| criterio de aceptación ejecutable | **el propio test** |
| localización | el traceback dice el fichero y la línea |
| verificación | `pytest` ya lo dice, sin opinión |

Eso elimina de un golpe los dos eslabones más débiles que medimos. Y no es solo
tests. Todas estas fuentes traen su propio oráculo:

| fuente | oráculo | comentario |
|---|---|---|
| test que falla | el test | el caso perfecto |
| `mypy` error | `mypy` | localizado, verificable, abundante |
| `ruff` no auto-fixable | `ruff` | ya tenemos autofix para el resto |
| `TODO`/`FIXME` | ninguno ⚠️ | necesita criterio humano; peor candidato |
| hueco de cobertura | el test que escribes | invierte el problema: la tarea *es* escribir el test |
| dependencia desactualizada | la suite entera | riesgo alto, señal clarísima |

**Primer paso concreto:** `nanoloop harvest` — corre los gates, parsea los
fallos, y emite tareas con criterio ya adjunto. El crew deja de esperar
instrucciones y empieza a leer el estado del repo.

---

## La segunda pieza: el entregable debe ser un PR, no un directorio

Ahora mismo el crew muta un workspace. Eso obliga al humano a estar delante.

Si el entregable es **una rama + commits + una descripción de qué hizo y qué no
pudo**, el humano entra de forma asíncrona — que es lo único que hace la
autonomía a la vez útil y segura. Revisar un PR es barato; vigilar un proceso
no.

Además fuerza algo sano: el crew tiene que **explicar su trabajo**, y ya tiene
todo el material (`calls.jsonl`, criterios cumplidos/incumplidos, pasos, fixes
del plan). No hay que pedirle al modelo que lo redacte — se genera del log.

---

## La tercera: saber cuándo parar y cuándo rendirse

Un crew autónomo necesita presupuesto y necesita **rendirse bien**. Hoy solo
está acotado el replan.

- **Presupuesto por tarea** (llamadas, tokens, reloj). Al agotarse: parar y
  reportar, no seguir.
- **Rendirse es un resultado válido.** Una tarea que devuelve *"no pude, esto es
  lo que intenté, aquí está el error exacto"* vale mucho más que una que
  entrega código dudoso. Ya tenemos el hábito: los gates y el snapshot impiden
  que lo roto llegue a disco.
- **Memoria de fallos.** `memory.py` + recall semántico están montados y **el
  loop no los usa**. Un crew que falla tres veces igual debería recordarlo:
  *"esta clase de tarea no me sale"* es información de primera.

---

## Lo que NO haría

Anti-patrones que suenan a autonomía y son retrocesos:

- **Devolverle el control al modelo** (un orquestador LLM que decide qué hacer).
  Es exactamente lo que PLAN.md D1 quitó, y medimos por qué.
- **Modelos más grandes** para tapar huecos de verificación. El A/B dice que no
  compra calidad; y tapa bugs, que es peor.
- **Más contexto** para que "vea más". PLAN.md §6 lo llama anti-patrón: si un
  paso necesita más, el paso es demasiado grande.
- **Que el crew escriba sus propios criterios sin ancla.** Ya inventa. Los
  criterios vienen del repo (un test) o de un humano.
- **Autonomía sin marcha atrás.** Todo debe caber en un PR revocable.

---

## Orden que propongo

| # | Qué | Por qué |
|---|---|---|
| 1 | `harvest`: tareas desde tests/mypy que fallan | elimina los dos eslabones débiles a la vez |
| 2 | entregable = rama + PR con reporte generado del log | hace la supervisión asíncrona |
| 3 | presupuesto por tarea + rendirse como resultado | sin esto, autónomo = descontrolado |
| 4 | memoria de fallos alimentando el planner | deja de repetir el mismo error |
| 5 | G4: medir de verdad la creación de ficheros | es el único límite real *del modelo* |

Con 1+2+3 esto pasa de "ejecutor supervisado" a algo que se le puede soltar en un
repo con tests y volver a mirarlo al rato. **No porque el modelo sea más listo,
sino porque cada paso tiene un oráculo detrás.**

## La prueba honesta de que funciona

No "resolvió una tarea". Esto:

> Apuntar el crew a un repo con la suite en rojo, volver en una hora, y encontrar
> un PR que arregla un subconjunto de los fallos, con los tests como prueba, y un
> reporte explicando los que no pudo y por qué.

Ese es el listón. Todo lo de arriba existe para llegar ahí.

---

*Escrito 2026-07-27, tras cerrar G1, G2, G3 y G7. Contexto en `GAPS.md` y
`NEXT-STEPS.md`; los hallazgos medidos en `IMPLEMENTATION.md` §0a.*
