# Guía de uso del modelo ibérico

Esta guía explica el menú opción por opción: qué hace cada una, qué pregunta,
cuánto tarda y cómo se lee lo que devuelve. Para instalar el modelo, ver el
[README](README.md).

```bash
python menu.py
```

## Índice

1. [Lo primero: el punto de operación](#1-lo-primero-el-punto-de-operación)
2. [Cómo se navega el menú](#2-cómo-se-navega-el-menú)
3. [Sobre este punto: simular](#3-sobre-este-punto-simular)
4. [Sobre este punto: consultar](#4-sobre-este-punto-consultar)
5. [Sobre este punto: analizar](#5-sobre-este-punto-analizar)
6. [Sobre este punto: mapas](#6-sobre-este-punto-mapas)
7. [Sobre el modelo entero](#7-sobre-el-modelo-entero)
8. [Antes de citar una cifra](#8-antes-de-citar-una-cifra)
9. [Problemas frecuentes](#9-problemas-frecuentes)

---

## 1. Lo primero: el punto de operación

Al arrancar, el menú pregunta sobre qué punto de operación trabajar. La
elección vale para **toda la sesión**: todas las opciones del bloque *sobre
este punto* corren sobre él.

```
SOBRE QUE PUNTO DE OPERACION QUIERES TRABAJAR
  * 1) 28-abr-2025 12:33 (apagon iberico)
       RECONSTRUIDO de fuentes secundarias; el N-1 corre sobre un caso base LIMPIO
    2) 15-ene 20-21 h (punta invernal nocturna)
       DERIVADO; su caso base NO esta limpio (L1357): solo citable como severidad relativa
    3) exportacion generica de 3.000 MW (despacho uniforme)
       SINTETICO; no representa ninguna hora real
    q) salir
```

### Los tres puntos no tienen el mismo respaldo

| Punto | De dónde sale | Para qué sirve |
|---|---|---|
| **Apagón** (28-abr-2025, 12:33) | El mix de generación y los intercambios publicados para ese instante. Su dinámica se contrasta contra la frecuencia medida aquel día | El punto de referencia: el BTM, el deslastre y el N-1 descansan sobre él |
| **Punta** (15-ene, 20-21 h) | Las cuotas medias de enero por tecnología. Solar cero: es de noche | El caso de inercia alta, para contrastar con el apagón |
| **Genérico** | Una exportación sintética de 3.000 MW con despacho uniforme | Pruebas y comparación; no representa ninguna hora real |

La línea de color bajo cada uno es su aval, y se repite arriba de todas las
pantallas del menú para que ninguna salida acabe comparada con otra que no le
corresponde.

---

## 2. Cómo se navega el menú

El menú se parte en dos bloques:

- **Sobre este punto de operación** — corre sobre el punto elegido. Cuatro
  grupos: *Simular*, *Consultar*, *Analizar* y *Mapas*.
- **Sobre el modelo entero** — da lo mismo el punto elegido. Al lado de cada
  opción figura sobre qué corre de verdad (`apagon y punta`, `escenario
  generico`…).

Las opciones que no tienen sentido en un punto **no aparecen**, y al pie del
menú se lista cuáles faltan y por qué. Por eso **la numeración cambia de un
punto a otro**: el apagón tiene 24 opciones, la punta 20 y el genérico 21. Las
secciones de esta guía siguen los nombres, no los números.

| Tecla | Qué hace |
|---|---|
| un número | entra en la opción |
| `p` | cambia de punto de operación sin salir |
| `q` | sale |
| `Ctrl-C` | interrumpe la opción en curso y vuelve al menú |

Al entrar en cualquier opción se imprimen, antes de correr, **sobre qué
corre** y una explicación de lo que va a hacer. Las que lanzan un módulo
enseñan además la orden exacta (`$ python -m iberia.…`), que se puede copiar
para repetirla fuera del menú.

### Dónde quedan las salidas

Todo lo que escriben las opciones va a `resultados/`, con el punto de
operación en el nombre del fichero. Los mapas, en `resultados/mapas/` y
`resultados/visualizaciones/`.

### Por qué la primera consulta tarda

Las opciones de *Consultar* leen el **caso base resuelto**: el flujo de
potencia AC con los límites de reactivo de cada máquina. Resolverlo cuesta
alrededor de un minuto en el apagón y varios en la punta, donde el lazo de
reactivo tarda más en estabilizarse. El menú lo resuelve **una vez por
sesión** y lo guarda en memoria: a partir de la segunda consulta todo es
inmediato. Cambiar de punto con `p` lo descarta.

---

## 3. Sobre este punto: simular

### Simular contingencias (N-1)

Saca de servicio cada línea, transformador y generador, y mide **lo que la
contingencia añade** sobre el caso base: sobrecargas nuevas, cuánto empeora la
cargabilidad máxima y cuánta carga ibérica queda aislada. La métrica es
incremental a propósito: contada en absoluto, casi cualquier contingencia
heredaría las sobrecargas que el caso base ya tiene.

Pregunta qué hacer:

| Camino | Qué hace | Cuánto tarda |
|---|---|---|
| **Barrido completo** | Las 3.277 contingencias. Las ramas que aíslan carga se resuelven por topología; los generadores pequeños, por balance; el resto, unas 2.000, con flujo AC | ~34 min en el apagón, ~2 h 20 en la punta |
| **Solo el plan** | Cuántas contingencias hay de cada clase y cuánto costaría el barrido | segundos |
| **Una contingencia concreta** | La salida de un elemento elegido por nombre (`L0690`, `G0911`…) | segundos a un minuto |
| **El ranking** | Las más graves del último barrido | inmediato |

El barrido completo **pide confirmación**, porque al terminar sustituye el
barrido guardado de ese punto. Si se interrumpe, el guardado no se toca: el
progreso va a un fichero `.parcial.csv` aparte.

El ranking usa el barrido más reciente que hayas corrido tú. Si todavía no has
corrido ninguno, usa el **barrido de referencia** que trae el repositorio en
`data/referencia/`, y lo dice en pantalla. En la punta avisa de que el
elemento crítico es siempre el mismo (`L1357`): ver
[Antes de citar una cifra](#8-antes-de-citar-una-cifra).

### Dinámica de frecuencia (P.O. 1.6)

Integra la ecuación de oscilación tras perder generación de golpe y dispara
los escalones del esquema español de deslastre por mínima frecuencia.
Pregunta:

1. **Los MW que se pierden** (por defecto 2.000).
2. **El esquema de deslastre:**
   - *P.O. 1.6 completo*: los seis escalones. Los dos primeros, a 49,5 y
     49,3 Hz, desconectan **grupos de bombeo**; los cuatro siguientes, de 49,0 a
     48,0 Hz, desconectan **clientes**.
   - *Sin los escalones de bombeo*: solo los cuatro generales. Es la forma que
     tiene el esquema colombiano, y la que hay que usar para comparar los dos
     sistemas.
   - *Desactivado*.

Devuelve el nadir (o el instante del colapso, si colapsa), el RoCoF inicial,
lo que aporta la regulación primaria, los MW de clientes deslastrados y el
bombeo soltado, y la hora de disparo de cada escalón. Tarda un par de
segundos.

Un ejemplo de lectura, sobre el apagón y 2.000 MW: con el esquema completo
**solo dispara el escalón de bombeo** y el nadir queda en 49,5 Hz; sin él, el
mismo evento llega a 49,0 Hz y **corta 4.050 MW de clientes**.

### Deslastre con BTM: MILP frente al proporcional

El algoritmo central del modelo. Reparte la generación detrás del contador por
las barras, desconecta de golpe la parte conectada por inversor, y resuelve un
MILP que asigna barras a los escalones del P.O. 1.6 sabiendo cuánta generación
embebida **sana** se llevaría por delante cada corte. Después lo compara con el
reparto proporcional del esquema regulado, **a MW desconectados iguales**.

Pregunta qué porcentaje del BTM conectado por inversor se desconecta (por
defecto el 80 %). Tarda unos segundos y escribe la comparación en
`resultados/comparacion_deslastre_<punto>.csv` y la traza de frecuencia en
`resultados/visualizaciones/`.

### Cascada BTM multironda

No supone que el sistema aguanta el primer golpe: encadena la pérdida de
generación con la caída del BTM y deja correr la frecuencia hasta que el
sistema se estabiliza o colapsa. Repite el cálculo para distintas
penetraciones de BTM y distintos instantes de desconexión, que es lo que dice
**cuánto depende el resultado** de esos supuestos. Tarda unos segundos.

### Validación contra la traza real del 28-A

Solo en el apagón. Alimenta el modelo con el evento real documentado y compara
su frecuencia, segundo a segundo, con la que registró el Fraunhofer ISE en
Málaga. Es la única medida independiente contra la que se contrasta la
dinámica. Tarda unos segundos.

Lo que enseña: el modelo reproduce la caída medida y **no colapsa por
frecuencia, igual que el sistema real**. El 28 de abril la frecuencia solo cayó
0,75 Hz antes de que saltara la interconexión con Francia.

---

## 4. Sobre este punto: consultar

### Resumen del sistema

Las cifras del punto de una ojeada: tamaño de la red, generación, demanda,
exportación y pérdidas ibéricas (separadas: Francia es condición de contorno y
no entra), rango de tensión, cargabilidad máxima, inercia, reserva y la mezcla
de generación por tecnología. Avisa si algún generador no cabe en su curva de
capacidad de reactivo.

### Buscar una barra, generador o línea

Busca por texto libre (por ejemplo `ES01240` o `L1357`) y muestra lo que el
modelo sabe del elemento: tensión, placa, carga, y cada rama conectada con su
flujo y su cargabilidad. **Marca los nudos radiales** —los que cuelgan de la
red por una sola rama—, que es donde suelen esconderse los problemas de control
de tensión.

### El BTM español

La placa instalada de autoconsumo, el factor de producción derivado del propio
punto de operación, lo que está produciendo, la penetración sobre la demanda,
la fracción conectada por inversor y el reparto por región. En la punta
nocturna dice que el autoconsumo solar no produce.

### Balance por país (ES / PT / FR)

Generación, demanda e intercambio neto de cada país, con el aviso de que
Portugal y Francia son sistemas agregados.

### Cobertura de datos: qué es dato y qué es supuesto

La procedencia de cada parámetro del modelo, en tres clases: **dato**,
**derivado** y **supuesto**. Es la pantalla que conviene mirar antes de decidir
cuánto peso dar a un resultado.

---

## 5. Sobre este punto: analizar

### Umbral de penetración con inversor

No se ofrece en la punta: de noche el BTM solar produce cero y el umbral no
está definido.

A partir de qué penetración de BTM conectado por inversor una desconexión
masiva llega a disparar el deslastre. Barre la penetración, simula la caída en
cada punto y busca el umbral por bisección. Informa **dos umbrales**:

- el de **bombeo** (49,5 Hz), que es propio del esquema español, y
- el **general** (49,0 Hz), el primero que corta clientes, que es **el
  comparable** con otros sistemas.

Y dice si el punto de operación queda por encima o por debajo. Tarda unos
segundos.

### Sensibilidad del umbral

Cuánto se mueve el umbral general si cambian los supuestos: la fracción del BTM
que cae, la fracción conectada por inversor y —la fila que más informa— qué
pasa **sin los escalones de bombeo**. La distancia entre esa fila y la primera
es cuánto del margen del sistema lo aporta el bombeo y no la red. Tarda unos
segundos.

### Barrido del peso lambda

Solo en el apagón. El MILP de deslastre penaliza la destrucción de BTM sano con
un peso λ; esta opción recorre ese peso. Pregunta:

- **En operación normal** (~8 min): sin evento, con el BTM simplemente
  conectado, a varias penetraciones. Es el régimen que fija hasta dónde se
  puede subir λ sin que el esquema deje de cumplir su objetivo.
- **La calibración completa** (~10 min).

---

## 6. Sobre este punto: mapas

### Abrir los mapas

Lista los mapas del punto elegido y los del modelo entero, **cada uno con su
fecha**, y abre el elegido (o todos, con `t`) con la aplicación del sistema.

| Mapa | Qué muestra |
|---|---|
| la red por nivel de tensión | 400, 220 y 132 kV, las interconexiones y los agregados de Portugal y Francia |
| cargabilidad de las ramas | el caso base del punto, por bandas de carga |
| dónde está el BTM | la placa instalada de autoconsumo por barra |
| inercia instalada | H × placa por barra, de la red de construcción |
| la red con fondo cartográfico | lo mismo que el primero, sobre un mapa base |
| mapa interactivo | en el navegador, con zoom; necesita internet para el fondo |

**La primera vez no existe ninguno**, porque se generan al usarse. La opción lo
detecta y ofrece generarlos en el momento: unos segundos cada uno, salvo el de
cargabilidad, que antes resuelve el caso base.

### Regenerar el mapa de carga de este punto

Vuelve a dibujar la cargabilidad del punto. No existe para el escenario
genérico.

---

## 7. Sobre el modelo entero

### Estado del modelo y cifras citadas

Re-deriva en vivo las cifras principales del modelo para los dos escenarios:
la red, el balance, las tensiones, la cargabilidad, la inercia, el BTM, el
deslastre y el estado de los barridos N-1. Tarda varios minutos, porque resuelve
los casos base con los límites de reactivo.

### Comprobar los verificadores

Las comprobaciones de lo que no puede cambiar sin que algo esté mal: la
impedancia de cada línea contra su impedancia característica, los seis
escalones del P.O. 1.6, las garantías del MILP, los límites de reactivo, la
compensación shunt y los intercambios con Portugal y Francia. Pregunta si
correr solo las rápidas o todas (~2 min).

### Comparar los dos escenarios lado a lado

Somete el apagón y la punta a la misma batería y los imprime en columnas:
balance, tensiones, cargabilidad, inercia, la misma perturbación y el pool de
BTM. Pregunta si incluir una muestra N-1 de seis contingencias por escenario:
sin ella tarda ~2 min; con ella, ~37.

### Límites de reactivo (curva de capacidad)

Las pruebas de la curva de capacidad de cada máquina y del lazo que conmuta a
PQ las que la exceden. Sin esos límites, el colapso de tensión sería imposible
de observar por construcción. Corre sobre el escenario genérico. ~1 min.

### Compensación shunt (reactores)

Las pruebas del reactor por barra que absorbe parte de la carga capacitiva de
sus líneas. Corre sobre el escenario genérico. ~1 min.

### Regenerar los mapas del modelo

Vuelve a dibujar los mapas que no dependen de un punto: la red, la red con
fondo, el interactivo, la inercia instalada y el BTM.

### Correr el proyecto entero por lotes

Toda la cadena en orden de dependencias —construcción, verificaciones,
dinámica, deslastre, barrido N-1, mapas— con un resumen al final de qué pasó y
qué falló. Pide confirmación y pregunta si saltar los pasos caros: completa
tarda ~1 h 30, sin los caros ~20 min. **Su primer paso reconstruye la red** y
reescribe `data/redes/`.

### Reconstruir la red (DESTRUCTIVO)

Rehace la red desde los CSV de origen, construye los dos puntos de operación y
dimensiona los transformadores por el flujo real de los dos. Son cuatro pasos,
en ese orden, y se detiene en el primero que falle. Pide confirmación. Sirve
para comprobar que el modelo se reproduce desde los datos de origen, o para
regenerarlo después de cambiar algo en la construcción.

### Cómo se construye cada escenario

De dónde sale cada uno de los tres puntos de operación y qué aval tiene.

---

## 8. Antes de citar una cifra

- **El apagón es el punto de referencia.** Es el único cuya dinámica se ha
  contrastado contra una medida real, y el único cuyo caso base N-1 no arrastra
  problemas propios.
- **El N-1 de la punta se lee en relativo.** Su caso base tiene un nudo radial
  en Madrid (`L1357`) cuyo generador no puede regular tensión, y que domina la
  cargabilidad absoluta de todas las contingencias. El ranking entre
  contingencias sí vale; la cifra de cargabilidad, no.
- **La inercia es por tecnología.** No hay un registro público de inercia por
  unidad para el parque español, de modo que el nadir y el RoCoF dependen de
  los valores por tecnología del modelo.
- **El BTM depende de supuestos.** El efecto de su desconexión cambia con la
  fracción que cae y con el instante en que lo hace. *Cascada BTM multironda* y
  *Sensibilidad del umbral* existen para ver cuánto.
- **Portugal y Francia son agregados.** Francia no debe entrar en ninguna
  métrica del sistema ibérico; el menú ya la separa en el balance y en las
  pérdidas.

---

## 9. Problemas frecuentes

**`pip install` falla al instalar PyPSA.** Casi siempre es la versión de
Python: hace falta 3.11 o superior. Ver el [README](README.md#requisitos).

**El menú dice que faltan las dependencias.** El entorno virtual no está
activado, o no se instaló `requirements.txt` en él.

**En Windows, `Activate.ps1` da un error de *execution policy*.**
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` y volver a
intentarlo.

**El mapa con fondo cartográfico sale sin fondo.** El fondo necesita
`contextily`, que no se instala por defecto porque depende de GDAL. El mapa se
dibuja igual, sin capa de fondo. Para tenerla: `pip install contextily`.

**El mapa interactivo se ve sin fondo.** Lo descarga el navegador al abrirlo:
hace falta internet.

**Las consultas en la punta tardan.** Es la primera vez de la sesión: el caso
base de la punta tarda varios minutos en resolverse. Después es inmediato.

**Interrumpí un barrido N-1 y quedó un `.parcial.csv`.** Es el progreso del
barrido cortado. El barrido guardado no se ha tocado; el `.parcial.csv` se
puede borrar.
