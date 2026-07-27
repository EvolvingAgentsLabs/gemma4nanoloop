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

## G2. Ficheros grandes: el anchor es inalcanzable — 🔴 bloqueante en repos reales

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

Sin esto el crew no puede editar ni su propio `crew.py`.

---

## G3. El planner es inestable entre corridas — 🟠 serio

Mismo objetivo, mismo modelo, cuatro corridas: **1, 2, 4 y 5 pasos**. Y en una de
ellas emitió dos pasos idénticos ("Add tests… tests/test_tags.py" duplicado).

El replan compensa el caso "faltó algo", pero no el caso "el plan estaba mal
descompuesto". Un plan de 5 pasos donde 2 son redundantes gasta llamadas y
multiplica las ocasiones de fallar.

**Qué haría:** deduplicar pasos por `(target_file, defines)` antes de ejecutar —
determinista y barato. Y medir la varianza: 10 corridas del mismo objetivo,
reportar la distribución de nº de pasos. Ahora mismo no está en el eval.

---

## G4. Crear ficheros nuevos sigue siendo el punto débil — 🟠 serio

Editar con anclajes: ~100%. Escribir un fichero entero: falla repetidamente,
incluso con el 26B. Ya mejoró mucho (prompt y esquema propios, `ast.parse` antes
de escribir, `autofix`), pero es donde se concentran las reparaciones.

Es exactamente lo que D4 predice, y la razón de que los anclajes existan. La
implicación práctica: **las tareas que requieren módulos nuevos son más frágiles
que las que extienden código existente**. Las skills lo esquivan cuando aplican
(el FastAPI salió en 3/3 con 0 llamadas) — por eso conviene cubrir con skills
todo lo que sea plantilla.

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

## G7. Supuestos del entorno — 🟡 fácil, pero hay que hacerlo

- Los gates asumen `ruff` + `pytest` configurados. En un repo sin ellos, el primer
  gate falla y el loop gasta reparaciones en algo que ningún edit arregla — ya nos
  pasó con `ruff: command not found`.
- El crew **no puede instalar dependencias**. Si la tarea necesita una librería
  nueva, no hay camino.
- `DEFAULT_GATES` está cableado a Python. Otro lenguaje = otra configuración.

**Qué haría:** un `preflight` que verifique gates verdes en el repo destino antes
del primer plan, y falle claro si no. Barato y evita una clase entera de ruido.

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
