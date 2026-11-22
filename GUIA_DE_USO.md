# Guía de uso del modelo ibérico

Esta guía describe el funcionamiento del menú del modelo ibérico. Para cada opción se explica su finalidad, la información que solicita, el tiempo de ejecución aproximado y la forma de interpretar los resultados. Para consultar los requisitos e instrucciones de instalación, véase el [README](README.md).

Para iniciar el menú, ejecutar desde la raíz del repositorio:

```bash
python menu.py
```

Los tiempos de ejecución indicados en esta guía son valores de referencia; el tiempo real depende de la capacidad de cómputo del equipo.

---

## Índice

1. [Selección del punto de operación](#1-selección-del-punto-de-operación)
2. [Navegación por el menú](#2-navegación-por-el-menú)
3. [Simulaciones sobre el punto de operación](#3-simulaciones-sobre-el-punto-de-operación)
4. [Consultas sobre el punto de operación](#4-consultas-sobre-el-punto-de-operación)
5. [Análisis sobre el punto de operación](#5-análisis-sobre-el-punto-de-operación)
6. [Mapas del sistema](#6-mapas-del-sistema)
7. [Operaciones sobre el modelo completo](#7-operaciones-sobre-el-modelo-completo)
8. [Consideraciones antes de citar resultados](#8-consideraciones-antes-de-citar-resultados)
9. [Problemas frecuentes](#9-problemas-frecuentes)

---

## 1. Selección del punto de operación

Al iniciar el menú, se solicita seleccionar el punto de operación sobre el que se realizarán los análisis. La selección se mantiene durante **toda la sesión** y se aplica a las opciones agrupadas bajo la sección *Sobre este punto de operación*.

El menú presenta los siguientes puntos:

```text
SOBRE QUE PUNTO DE OPERACION QUIERES TRABAJAR
  * 1) 28-abr-2025 12:33 (apagon iberico)
       MEDIDO (ENTSO-E 12:15 CEST, convencional por central con el I90) con el balance cerrado; su caso base arranca con 1 sobrecarga (L1146, 104 %): el N-1 se cita contra esa referencia
    2) 15-ene-2025 20:45 (punta invernal nocturna)
       MEDIDO (ENTSO-E, convencional por central con el I90) con el balance cerrado; su caso base arranca con 9 sobrecargas (4 en la frontera con Francia): el N-1 se cita contra esa referencia
    3) exportacion generica de 3.000 MW (despacho uniforme)
       SINTETICO; no representa ninguna hora real
    q) salir
```

### Respaldo de los puntos de operación

Los tres puntos de operación tienen distinto origen y nivel de respaldo. Esta distinción debe tenerse en cuenta al interpretar y comparar los resultados.

| Punto | Procedencia | Uso previsto |
|---|---|---|
| **Apagón** (28-abr-2025, 12:33 h) | Datos medidos de ENTSO-E para las 12:15 h y generación convencional central a central con el I90 de REE. Su respuesta dinámica se contrasta con la frecuencia medida ese día. | Punto de referencia para los análisis de BTM, deslastre y contingencias N-1. |
| **Punta** (15-ene-2025, 20:45 h) | Datos medidos de ENTSO-E y generación convencional central a central con el I90 de REE, en el cuarto de hora de la punta anual. La generación solar es prácticamente nula (100 MW) por tratarse de un periodo nocturno. | Escenario de elevada inercia para contrastar sus resultados con los del apagón. |
| **Genérico** | Escenario sintético de exportación de 3.000 MW con despacho uniforme. | Comparaciones metodológicas. No representa una hora real de operación. |

El indicador de respaldo asociado a cada punto se muestra en la pantalla de selección y se repite en la cabecera de las pantallas del menú. Esto permite identificar el escenario al que corresponde cada resultado y evitar comparaciones entre puntos de operación distintos sin tener en cuenta sus diferencias.

---

## 2. Navegación por el menú

El menú está organizado en dos bloques:

- **Sobre este punto de operación:** agrupa las opciones que se ejecutan sobre el punto seleccionado. Incluye las secciones *Simular*, *Consultar*, *Analizar* y *Mapas*.
- **Sobre el modelo entero:** contiene operaciones que no dependen del punto activo o que se ejecutan sobre varios escenarios. El menú indica junto a cada opción los puntos de operación que utiliza, por ejemplo, `apagon y punta` o `los tres puntos`.

Las opciones que no son aplicables al punto seleccionado **no se muestran**. El menú identifica al final de la pantalla las opciones omitidas y explica el motivo. Por esta razón, la numeración puede variar según el punto de operación: el escenario del apagón presenta 18 opciones, la punta 14 y el escenario genérico 15. Esta guía se organiza por el nombre de cada funcionalidad y no por su número en el menú.

| Tecla | Función |
|---|---|
| Número | Abre la opción correspondiente. |
| `p` | Permite cambiar el punto de operación sin salir del menú. |
| `q` | Cierra el menú. |
| `Ctrl-C` | Interrumpe la opción en ejecución y regresa al menú. |

Antes de ejecutar una opción, el menú indica el punto de operación sobre el que trabajará y presenta una descripción de la tarea. Las opciones que ejecutan un módulo independiente muestran también el comando correspondiente (`python -m iberia.…`), que puede utilizarse para repetir la ejecución directamente desde la terminal.

### Ubicación de los resultados

Los archivos generados por las opciones se almacenan en `resultados/` e incluyen el punto de operación en su nombre. Los mapas se guardan en `resultados/mapas/` y `resultados/visualizaciones/`.

### Tiempo de la primera consulta

Las opciones de *Consultar* utilizan el **caso base resuelto**, correspondiente al flujo de potencia AC con los límites de potencia reactiva de cada máquina. Su resolución tarda aproximadamente un minuto en cualquiera de los tres puntos de operación.

El menú resuelve el caso base una sola vez por sesión y conserva el resultado en memoria. Por ello, las consultas posteriores se ejecutan de forma prácticamente inmediata. Al cambiar de punto de operación mediante `p`, el resultado almacenado se descarta y debe resolverse el nuevo caso base.

---

## 3. Simulaciones sobre el punto de operación

### Simular contingencias (N-1)

Esta opción desconecta individualmente cada línea, transformador y generador para evaluar el efecto de cada contingencia respecto al caso base. Entre las variables analizadas se encuentran las sobrecargas adicionales, la variación de la cargabilidad máxima y la cantidad de carga española que queda aislada. La carga de los nudos agregados de Portugal y Francia no se contabiliza.

La evaluación utiliza una **métrica incremental**: cuantifica los cambios atribuibles a la contingencia y no únicamente los valores absolutos posteriores a ella. De esta forma, las sobrecargas que ya existen en el caso base no se atribuyen a la salida del elemento.

El menú permite seleccionar uno de los siguientes procedimientos:

| Modalidad | Descripción | Tiempo aproximado |
|---|---|---|
| **Barrido completo** | Evalúa las 3.277 contingencias. Las líneas y transformadores que aíslan carga se analizan mediante topología; los generadores pequeños, mediante balance de potencia; y las restantes (2.134 en el apagón y 2.049 en la punta), mediante flujo AC. | Aproximadamente 40 minutos en el escenario del apagón y 30 minutos en el escenario de punta. |
| **Solo el plan** | Informa el número de contingencias de cada clase y estima el coste computacional del barrido. | Segundos. |
| **Una contingencia concreta** | Evalúa la salida de un elemento seleccionado por su nombre, por ejemplo, `L0690` o `G0911`. | De algunos segundos a un minuto. |
| **El ranking** | Muestra las contingencias más severas del último barrido disponible. | Inmediato, si ya existe un barrido. |

El barrido completo solicita confirmación porque, al finalizar correctamente, sustituye el barrido guardado para ese punto de operación. Si la ejecución se interrumpe, el resultado anterior se conserva y el progreso parcial se escribe en un archivo independiente con extensión `.parcial.csv`.

El ranking utiliza el barrido más reciente ejecutado por el usuario. Si todavía no se ha realizado un barrido, utiliza el **barrido de referencia** incluido en `data/referencia/` e informa de ello en pantalla. Si el elemento crítico identificado es el mismo en todas las contingencias, el menú lo advierte, ya que esta condición indica una limitación del caso base y no una característica de la red.

Los casos base no están completamente limpios: el de la punta presenta 9 sobrecargas (cuatro en la frontera con Francia) y el del apagón una (`L1146`, 104 %). Los resultados deben interpretarse como incremento respecto a esa referencia, tal como se explica en [Consideraciones antes de citar resultados](#8-consideraciones-antes-de-citar-resultados).

### Dinámica de frecuencia (P.O. 1.6)

Esta opción integra la ecuación de oscilación después de una pérdida súbita de generación y simula la actuación de los escalones del esquema español de deslastre por mínima frecuencia, definido en el Procedimiento de Operación P.O. 1.6.

El menú solicita los siguientes parámetros:

1. **Potencia de generación perdida:** valor en MW que se desconecta. El valor predeterminado es 2.000 MW.
2. **Esquema de deslastre:** permite seleccionar una de estas alternativas:
   - **P.O. 1.6 completo:** considera los seis escalones. Los dos primeros, a 49,5 y 49,3 Hz, desconectan grupos de bombeo; los cuatro siguientes, entre 49,0 y 48,0 Hz, desconectan clientes.
   - **Sin los escalones de bombeo:** considera únicamente los cuatro escalones generales. Esta configuración se utiliza para comparar el comportamiento con esquemas que no incluyen escalones específicos de bombeo, como el esquema colombiano considerado en el estudio.
   - **Desactivado:** no aplica los escalones de deslastre.

La simulación informa el nadir de frecuencia o, si se produce el colapso, el instante en que ocurre; el RoCoF inicial; la contribución de la regulación primaria; la potencia de clientes deslastrada; la potencia de bombeo desconectada; y el instante de actuación de cada escalón. El tiempo de ejecución es de unos segundos.

Como referencia, para el escenario del apagón y una pérdida de 2.500 MW, el esquema completo activa únicamente el escalón de bombeo y el nadir alcanza 49,5 Hz. Al desactivar los escalones de bombeo, el mismo evento alcanza 49,0 Hz y se desconectan 3.633 MW de clientes. Con la pérdida predeterminada de 2.000 MW, sin los escalones de bombeo el nadir se sitúa en 49,02 Hz, dos centésimas por encima del primer escalón general.

### Deslastre con BTM: MILP frente al proporcional

Esta opción implementa el algoritmo de deslastre que considera la generación detrás del contador (*Behind-the-Meter*, BTM). El modelo distribuye la generación BTM entre las barras, simula la desconexión súbita de la fracción conectada mediante inversores y resuelve un problema de optimización lineal entera mixta (MILP).

El MILP asigna las barras a los escalones del P.O. 1.6 teniendo en cuenta cuánta generación BTM permanece conectada después de la desconexión inicial y podría perderse como consecuencia adicional del deslastre. El modelo identifica esta fracción como **generación embebida sana**. El resultado se compara con el reparto proporcional del esquema regulado, utilizando como criterio una misma potencia total desconectada.

El menú solicita el porcentaje de BTM conectado mediante inversores que se desconecta. El valor predeterminado es 80 %.

Como referencia, en el escenario del apagón y con el valor predeterminado, el sistema colapsa a los 9,27 s aun con los seis escalones activados: el esquema desconecta como máximo la mitad de la demanda más el bombeo (15.140 MW) frente a un evento de 19.715 MW. El esquema completo evita el colapso hasta una desconexión de BTM del 74 %. La comparación entre el MILP y el reparto proporcional se realiza igualmente, porque se mide sobre la misma secuencia de escalones disparados.

El plan del MILP se decide sin conocer el evento: se resuelve con ocho sorteos del BTM estimado independientes de la desconexión real, y el resultado es la media. En el escenario del apagón el MILP destruye un 1,5 % menos de generación embebida sana que el reparto proporcional (775,9 frente a 787,6 MW), y según el sorteo la diferencia va de −1,6 a 7,0 %. La ventaja es pequeña porque el modelo reparte el BTM entre las barras de cada región en proporción a la carga, así que no hay diferencias espaciales que el MILP pueda aprovechar.

La ejecución tarda alrededor de un minuto en el apagón y unos veinte en la punta, donde casi no hay BTM y el MILP agota su tiempo límite en cada escalón. Genera:

- La comparación de los métodos en `resultados/comparacion_deslastre_<punto>.csv`.
- El resultado de cada sorteo del plan en `resultados/comparacion_deslastre_<punto>_semillas.csv`.
- La traza de frecuencia en `resultados/visualizaciones/`.

### Cascada BTM multironda

Esta opción analiza una secuencia de eventos en lugar de limitarse a una única perturbación. Encadena la pérdida de generación con la desconexión de BTM y calcula la evolución de la frecuencia hasta que el sistema se estabiliza o colapsa.

El procedimiento se repite para diferentes niveles de penetración de BTM y distintos instantes de desconexión. De esta manera, permite evaluar la sensibilidad de los resultados frente a estos supuestos. El tiempo de ejecución es de unos segundos.

### Validación contra la frecuencia medida del 28-A

Esta opción está disponible únicamente para el escenario del apagón. Alimenta el modelo con la secuencia de eventos al milisegundo del informe final de ENTSO-E (20 de marzo de 2026) y compara la frecuencia simulada con la medida por unidades PMU en Málaga y Zúrich. El tiempo de ejecución es de unos segundos.

La comparación se hace por fases, porque en cada una la física que representa el modelo es distinta. Hasta las 12:33:16 la frecuencia de Málaga coincide con la de Zúrich: Iberia seguía sincronizada con Europa y el modelo aislado no es aplicable. Entre las 12:33:16 y la separación de Francia (12:33:21,535), el modelo sigue la caída de Málaga con un error medio de 0,084 Hz, aunque no representa la oscilación de ángulo que domina ese tramo. En la isla, la caída medida (−0,74 Hz/s) exige un déficit de al menos 3,5 GW, mientras que los eventos registrados dan un superávit de 2,1 GW: faltan al menos 5,6 GW que no aparecen en ningún registro.

La salida también compara la energía cinética del modelo con la que calcula ENTSO-E para las 12:30 (119,5 GW·s). La inercia del apagón está calibrada con esa cifra; la del escenario de punta no, porque ENTSO-E solo la publica para ese instante.

---

## 4. Consultas sobre el punto de operación

### Resumen del sistema

Presenta las principales magnitudes del punto de operación: tamaño de la red, generación, demanda, exportación y pérdidas del sistema ibérico, rangos de tensión, cargabilidad máxima, inercia, reserva y composición de la generación por tecnología.

El balance mantiene separadas las magnitudes de Francia, que se representa como condición de contorno y no se incluye en los totales ibéricos. La consulta también advierte si algún generador excede su curva de capacidad de potencia reactiva.

### Buscar una barra, generador o línea

Permite buscar elementos mediante texto libre. Por ejemplo, se pueden introducir identificadores como `ES01240` o `L1357`.

La consulta muestra la información disponible para el elemento encontrado, como tensión, potencia nominal, carga y las líneas conectadas, junto con sus flujos y cargabilidades. También identifica los **nudos radiales**, es decir, aquellos conectados al resto de la red mediante una única línea. Esta información permite localizar puntos cuya conexión depende de un único elemento y que pueden requerir una revisión particular en los análisis de tensión.

### El BTM español

Presenta la potencia instalada de autoconsumo, el factor de producción estimado a partir del propio punto de operación, la potencia que está produciendo, su penetración respecto a la demanda, la fracción conectada mediante inversores y su distribución regional.

En el escenario de punta nocturna, la consulta indica que la generación solar de autoconsumo es nula.

### Balance por país (ES / PT / FR)

Muestra la generación, la demanda y el intercambio neto de España, Portugal y Francia. La consulta recuerda que Portugal y Francia están representados mediante sistemas agregados y no mediante sus respectivas redes internas.

### Cobertura de datos: qué es dato y qué es supuesto

Presenta la procedencia de los parámetros utilizados por el modelo y los clasifica en tres categorías:

- **Dato:** información disponible directamente en las fuentes utilizadas.
- **Derivado:** valor calculado a partir de datos de entrada o de otros parámetros.
- **Supuesto:** valor adoptado ante la ausencia de información específica.

Esta consulta permite identificar qué resultados dependen de mediciones o datos publicados y cuáles están condicionados por hipótesis del modelo.

---

## 5. Análisis sobre el punto de operación

### Umbral de penetración con inversor

Esta opción no está disponible para el escenario de punta. Durante el periodo nocturno, la generación solar BTM es nula, por lo que no es posible definir el umbral asociado a su desconexión.

El análisis determina a partir de qué nivel de penetración de BTM conectado mediante inversores una desconexión masiva provoca la activación del deslastre. Para ello, barre distintos niveles de penetración, simula la desconexión correspondiente y estima el umbral mediante el método de bisección.

Se calculan dos umbrales:

- **Umbral de bombeo:** corresponde a la activación del escalón de 49,5 Hz, propio del esquema español.
- **Umbral general:** corresponde a la activación del primer escalón que desconecta clientes, a 49,0 Hz. Es el valor comparable con sistemas que no consideran escalones específicos de bombeo.

El resultado también indica si el punto de operación analizado se encuentra por encima o por debajo de cada umbral. El tiempo de ejecución es de unos segundos.

### Sensibilidad del umbral

Evalúa la variación del umbral general ante cambios en los supuestos del modelo, entre ellos la fracción de BTM que se desconecta y la proporción de generación conectada mediante inversores.

La comparación incluye una condición **sin los escalones de bombeo**. La diferencia entre el umbral obtenido con el esquema completo y el obtenido sin dichos escalones permite cuantificar su contribución al margen disponible antes de activar el deslastre general. El tiempo de ejecución es de unos segundos.

### Barrido del peso lambda

Esta opción está disponible únicamente para el escenario del apagón. El MILP de deslastre utiliza un peso de penalización, λ, asociado a la desconexión de generación BTM que no forma parte de la perturbación. Esta funcionalidad evalúa cómo varían los resultados al modificar dicho peso.

El menú ofrece dos alternativas:

- **Operación normal** (aproximadamente 1 minuto): analiza escenarios sin perturbación, con el BTM conectado, para distintos niveles de penetración. Este régimen permite evaluar hasta qué valor de λ puede aumentarse la penalización sin que el esquema deje de cumplir su objetivo.
- **Calibración completa** (unos dos minutos): resuelve el plan con λ = 0,5, 5, 25, 60 y 100 frente a la caída del 80 % del BTM, con ocho sorteos del plan independientes del evento. Todos los valores cubren el objetivo del esquema y dan prácticamente la misma generación embebida sana perdida (entre 774 y 781 MW de media), así que el valor predeterminado, λ = 25, no está optimizado: cualquier valor del rango se comporta igual.

---

## 6. Mapas del sistema

### Abrir los mapas

Esta opción presenta los mapas disponibles para el punto de operación seleccionado y los mapas generales del modelo. Cada elemento de la lista incluye su fecha de generación. Se puede abrir un mapa individual o todos mediante la tecla `t`, utilizando la aplicación asociada en el sistema.

| Mapa | Información presentada |
|---|---|
| Red por nivel de tensión | Red de 400 kV y de 220-132 kV, interconexiones internacionales y sistemas agregados de Portugal y Francia. |
| Cargabilidad de las líneas | Cargabilidad de las líneas del caso base del punto de operación, agrupada en bandas (< 50 %, 50 – 75 %, 75 – 100 % y > 100 %). |
| Distribución del BTM | Potencia instalada de autoconsumo por barra, agrupada por bandas de potencia. |
| Inercia instalada | Producto de la constante de inercia, H, por la potencia de placa, representado por barra a partir de la red de construcción. |
| Red con fondo cartográfico | Representación de la red por nivel de tensión sobre un mapa base. |
| Mapa interactivo | Visualización en el navegador con controles de zoom. Requiere conexión a internet para cargar el fondo cartográfico. |

Los mapas se generan bajo demanda, por lo que es posible que no existan durante la primera consulta. En ese caso, el menú lo indica y ofrece generarlos. La mayoría tarda unos segundos; el mapa de cargabilidad requiere resolver previamente el caso base.

### Regenerar el mapa de carga de este punto

Vuelve a generar el mapa de cargabilidad correspondiente al punto de operación seleccionado. Requiere resolver el caso base, lo que tarda aproximadamente un minuto. Esta opción no está disponible para el escenario genérico.

---

## 7. Operaciones sobre el modelo completo

Estas opciones no dependen del punto de operación seleccionado. Las comprobaciones internas del modelo y la reconstrucción de las redes a partir de los datos de origen no forman parte del menú; se ejecutan desde la línea de comandos, tal como se describe en el [README](README.md#comprobaciones).

### Comparar los dos escenarios lado a lado

Compara el escenario del apagón y el de punta aplicando el mismo conjunto de análisis. Los resultados se presentan en columnas e incluyen el balance de potencia, las tensiones, la cargabilidad, la inercia, la respuesta ante una misma perturbación y el conjunto de generación BTM considerado.

También se puede incluir una muestra N-1 de seis contingencias por escenario. Sin esta muestra, la ejecución tarda aproximadamente dos minutos; al incluirla, el tiempo aumenta a unos 37 minutos.

### Regenerar los mapas del modelo

Vuelve a generar los mapas que no dependen de un punto de operación específico: la red, la red con fondo cartográfico, el mapa interactivo, la distribución de inercia instalada y la distribución del BTM.

### Cómo se construye cada escenario

Presenta la procedencia de los tres puntos de operación y el respaldo asociado a cada uno: los puntos del apagón y de la punta, construidos con los datos medidos de ENTSO-E y el I90 de REE, y el escenario genérico.

---

## 8. Consideraciones antes de citar resultados

Antes de utilizar los resultados del modelo en un informe, presentación o publicación, es importante tener en cuenta las siguientes limitaciones:

- **El escenario del apagón es el punto de referencia.** Es el único cuya respuesta dinámica se ha contrastado con una medición real de frecuencia. Su caso base para el análisis N-1 presenta una línea sobrecargada (`L1146`, 104 %) y ninguna barra fuera del rango de 0,90 a 1,10 pu.
- **La punta es un punto medido, con un supuesto que decide un resultado.** Su caso base presenta 9 líneas entre el 102 % y el 117 %; cada contingencia debe interpretarse como incremento respecto a esa referencia. Que la punta sobreviva a la cascada del 28-A **sin** deslastre depende de la reserva primaria asignada a Portugal, de la que no hay dato; con el deslastre del P.O. 1.6 sobrevive en cualquier caso.
- **La inercia se estima por tecnología.** No se dispone de un registro público de inercia individual por unidad para el parque español. En el apagón, el total está calibrado con la energía cinética publicada por ENTSO-E (119,5 GW·s); en los demás escenarios, los resultados de nadir y RoCoF dependen de los valores asignados por tecnología en el modelo.
- **El efecto del BTM depende de los supuestos del escenario.** La respuesta ante su desconexión varía según la fracción de generación que se pierde y el instante en que ocurre el evento. Las opciones *Cascada BTM multironda* y *Sensibilidad del umbral* permiten estudiar esta dependencia.
- **Portugal y Francia se representan mediante sistemas agregados.** Francia se utiliza como condición de contorno y sus magnitudes deben mantenerse separadas de los balances y métricas del sistema ibérico; el menú ya las separa en el balance y en las pérdidas. Portugal forma parte de la representación agregada del sistema síncrono ibérico.
- **El escenario genérico no es una referencia de tensión.** Presenta 21 barras entre 1,10 y 1,12 pu, ya que la compensación reactiva del modelo es fija.

---

## 9. Problemas frecuentes

**`pip install` falla al instalar PyPSA.** La causa más habitual es una versión de Python incompatible. El proyecto requiere Python 3.11 o superior. Consulta la sección [Requisitos del README](README.md#requisitos).

**El menú indica que faltan dependencias.** Es posible que el entorno virtual no esté activado o que `requirements.txt` no se haya instalado dentro de ese entorno. Activa el entorno e instala las dependencias indicadas en el README.

**En Windows, `Activate.ps1` genera un error de `execution policy`.** Ejecuta el siguiente comando en PowerShell y vuelve a activar el entorno:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

**El mapa con fondo cartográfico se genera sin fondo.** La capa de fondo requiere `contextily`, que no se instala de forma predeterminada debido a su dependencia de GDAL. El mapa se genera igualmente, pero sin la capa cartográfica. Para instalarla, ejecuta:

```bash
pip install contextily
```

**El mapa interactivo aparece sin fondo cartográfico.** El navegador descarga esa capa al abrir el mapa, por lo que se necesita conexión a internet.

**La primera consulta de la sesión tarda aproximadamente un minuto.** La primera consulta requiere resolver el caso base con los límites de potencia reactiva. Las consultas posteriores reutilizan el caso resuelto y se ejecutan de forma prácticamente inmediata.

**Se interrumpió un barrido N-1 y se generó un archivo `.parcial.csv`.** El archivo contiene el progreso del barrido interrumpido. El resultado guardado anteriormente no se modifica, por lo que el archivo parcial puede eliminarse si no se necesita conservar ese progreso.
