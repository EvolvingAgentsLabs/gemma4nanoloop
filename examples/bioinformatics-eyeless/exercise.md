# El ejercicio: dáselo al crew

`conserved.py` viene arreglado para que `discover.py` funcione de entrada. Para
convertirlo en una tarea, reintroduce el bug canónico de la bioinformática —
devolver coordenadas 0-based donde la documentación promete 1-based:

```diff
-                "query_start": qs + 1,
+                "query_start": qs,
-                "subject_start": ss + 1,
+                "subject_start": ss,
```

Ahora `tests/test_conserved.py` falla, y el repo tiene una tarea con su propio
oráculo. No hace falta que escribas ni el objetivo ni el criterio:

```bash
cp -r examples/bioinformatics-eyeless /tmp/bio
cd /tmp/bio && git init -q && git add -A && git commit -qm base
python -m nanoloop.main harvest --workspace /tmp/bio --run --deliver
```

Resultado real con `gemma4:12b` **local**:

```
[harvest] 1 task from the repo
  1. [pytest] Make the failing test ...::test_paired_domain_is_found pass
     fix in:   conserved.py        <- el código, no el test
     oracle:   1 executable criterion
=== task 1: SOLVED ===   3 pasos, 3 llamadas
```

## Una observación honesta sobre ese arreglo

El 12B corrigió el off-by-one **y además añadió una rama de fusión de bloques
que nadie había pedido**. Los tests pasan, pero esa rama mezcla coordenadas
1-based con 0-based: tiene un bug latente en un camino que los tests no
recorren.

Es un recordatorio útil de algo que este proyecto repite: **los gates prueban lo
que los tests cubren, ni un milímetro más.** Un criterio ejecutable te dice que
la función hace lo que pediste; no te dice que el código que la rodea sea bueno.
Revisa el diff.
