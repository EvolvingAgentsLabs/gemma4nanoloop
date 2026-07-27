# Bucle evolutivo estilo AlphaEvolve

`propose N → puntúa todos → quédate con el mejor → repite`, con un evaluador
determinista. No es lo que hace el crew, y esa es la gracia.

| | |
|---|---|
| **crew** | propone → el primer candidato que **pasa** gana → para. Optimiza para *correcto*. |
| **este bucle** | propone N → **puntúa** todos → se queda con el mejor → itera. Optimiza para *mejor sujeto a correcto*. |

El crew ya tiene best-of-N, pero toma la primera muestra que supera el gate:
para un bug, "correcto" **es** todo el requisito. La optimización no tiene ese
punto de parada — todo candidato correcto sigue siendo comparable con los demás,
y parar en el primero tira la búsqueda a la basura.

El evaluador es la misma idea que `Acceptance.check`, partida en dos:

```python
valid = Operator(candidate).equiv(Operator(reference))  # gate duro
score = sum(qc.count_ops().values())  # gradiente
```

Un candidato inválido puntúa cero por corto que sea. Si no, el bucle aprende que
borrar el circuito es una optimización excelente.

## Resultado

```
original    10 compuertas, profundidad 8
transpiler   3 compuertas, profundidad 3   <- el listón
evolucionado 3 compuertas   en 3 llamadas y 9 s   -> IGUALA al transpilador
```

Encontró la reducción que **requiere conmutación**, no solo cancelación de
adyacentes: los dos `rz` estaban separados por un `cx`, y solo se pueden fusionar
en `rz(0.7)` si sabes que un `rz` sobre el qubit de control conmuta a través del
`cx`.

```python
qc.h(0)
qc.rz(0.7, 0)
qc.cx(0, 1)  # 0.3 + 0.4 = 0.7
```

Unitario idéntico, verificado aparte.

## El fallo que más enseña

La primera corrida dio **0/9 candidatos válidos**. El modelo generaba basura:

```python
qc.h(qubit_0_index_placeholder_for_logic_only_to_be_replaced_by__real_indices_0_and_1)
qc.cx(0, 0_placeholder_for_logic_only_to_be_redistributed-0_and_1)
```

Era **mi prompt**, no el modelo. Decía *"return the complete new body of build()
as a Python module"* — ambiguo entre "el cuerpo" y "el módulo". Reescrito a
*"output one complete Python file... every qubit index is a literal integer:
0 or 1. Never write a placeholder name where a number belongs"*, funcionó a la
primera.

**0/9 → 2/3 candidatos válidos por un cambio de redacción.** Antes de concluir
que un modelo pequeño no puede con una tarea, hay que descartar que el prompt sea
el que no puede.

## Y aun así: el transpilador sigue ganando

`transpile(optimization_level=3)` da el mismo resultado en **12 ms** con
garantías. El bucle tardó 9 s. Esto **no** es una recomendación para optimizar
circuitos con un agente.

Lo que sí demuestra es que **el patrón evolutivo funciona con un oráculo exacto**,
y ese patrón se aplica allí donde *no* hay un transpilador: heurísticas sin
algoritmo conocido, código que hay que hacer rápido sin cambiar su semántica,
ajuste de parámetros con una métrica medible. El circuito cuántico es el banco de
pruebas, no el caso de uso.

## Llevado al crew: `--optimize`

El patrón ya no vive solo en este script. `nanoloop run --optimize FILE` acepta
un fichero que define `score(workspace) -> float | None` (**menor es mejor**) y
cambia la estrategia del bucle:

```
sin scorer   primer candidato que pasa -> para        (1 llamada típica)
con scorer   puntúa los N, se queda con el mejor      (siempre N llamadas)
```

Dos cosas que hubo que aprender construyéndolo, ambas descubiertas ejecutando:

1. **Exige snapshot.** Sin árbol limpio por candidato, el candidato 2 ve el edit
   del 1, su anchor ya no casa, y la población colapsa en una cadena que se
   acumula. Ahora falla con un mensaje que lo dice, en vez de comportarse raro.
2. **Necesita conocer al titular.** La primera versión elegía el mejor
   *candidato* y cantaba victoria aunque ninguno mejorase el punto de partida —
   una corrida reportó `1/1 steps solved` habiendo ido de 10 compuertas a 10.
   Una optimización que no optimiza es un fallo, no un éxito plano. Ahora se
   mide el baseline antes y un candidato que no lo bate no gana.

## 12B local vs 26B cloud: la primera vez que el tamaño importa

Corrido de punta a punta con `run --optimize` contra los dos backends:

| modelo | resultado | óptimo |
|---|---|---|
| `gemma-4-26b` (cloud) | **10 → 3** compuertas, iguala al transpilador | 3 |
| `gemma4:12b` (local) | **9 → 7**, luego se planta | 3 |

El 12B quitó los `h` redundantes y dejó intactos `cx×3` y `x×2`. Correcto —el
unitario se conserva— pero incompleto. Repetido dos veces más, ningún candidato
mejoró sobre 7 y el paso falló, que es el baseline haciendo su trabajo en vez de
reportar un éxito plano.

**Esto importa más allá del ejemplo.** En todo el resto del proyecto el 12B y el
26B empataron: anchor-hit 100% los dos, y el A/B concluyó que un modelo mayor no
compraba calidad. La optimización es **el primer sitio donde el tamaño del modelo
se mide de verdad**. Tiene sentido: buscar en un espacio de reescrituras es otra
tarea que aplicar una regla nombrada a un error nombrado.

## Nota sobre el backend

Las corridas contra AI Studio se degradaron tras un día de uso: ~180 s por
llamada y respuestas vacías, cuando por la mañana tardaban 4 s. El `probe`
seguía respondiendo, así que era throttling, no caída. El 12B local no tiene ese
problema y es el objetivo real del proyecto.

## Correrlo

```bash
python examples/quantum-evolve/evolve.py --generations 3 --candidates 3
```

Requiere `qiskit`. Escribe el mejor candidato en `best.py`.
