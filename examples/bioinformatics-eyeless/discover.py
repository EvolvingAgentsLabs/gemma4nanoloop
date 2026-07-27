"""El experimento del ojo de la mosca, ejecutable en tu portátil.

    python discover.py

Reproduce el ejercicio con el que abre *Developing Bioinformatics Computer
Skills* (Gibas & Jambeck, O'Reilly 2001): descubrir, sin saber biología, que un
gen de mosca y una enfermedad humana de los ojos son la misma historia
evolutiva.

No hace falta red, ni BLAST instalado, ni cuenta en ningún sitio. Dos secuencias
públicas y un algoritmo de 1981.
"""

from __future__ import annotations

from conserved import align, conserved_blocks
from sequences import EYELESS_DROME, PAX6_HUMAN

# NCBI sitúa estos dominios en PAX6 humano. Se usan solo para ROTULAR lo que el
# alineamiento encuentra por su cuenta — no para encontrarlo.
DOMAINS = [
    (4, 136, "paired domain", "se agarra al ADN regulador"),
    (208, 267, "homeodomain", "el segundo agarre al ADN"),
]


def label(subject_start: int, subject_end: int) -> str:
    for lo, hi, name, what in DOMAINS:
        if subject_start <= hi and lo <= subject_end:
            return f"{name} — {what}"
    return "región enlazante, mucho más libre de mutar"


def rule(char: str = "─") -> None:
    print(char * 72)


def main() -> None:
    rule("═")
    print("EL EXPERIMENTO DEL OJO DE LA MOSCA")
    rule("═")

    print("""
Dos hechos, conocidos por separado durante décadas:

  · La mosca de la fruta tiene un gen llamado `eyeless`. Rómpelo y nacen
    moscas sin ojos.
  · Algunas personas nacen con `aniridia`: sin iris. Se sabía que era
    hereditaria.

Nada en esos dos nombres sugiere que tengan relación. Ni un buscador de texto,
ni un índice de literatura, ni un catálogo de genes los pondría juntos:
""")
    print(f"    'eyeless' contiene 'aniridia'? {'aniridia' in 'eyeless'}")
    print(f"    'aniridia' contiene 'eyeless'? {'eyeless' in 'aniridia'}")
    print("    palabras en común: ninguna\n")

    print("Pero las proteínas no son nombres. Son secuencias:\n")
    print(f"    eyeless (Drosophila)  {len(EYELESS_DROME):>4} aminoácidos")
    print(f"      {EYELESS_DROME[:58]}...")
    print(f"    PAX6 (humano)         {len(PAX6_HUMAN):>4} aminoácidos")
    print(f"      {PAX6_HUMAN[:58]}...\n")

    print("A simple vista tampoco dicen nada. Que las compare el ordenador.\n")
    rule()

    alignment = align(EYELESS_DROME, PAX6_HUMAN)
    blocks = conserved_blocks(EYELESS_DROME, PAX6_HUMAN)
    total = sum(b["length"] for b in blocks)
    matched = sum(b["identities"] for b in blocks)

    print(f"ALINEAMIENTO LOCAL (Smith–Waterman, BLOSUM62)   score = {alignment.score:.0f}\n")
    print(f"{'eyeless':>14}   {'PAX6':>12}   {'largo':>6} {'identidad':>10}   qué es")
    for b in blocks:
        print(
            f"{b['query_start']:>6}-{b['query_end']:<7} "
            f"{b['subject_start']:>5}-{b['subject_end']:<6} "
            f"{b['length']:>6} {b['percent_identity']:>9.0f}%   "
            f"{label(b['subject_start'], b['subject_end'])}"
        )

    best = max(blocks, key=lambda b: b["percent_identity"])
    print(f"\n{matched} de {total} residuos alineados son IDÉNTICOS.")
    print(
        f"El mejor bloque: {best['length']} residuos seguidos al "
        f"{best['percent_identity']:.0f}% de identidad.\n"
    )

    print("Los primeros 60 residuos de ese bloque, uno sobre otro:\n")
    q = EYELESS_DROME[best["query_start"] - 1 : best["query_end"]][:60]
    s = PAX6_HUMAN[best["subject_start"] - 1 : best["subject_end"]][:60]
    bar = "".join("|" if a == b else " " for a, b in zip(q, s))
    print(f"    mosca   {q}")
    print(f"            {bar}")
    print(f"    humano  {s}\n")

    rule()
    print("""
QUÉ SIGNIFICA

Un 93% de identidad en 133 residuos seguidos no ocurre por azar. Entre una
mosca y un humano, separados por unos 600 millones de años, sobrevive intacto
justo el trozo que se agarra al ADN — porque cambiarlo rompe la proteína.
Lo de en medio ha ido derivando libremente: nadie lo estaba mirando.

Así que `eyeless` y el gen de la aniridia descienden del mismo gen ancestral.
El mismo interruptor que enciende el ojo de una mosca enciende el tuyo.

Y una advertencia que el libro subraya, y conviene repetir: esto es una
HIPÓTESIS fuerte, no una demostración. El parecido de secuencia sugiere
función compartida; confirmarla exige experimentos. (En este caso se
confirmaron: el PAX6 de ratón, puesto en una mosca, induce ojos.)

LO QUE DE VERDAD IMPRESIONA

Esto era ciencia de portada en 1995. Hoy son dos descargas públicas, treinta
líneas de Python y unos segundos en un portátil. La barrera de entrada a este
tipo de pregunta ya no es el acceso a los datos ni la potencia de cálculo:
es saber qué preguntar.
""")
    rule("═")


if __name__ == "__main__":
    main()
