# Ejemplo: criterios de aceptación con un oráculo exacto

Este ejemplo existe por **el criterio**, no por la tarea.

## Lo que demuestra

`criteria.json` contiene el mejor criterio de aceptación de todo el proyecto:

```python
assert Operator(prepare_state()).equiv(Operator(ref))   # sigue siendo el mismo unitario
assert qc.count_ops().get("cx", 0) <= 1                 # y usa menos compuertas
```

Es **doble** y **exacto**: correctitud (equivalencia unitaria, matemáticamente
decidible) más mejora (conteo de compuertas). Ninguna de las dos mitades admite
opinión, y un stub no puede satisfacerlas. Es exactamente la forma que
`AUTONOMY.md` argumenta que necesita la autonomía.

Corrida real (`gemma-4-26b-a4b-it`):

```
2/2 pasos, 1 ronda, 3 llamadas, 26 s
cx: 3 -> 1     x: 2 -> 0     profundidad: 6 -> 3     unitario idéntico
```

## Lo que NO demuestra, y conviene decirlo

**El transpilador de Qiskit hace exactamente lo mismo en 17 ms:**

```python
transpile(qc, optimization_level=3)   # cx 3->1, x 2->0, 17 ms, demostrable
```

El crew tardó **26 segundos y 3 llamadas al modelo** para llegar al mismo sitio
que una herramienta determinista y madura resuelve mil veces más rápido y con
garantías que un LLM no da.

Así que esto **no** es un argumento para optimizar circuitos con un agente. Si
el problema tiene un algoritmo, usa el algoritmo.

## La lección que sí vale

Lo interesante del software cuántico para este proyecto no es que necesite
agentes — es que tiene **oráculos inusualmente buenos**: equivalencia unitaria,
simulación de estabilizadores, tests de respuesta conocida. `AUTONOMY.md`
sostiene que la autonomía está limitada por la densidad de señal verificable, no
por la inteligencia del modelo. Un dominio rico en oráculos es donde esa tesis
se puede poner a prueba en serio.

El valor está en **prestar el oráculo**, no en sustituir al transpilador.

## Cómo correrlo

```bash
cp -r examples/quantum-circuit-opt /tmp/qopt
cd /tmp/qopt && git init -q && git add -A && git commit -qm base
python -m nanoloop.main run "Remove the redundant gates from prepare_state" \
    --workspace /tmp/qopt --accept /tmp/qopt/criteria.json --max-calls 12
```

Requiere `qiskit` en el entorno que corre los gates.
