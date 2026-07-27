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

**HECHO.** `nanoloop harvest` corre los gates, parsea los fallos y emite tareas
con su criterio adjunto. `--run` las trabaja una a una.

Probado de punta a punta: repo con un `summarize()` que devolvía `"TODO"` y un
test que lo especificaba. Sin objetivo ni criterio escritos a mano:

```
[harvest] 1 task(s) from the repo
  1. [pytest] Make the failing test ...::test_summarize_counts pass
     fix in:   todo/store.py          <- el CÓDIGO, no el test
     oracle:   1 executable criterion
=== task 1: SOLVED ===   1/1 steps, 1 model call
```

Dos detalles que decidían si esto servía o no:

- **La tarea apunta al código bajo prueba, no al fichero de test.** Se infiere de
  los imports del test. Apuntar al test invita a editarlo hasta que pase, que es
  el único resultado que dejaría todo el ejercicio sin valor. El objetivo además
  lo dice explícito: *"Fix the code under test, not the test itself."* Verificado:
  el test quedó intacto byte a byte.
- **El preflight se salta a propósito** en `--run`. El repo ESTÁ rojo, y ese rojo
  es el trabajo; negarse a arrancar haría harvest inútil por construcción.

No se cosechan `TODO`/`FIXME`: no traen oráculo, así que el "hecho" sería opinión
del modelo — justo lo que este módulo existe para evitar.

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

**HECHO.** `--deliver` crea una rama, un commit por tarea resuelta, y
`NANOLOOP-REPORT.md` generado de los datos. `--pr` empuja y abre el PR (opt-in:
publicar es hacia fuera, no algo que hacer por defecto). Lo no resuelto va
**primero** en el reporte y **nunca se commitea**.

Probado: repo git con dos specs sin implementar, sin objetivo ni criterios
escritos a mano → **2/2 resueltas, 4 tests en verde, diff de 1 fichero**, dos
commits en `nanoloop/harvest-pytest`, `main` intacto.

Tres bugs que solo aparecieron al hacerlo de verdad:

1. **`git add -A` metía `__pycache__`** en los commits; el diff a revisar era
   mayormente bytecode.
2. **Sin gates no hay red entre tareas.** Puse `no_gates=True` porque el repo
   está rojo — y la tarea 2 deshizo la 1 reportando ambas como resueltas. La
   semántica correcta para un repo rojo no es "sin gates" sino **baseline**:
   puedes dejar los fallos que ya había, no puedes añadir nuevos.
   `harvest.regressions()` lo comprueba y revierte la tarea que regresa.
3. **La fusión de criterios entre rondas descartaba el `check`.** Reconstruía
   `Acceptance(symbol, file)` perdiendo el ejecutable, así que la verificación
   caía a "¿existe el nombre?" — y una tarea que commiteó un `summarize()` que
   devolvía un dict se reportó resuelta porque la función de test seguía
   existiendo. **La misma forma que el bug del schema: una comprobación que
   aparenta correr y no puede fallar.** Es el error que más veces ha aparecido
   en este proyecto.

Y la cascada funciona: arreglados los tests, harvest encontró acto seguido un
error de **mypy** en el código recién escrito (`list[str]` donde iba `list[Item]`)
que los tests no cazan porque en runtime da igual.

---

## La tercera: saber cuándo parar y cuándo rendirse

Un crew autónomo necesita presupuesto y necesita **rendirse bien**. Hoy solo
está acotado el replan.

- **Presupuesto por tarea** ✅ `--max-calls`, `--max-seconds`, `--max-tokens`.
  Se comprueba **antes** de cada llamada, nunca después: empezar trabajo que no
  puedes pagar desperdicia lo más caro del bucle.
- **Rendirse es un resultado válido** ✅. El reporte lo marca como
  **"stopped on budget"**, distinto de un criterio incumplido: uno le dice al
  revisor *sube el límite*, el otro *la tarea puede estar mal o ser demasiado
  difícil*.

Probado con `--max-calls 1` (imposible de cumplir): se rinde sin traceback,
**0 commits**, y el reporte explica exactamente en qué se gastó. Con
`--max-calls 10`: 1/1 resuelta.

Un bug que costó encontrar y merece recordarse: `BudgetExhausted` heredaba de
`RuntimeError`, y el retry del planner captura `RuntimeError` para fallos
transitorios. **"Deja de gastar" era indistinguible de "reinténtalo"** — el
planner quemó tres llamadas más y reportó un falso *"no valid plan in 3
attempts"*. Ahora hereda de `Exception` a secas: una excepción que significa
PARAR no puede ser capturable por un handler que significa REINTENTAR.
- **Memoria de fallos** ✅ `failmem.py`. Cada intento queda registrado
  (`solved` / `unmet` / `gave_up` + el motivo exacto) y los fallos relevantes se
  inyectan en el prompt del planner en la primera pasada.

  **Lo delicado no es guardar, es la obsolescencia.** Un fallo recordado que ya
  se arregló es *peor* que no tener memoria: le dice al planner que evite algo
  que ahora funciona, y a diferencia de una memoria ausente, una equivocada
  dirige activamente. Por eso **todo éxito posterior invalida** los fallos del
  mismo trabajo, y nada que un éxito haya contradicho vuelve a recordarse.

  Verificado en vivo: corrida 1 con `--max-calls 1` → `gave_up` registrado;
  corrida 2 con presupuesto suficiente → resuelto, 3 tests verdes; después, la
  lección desaparece por superseded.

  Un bug del camino: la huella del objetivo se comparaba por **igualdad exacta**
  de conjuntos de palabras, así que *"add by_tag to Store"* no reconocía su
  propio fallo registrado como *"implement by_tag(tag) on Store"* — una palabra
  de más y la memoria era ciega. Ahora se compara por **solapamiento**, que es lo
  que hace que una huella "lossy" sea de verdad lossy.

  Se guarda como JSONL, no como notas del grafo de conocimiento: un intento es un
  registro estructurado que se consulta por fichero exacto, no prosa para buscar
  semánticamente. `memory.py` sigue siendo el sitio de los hechos durables del
  proyecto; esto es una caja negra de vuelo.

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
| ~~1~~ | ~~`harvest`~~ ✅ **hecho** — tareas desde pytest/mypy/ruff | elimina los dos eslabones débiles a la vez |
| ~~2~~ | ~~entregable = rama + PR~~ ✅ **hecho** | hace la supervisión asíncrona |
| ~~3~~ | ~~presupuesto por tarea + rendirse~~ ✅ **hecho** | sin esto, autónomo = descontrolado |
| ~~4~~ | ~~memoria de fallos~~ ✅ **hecho** | deja de repetir el mismo error |
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
