# El experimento del ojo de la mosca

```bash
python discover.py
```

Un gen de mosca llamado `eyeless` y una enfermedad humana llamada `aniridia`.
Los nombres no comparten **nada**. Las secuencias comparten **133 residuos
seguidos al 93%**.

```
    mosca   HSGVNQLGGVFVGGRPLPDSTRQKIVELAHSGARPCDISRILQVSNGCVSKILGRYYETG
            |||||||||||| |||||||||||||||||||||||||||||||||||||||||||||||
    humano  HSGVNQLGGVFVNGRPLPDSTRQKIVELAHSGARPCDISRILQVSNGCVSKILGRYYETG
```

Una diferencia en sesenta posiciones, entre dos linajes separados por unos 600
millones de años.

Es el ejercicio con el que abre *Developing Bioinformatics Computer Skills*
(Gibas & Jambeck, O'Reilly 2001), el libro que enseñó a una generación de
biólogos a convertir una pregunta en un experimento computacional.

## Qué encuentra

```
       eyeless           PAX6    largo  identidad   qué es
    57-189         5-137       133        93%   paired domain — se agarra al ADN
   402-547       182-327       146        60%   homeodomain — el segundo agarre
   598-629       371-402        32        19%   región enlazante, libre de mutar
```

Lo revelador no es que se parezcan: es **dónde** se parecen. Sobrevive intacto
justo lo que toca el ADN, porque cambiarlo rompe la proteína. Lo de en medio ha
derivado libremente — nadie lo estaba mirando.

Eso permitió proponer que `eyeless` y el gen de la aniridia descienden del mismo
gen ancestral: el mismo interruptor enciende el ojo de una mosca y el tuyo.
Después se confirmó experimentalmente — el PAX6 de ratón, puesto en una mosca,
induce ojos.

**Y una advertencia que el libro subraya:** el parecido de secuencia genera una
hipótesis, no una demostración. Confirmarla exige experimentos de verdad.

## Por qué está al alcance de cualquiera

Esto fue portada en 1995. Hoy: dos secuencias públicas, treinta líneas de Python
y unos segundos en un portátil. Sin red, sin BLAST instalado, sin cuenta en
ningún sitio — las secuencias van vendidas en `sequences.py`.

**La barrera ya no son los datos ni el cómputo. Es saber qué preguntar.**

Que es exactamente donde un crew autónomo puede ayudar, y donde no: puede
escribirte y arreglarte el código del análisis; la pregunta la pones tú.

## Los números del libro NO se reproducen, y eso enseña algo

El libro reportaba el paired domain en eyeless 24–169 frente a una PAX6 humana
de **447 aa** desde la base PIR. Hoy UniProt da **422 aa** y las coordenadas
salen 57–189 / 5–137.

La biología es la misma; las entradas de base de datos cambiaron en 25 años. Por
eso las secuencias están **vendidas** en el repo en vez de descargarse: un
ejemplo que depende de una base de datos viva deja de significar lo mismo sin
avisar. Es reproducibilidad computacional, que es justo lo que el capítulo 2 del
libro insistía en enseñar.

## El ejercicio para el crew

Ver [`exercise.md`](exercise.md): reintroduce el off-by-one clásico y deja que
`harvest` lo encuentre y lo arregle solo. Resuelto con **`gemma4:12b` local** en
3 pasos y 3 llamadas.

## Ficheros

```
discover.py     la narración ejecutable — empieza por aquí
conserved.py    el análisis: alineamiento local y bloques conservados
sequences.py    PAX6_HUMAN y EYELESS_DROME, vendidas de UniProt
tests/          el oráculo: el paired domain donde la biología dice que está
exercise.md     cómo convertirlo en una tarea para el crew
```

Requiere `biopython`.
