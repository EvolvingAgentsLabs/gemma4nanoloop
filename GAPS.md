# Qué falta para una tarea real

Análisis medido, no especulado. Cada hueco lleva la evidencia que lo demuestra y
lo que costaría cerrarlo. Ordenados por lo que más te va a doler primero.

Contexto: el loop **funciona** — plan → pasos → gates → verificación → replan,
177 tests, tareas reales resueltas de punta a punta. Lo de abajo es lo que separa
"resuelve tareas de juguete de forma fiable" de "le doy una tarea real".

---

## ~~G1~~. La aceptación comprueba que EXISTE, no que FUNCIONA — ✅ CERRADO

Es el hueco más grande y el más fácil de pasar por alto, porque todo sale verde.

```python
class Store:
    def by_tag(self, tag):
        return []  # stub: siempre vacío
```
```
criterio `by_tag` sobre ese stub  ->  CUMPLIDO
```

`defines_symbol()` pregunta *"¿existe este nombre?"*. Un stub, un `pass`, o una
implementación al revés pasan igual. Los gates tampoco lo salvan: `ruff` no juzga
semántica y `pytest` solo ejecuta los tests que YA existen — si la función es
nueva, no hay test que la cubra.

Encadenado con el replan esto es peor, no mejor: el replan da por satisfecho un
criterio en cuanto aparece el símbolo, así que deja de insistir justo cuando el
código está vacío.

**Qué haría:** que `Acceptance` deje de ser un nombre y pase a ser una
**aserción ejecutable** — un fragmento de pytest que el grafo corre:

```python
class Acceptance(BaseModel):
    test: str  # "s = Store(); s.add('a', ['x']); assert s.by_tag('x')"
    file: str
```

Determinista, sin opinión del modelo, y encaja con D3. Y para una tarea real de
verdad: **los criterios los escribes tú**, no el planner. El modelo demostró que
inventa criterios (`text_item`) y que olvida otros; el objetivo y su definición
de "hecho" son justo lo que no conviene delegar.

**HECHO.** `Acceptance.check` es ahora Python ejecutable que el grafo corre desde
la raíz del repo, con timeout y borrando la sonda después. El mismo stub:

```
solo nombre : CUMPLIDO            <- el hueco
con check   : `by_tag` exists but its check failed: AssertionError
```

Y `--accept criterios.json` deja que **los escribas tú**, ignorando los del
planner — verificado de punta a punta: mis dos criterios sobrevivieron el replan
y forzaron una segunda ronda hasta cumplirse (5/5 pasos, 2 rondas, 6 llamadas).

`NANOLOOP_REQUIRE_CHECKS=1` trata como incumplido cualquier criterio sin check,
para que una corrida no pueda parecer más fuerte de lo que es.

---

## ~~G2~~. Ficheros grandes: el anchor es inalcanzable — ✅ CERRADO

```
nanoloop/crew.py   29.735 chars -> slice de 12.018 (truncado por cabeza)
¿el 25% final visible para anclar?  NO
```

`_read_slice` corta a 12.000 chars conservando la CABEZA. Todo anchor que viva en
la cola del fichero es literalmente inalcanzable: el modelo no puede copiar texto
que no ha visto, y el fallo aparece como `not_found` repetido — indistinguible de
"el modelo no sabe copiar".

En un repo real esto no es un caso raro:

```
muestra de pydantic (105 ficheros)
  42% exceden la mitad del presupuesto de build
  _generate_schema.py  ~34.087 tok   (4x la ventana COMPLETA de 8.192)
  json_schema.py       ~31.488 tok
  types.py             ~26.490 tok
```

**Qué haría, por orden:**
1. **Ventana centrada en la región relevante** en vez de la cabeza: localizar por
   símbolo (ya tenemos el índice de `repomap._symbols`) y mandar esa función ±N
   líneas. Es el cambio de mayor impacto y no toca la arquitectura.
2. Numerar las líneas del slice para que el modelo ancle por posición.
3. Subir `PHASE_NUM_CTX["build"]` solo si hace falta — cuesta latencia en local.

**HECHO.** `_read_slice` ya no trunca por la cabeza. Localiza con `ast` la
definición de la que trata el paso (pistas: `defines`, luego `title`/`intent`) y
manda una ventana centrada en ella, creciendo hacia fuera hasta llenar el
presupuesto. Si ningún símbolo casa, manda **cabeza Y cola** — añadir al final es
lo más común y la cola es donde se ancla.

Sobre el propio `crew.py` (36.041 chars, 937 líneas):

```
símbolo            línea   antes           ahora
run_goal            868    INALCANZABLE    visible
verify_plan         785    INALCANZABLE    visible
run_check           751    INALCANZABLE    visible
```

Verificado de punta a punta contra un módulo de 22.229 chars donde `class
Registry` cae fuera de los primeros 12.000: **1 paso, 1 llamada, 0 reparaciones,
anchor `exact`**, criterio ejecutable en verde y gates verdes.

Cada región mostrada es byte a byte idéntica al fichero (hay test que lo fija) y
los huecos van anunciados — un anchor que cruzara el hueco no casaría con nada, y
el modelo tiene que poder ver que falta algo.

Nota: no numeré las líneas. Chocaría con el copiado literal del anchor, que es la
propiedad de la que depende todo lo demás.

---

## ~~G3~~. El planner es inestable entre corridas — ✅ CERRADO (y la premisa era falsa)

Mismo objetivo, mismo modelo, cuatro corridas: **1, 2, 4 y 5 pasos**. Y en una de
ellas emitió dos pasos idénticos ("Add tests… tests/test_tags.py" duplicado).

El replan compensa el caso "faltó algo", pero no el caso "el plan estaba mal
descompuesto". Un plan de 5 pasos donde 2 son redundantes gasta llamadas y
multiplica las ocasiones de fallar.

**MEDIDO, y me equivocaba.** `eval/run_variance.py`, 8 corridas del mismo
objetivo:

```
steps (raw)      median 3.0   range 3-3   sd 0.00   {3: 8}
criterios con check                       16/16 (100%)
VERDICT: stable
```

El planner es **determinista** a temperatura 0. Lo que yo tomé por varianza eran
entradas distintas: objetivos ligeramente diferentes y repos en estados
distintos. La lección: sin medir, "es inestable" era una historia que me conté.

**Pero la medición destapó un bug real y consistente**, que es lo que de verdad
causaba los replans:

```
paso 3  target_file='todo wrong/store.py'    <- 8 de 8 corridas
```

Un directorio que no existe. El paso no editaba `todo/store.py`: **creaba un
fichero fantasma**, el símbolo caía donde ningún criterio miraba, y se gastaba
una ronda de replan redescubriéndolo.

`resolve_target()` lo repara de forma determinista: si la ruta no existe y hay
**exactamente un** fichero con ese nombre, se ajusta a él; si hay ambigüedad se
deja fallar, porque un ajuste equivocado edita el fichero equivocado.

Efecto medido en vivo, mismo objetivo: **2 rondas de plan → 1**, 3/3 pasos, 3
llamadas.

También añadido `normalize_plan()`, que descarta pasos redundantes de forma
conservadora — solo con `defines` repetido o título idéntico. Dos pasos sobre el
mismo fichero sin `defines` NO se fusionan: un falso merge pierde trabajo en
silencio.

---

## ~~G4~~. Crear ficheros nuevos — ✅ MEDIDO (y era mucho menos grave)

Editar con anclajes: ~100%. Escribir un fichero entero: falla repetidamente,
incluso con el 26B. Ya mejoró mucho (prompt y esquema propios, `ast.parse` antes
de escribir, `autofix`), pero es donde se concentran las reparaciones.

**MEDIDO.** `eval/run_newfiles.py`, 16 fixtures, embudo en vez de tasa:

```
             cruda    pipeline real
parsed      100.0%       100.0%
syntax       93.8%        93.8%
lint         41.7%        93.8%   <- autofix
imports      41.7%        93.8%
defines      41.7%        93.8%
FULLY VALID  41.7%        93.8%
```

**Dos veces me equivoqué al medir, y las dos veces a la baja.**

1. La primera medición dio **41,7%** — pero medía la salida *cruda*, sin el
   `crew.autofix` que el pipeline aplica tras cada edit. Los fallos dominantes
   eran `F401 unused import` e `I001 imports sin ordenar`: **auto-corregibles**.
   Estaba culpando al modelo de algo que una herramienta arregla siempre.
2. La segunda dio **68,8%**, y todos los fallos restantes eran ficheros de test
   con el diagnóstico *"does not define test_X"*. Mirando lo que escribió:

   | pedido | escribió |
   |---|---|
   | `test_pending_empty` | `test_store_pending_is_empty_on_new_store` |
   | `test_all_returns_both` | `test_all_returns_two_items_after_adding_two` |

   Tests **válidos, importables y mejor nombrados que los que pedí**. El que
   fallaba era mi verificador: en un módulo de test el nombre exacto no es el
   requisito, que exista un test lo es. `defines_symbol` ahora acepta cualquier
   `test_*` en un módulo de test — y solo ahí; fuera, el nombre sigue siendo el
   contrato (`by_tag` ≠ `by_label`).

**Resultado real: 15/16 = 93,8%.** Un único fallo genuino en 16 (un error de
indentación). Frente al ~100% de los edits con anclaje, la brecha existe pero es
mucho menor de lo que aparentaba — y el `--raw` del harness deja ver cuánto de
eso lo aporta la herramienta y no el modelo.

Sigue valiendo: cubrir con **skills** todo lo que sea plantilla (el FastAPI salió
3/3 con 0 llamadas). Pero "crear ficheros nuevos es el punto débil" era, en
buena medida, un artefacto de cómo lo estaba midiendo.

---

## G5. El repo map no escala — 🟡 lo notarás pronto

```
este repo: 129 líneas, ~3.260 tok  (presupuesto plan: 16.384)
```

Cómodo aquí, pero crece lineal y sin ningún filtro: `max_files=300` y corta. Un
repo de 2.000 ficheros ni entra ni tendría sentido — el planner no necesita ver
todo el repo, necesita ver **lo relevante al objetivo**.

**Qué haría:** filtrar el map por relevancia al objetivo antes de mandarlo
(coincidencia léxica basta para empezar; ya tenemos EmbeddingGemma si hace falta
algo mejor). Nótese que el índice de símbolos que añadimos ya es lo que hace el
map útil — sin él el planner mandaba edits a `__init__.py`.

---

## G6. Nadie mira dos ficheros a la vez — 🟡 estructural

Cada paso ve UN fichero (D6, y es deliberado). Consecuencia: un cambio en
`store.py` que rompe `format.py` solo se detecta si los tests ya lo cubren. En un
repo real, un cambio de firma se propaga y el crew no lo ve venir.

Los gates son la red, y son buena red — pero solo tan buena como la suite de
tests del repo destino. **En un repo con poca cobertura, el crew avanza a ciegas.**

No lo "arreglaría" ampliando el contexto (eso es el anti-patrón de §6 de PLAN.md).
Lo tratable es: exigir que el repo destino tenga tests que pasen ANTES de empezar,
y abortar si no.

---

## ~~G7~~. Supuestos del entorno — ✅ CERRADO (parcialmente)

- Los gates asumen `ruff` + `pytest` configurados. En un repo sin ellos, el primer
  gate falla y el loop gasta reparaciones en algo que ningún edit arregla — ya nos
  pasó con `ruff: command not found`.
- El crew **no puede instalar dependencias**. Si la tarea necesita una librería
  nueva, no hay camino.
- `DEFAULT_GATES` está cableado a Python. Otro lenguaje = otra configuración.

**HECHO** lo principal. `crew.preflight()` corre antes del primer plan y se niega
a empezar si el repo ya está roto, distinguiendo dos causas que necesitan
respuestas distintas:

```
tool ausente -> tooling not on PATH: eslint. Install it in the environment...
repo rojo    -> the repo does not pass its own gates before any change
```

Y **no** bloquea dos casos que son legítimos: workspace vacío (scaffolding desde
cero — la demo de FastAPI empieza justo ahí) y repos sin Python.

Verificado con el CLI:

```
repo con un test roto     -> exit 3, 0 llamadas al modelo
workspace vacío           -> skipped, sigue y scaffoldea (0 llamadas, skill)
```

Lo de las **0 llamadas** es el punto: antes ese repo habría gastado reparaciones
peleando con un fallo que ningún edit suyo podía arreglar.

`--skip-preflight` para saltarlo a sabiendas.

**Sigue pendiente de G7:** el crew no puede instalar dependencias, y
`DEFAULT_GATES` sigue cableado a Python.

---

## G8. Cosas menores pero que muerden

- **Sin resume.** Una corrida interrumpida deja el workspace a medias. El snapshot
  protege por candidato, no por sesión.
- **Latencia local**: ~30 s/llamada en el 12B, y vimos p50 subir de 17,5 s a
  29,8 s tras un día de carga. El soak térmico de 30 pasos sigue sin correrse.
- **Coste cloud sin límite**: no hay tope de gasto ni de llamadas por objetivo.
- **`num_ctx` sigue sin verificarse** de verdad contra el servidor (Phase 0 #1
  quedó a medias: el comando existe, la comprobación en logs no se hizo).

---

## Lo que yo haría, en orden

| # | Hueco | Esfuerzo | Desbloquea |
|---|---|---|---|
| 1 | **G1** criterios ejecutables (y escritos por ti) | bajo | que "verde" signifique algo |
| 2 | **G2** slice centrado en el símbolo | medio | editar ficheros reales |
| 3 | **G7** preflight de gates | bajo | no pelear con el entorno |
| 4 | **G3** dedup de pasos + medir varianza | bajo | planes estables |
| 5 | **G5** repo map filtrado por relevancia | medio | repos grandes |

Con **1 + 2 + 7** yo ya le daría una tarea real acotada en un repo con tests
decentes. Sin G1, "todo verde" no te dice nada, y sin G2 no puede tocar la mitad
de los ficheros de un repo normal.

## Qué tarea le daría HOY, tal cual está

Funciona bien, sin supervisión, si se cumple todo esto:

- repo Python con `ruff` + `pytest` ya configurados y **verdes de partida**
- ficheros objetivo por debajo de ~10.000 chars
- extender código existente (añadir método, parámetro, endpoint), no diseñar
  módulos nuevos
- objetivo que nombre explícitamente lo que debe existir (alimenta la aceptación)
- **tú revisas el diff** — la aceptación te dice que está, no que esté bien

Fuera de eso todavía necesita a alguien mirando.
