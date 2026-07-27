# Próximos pasos

Estado al cerrar la sesión del **2026-07-27**. Escrito para que alguien (o yo
mismo) pueda retomar en frío sin releer todo el historial.

Lecturas por orden: `README.md` → `GAPS.md` (qué falta, medido) →
`IMPLEMENTATION.md` §0a (hallazgos F1–F10) → `PLAN.md` (decisiones D1–D8).

---

## Dónde quedó

**205 tests verdes**, `ruff` limpio, 15 commits en `main`, publicado en
`EvolvingAgentsLabs/gemma4nanoloop`.

Cerrados esta sesión: los tres huecos que bloqueaban dar una tarea real.

| | |
|---|---|
| ~~G1~~ | criterios de aceptación **ejecutables**, y escribibles por ti (`--accept`) |
| ~~G2~~ | slice **centrado en el símbolo** (ficheros grandes editables) |
| ~~G7~~ | **preflight**: no arranca en un repo ya roto |

Más: replan acotado sobre criterios incumplidos, skills invocables desde el plan
(coste 0 llamadas), creación de ficheros con prompt y esquema propios.

---

## Lo siguiente, por prioridad

### 1. G3 — estabilizar el planner  🟠 el que más ruido quita

**Síntoma medido:** el mismo objetivo produjo **1, 2, 4 y 5 pasos** en corridas
distintas, y en una emitió dos pasos idénticos. Un plan mal descompuesto no lo
arregla el replan: gasta llamadas y multiplica las ocasiones de fallar.

**Qué hacer**
1. Deduplicar pasos por `(target_file, defines)` antes de ejecutar. Determinista,
   barato, y ataca el caso observado directamente.
2. Añadir al eval una medida de **varianza**: 10 corridas del mismo objetivo,
   reportar la distribución del nº de pasos. Hoy no existe y por eso la
   inestabilidad solo se ve por accidente.

**Dónde:** `crew.run_plan` (dedup), `eval/run_plans.py` (varianza).

### 2. G4 — generación de ficheros nuevos  🟠

Editar con anclajes: ~100%. Escribir un fichero entero: sigue fallando, incluso
con el 26B. Ya tiene prompt propio, esquema `NewFile`, `ast.parse` previo y
`autofix`; aun así es donde se concentran las reparaciones.

**Qué hacer:** medirlo de verdad — un `eval/run_newfiles.py` análogo a
`run_anchors.py`, con N fixtures que exijan crear un módulo, reportando
válido/inválido. Sin ese número se está optimizando a ciegas.

**Alternativa que ya funciona:** cubrir con **skills** todo lo que sea plantilla.
El scaffold de FastAPI salió 3/3 con **0 llamadas al modelo**. Cada plantilla que
se convierte en skill es una clase de fallo que desaparece.

### 3. G5 — repo map filtrado por relevancia  🟡

~3.260 tok en este repo, crece lineal, `max_files=300` y corta. El planner no
necesita ver todo el repo sino lo relevante al objetivo.

**Qué hacer:** filtrar por coincidencia léxica con el objetivo antes de mandarlo.
Si se queda corto, `recall.py` ya tiene EmbeddingGemma montado.

### 4. G6 — visión entre ficheros  🟡 estructural

Cada paso ve UN fichero (D6, deliberado). Un cambio de firma que rompe otro
módulo solo se detecta si los tests ya lo cubren.

**No ampliar el contexto** — es el anti-patrón de PLAN.md §6. Lo tratable: el
preflight ya exige que el repo arranque verde; el siguiente escalón sería avisar
cuando el objetivo toca un símbolo con referencias en otros ficheros (grep sobre
el índice de `repomap`), aunque sea solo para informar al humano.

### 5. Deuda de PLAN.md que sigue sin tocarse

- **Soak térmico (Phase 4)**: nunca corrido. Es *la* pregunta abierta del
  hardware. Correr 30+ pasos **en frío** y graficar latencia vs índice de paso;
  `eval/report.py` ya dibuja la curva. Señal blanda ya observada: p50 subió de
  17,5 s a 29,8 s sobre los mismos fixtures tras un día de carga.
- **Anchor-hit con ≥50 fixtures**: hoy son 12 (100%). PLAN.md pide 50, y un repo
  de 5 ficheros es donde los anclajes son más fáciles.
- **LiteRT-LM**: instalado pero nunca sirvió. PLAN.md §7 Q2 sigue contestada solo
  para Ollama.
- **`num_ctx` sin verificar de verdad**: el comando `verify-ctx` existe pero la
  comprobación en los logs del servidor no se hizo.
- **30 queries de recall** (hoy 10) contra un corpus mayor; el actual lo escribí
  yo, así que query y documento comparten autor y eso favorece el resultado.

---

## Trampas que ya costaron horas — no repetir

1. **Gemma 4 razona y `/v1` no lo puede apagar.** 222 s vs 27 s en el endpoint
   nativo, con `content` llegando vacío. Si vuelve a aparecer latencia rara,
   mirar `thinking_chars` en `calls.jsonl` **antes** que nada.
2. **Pydantic quita del `required` del schema todo campo con `default=`**, y el
   decodificado restringido lo trata como opcional: el modelo no lo emite. Dejó
   `Step.defines` y `Plan.acceptance` inertes — parecían funcionar y no podían
   fallar jamás. `schema_of()` fuerza `required`; no deshacer.
3. **El razonamiento comparte el presupuesto de salida.** Un cap pequeño se gasta
   pensando y devuelve vacío con `completion_tokens: 0`. Ver `PHASE_MAX_TOKENS`.
4. **Gates verdes ≠ objetivo cumplido.** Por eso existen `Step.defines` y
   `Plan.acceptance` con `check` ejecutable. Un símbolo que existe no prueba nada.
5. **Un error del harness es indistinguible de un mal edit** para el loop de
   reparación. De ahí el preflight.

---

## Antes de retomar

```bash
source ./env.sh                 # config de Ollama; reiniciar `ollama serve`
uv pip install -e ".[dev]"
python -m pytest -q             # deben salir 205
```

Backends: `NANOLOOP_BACKEND=ollama` (12B local, ~30 s/llamada) o `aistudio`
(26B, ~4 s/llamada, key en `.env`). El A/B midió **la misma calidad de
anchor-hit** en ambos, así que el cloud es para iterar rápido — **toda medición
de aceptación debe cerrarse contra el 12B local**, que es el objetivo real.

⚠️ **La key de AI Studio quedó expuesta en el historial del chat de esta sesión.**
Nunca entró en ningún commit (verificado sobre todo el historial), pero conviene
rotarla: https://aistudio.google.com/apikey
