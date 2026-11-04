# modelo-iberia — dinámica de frecuencia y BTM del sistema eléctrico ibérico

Modelo de la **red de transporte peninsular española** de 132/220/400 kV,
construido sobre [PyPSA](https://pypsa.org/), con Portugal y Francia como
sistemas vecinos. Sobre él trabajan cuatro capas de análisis:

- **contingencias N-1** con flujo de potencia AC y límites de capacidad
  reactiva de cada máquina,
- **dinámica de frecuencia** con el esquema real de deslastre por mínima
  frecuencia de Red Eléctrica de España (P.O. 1.6, seis escalones),
- **cascada** que encadena la pérdida de generación con la desconexión de la
  generación detrás del contador (BTM), y
- **deslastre de carga consciente del BTM**, un MILP que reparte las barras
  entre los escalones del P.O. 1.6 destruyendo la menor cantidad posible de
  generación embebida sana.

El modelo incluye tres puntos de operación listos para simular, entre ellos
la **reconstrucción del 28 de abril de 2025 a las 12:33**, el instante previo
al apagón ibérico, cuya dinámica se contrasta contra la medida de frecuencia
real registrada aquel día.

> **Los puntos de operación son reconstrucciones a partir de fuentes
> públicas**, no el estado de la red registrado por el operador. Sirven para
> estudiar el comportamiento del sistema, no para reproducir cifras
> operativas exactas. Ver [Alcance del modelo](#alcance-del-modelo).

## Requisitos

- **Python 3.11 o superior.** PyPSA 1.x no publica ruedas para versiones
  anteriores, así que con 3.10 la instalación falla. Compruébalo antes de
  empezar:

  ```powershell
  py --list          # Windows: los intérpretes instalados
  ```

  ```bash
  python3 --version  # macOS o Linux
  ```

  Si da 3.10 o menos, usa un intérprete más nuevo al crear el entorno.

- Las dependencias de `requirements.txt`: PyPSA, pandas, NumPy, SciPy,
  NetworkX, matplotlib, netCDF4, linopy y HiGHS (el MILP del deslastre), y
  folium (el mapa interactivo).

## Primeros pasos

El repositorio trae los datos y las redes ya construidas, de modo que
**funciona sin internet desde el primer momento**.

### Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python menu.py
```

Si `Activate.ps1` falla con un error de *execution policy* —lo habitual en una
instalación recién hecha—, se permite solo para esta ventana y se vuelve a
intentar:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### macOS o Linux (Bash)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python menu.py
```

### El menú

Lo primero que pregunta es **sobre qué punto de operación trabajar**, y esa
elección vale para toda la sesión:

```
SOBRE QUE PUNTO DE OPERACION QUIERES TRABAJAR
  1) 28-abr-2025 12:33 (apagon iberico)
  2) 15-ene 20-21 h (punta invernal nocturna)
  3) exportacion generica de 3.000 MW (despacho uniforme)
```

Después ofrece las opciones en dos bloques:

- **Sobre este punto de operación** — lo que corre sobre el punto elegido,
  agrupado en *simular*, *consultar*, *analizar* y *mapas*.
- **Sobre el modelo entero** — lo que no depende del punto: comprobaciones,
  comparación de los dos escenarios, mantenimiento.

Cada opción dice sobre qué corre y cuánto tarda antes de lanzarla. Las que no
tienen sentido en un punto —el umbral de penetración en la punta nocturna,
donde el BTM solar produce cero— no aparecen, y el menú dice por qué. Se cambia
de punto en cualquier momento con la tecla `p`.

**[GUIA_DE_USO.md](GUIA_DE_USO.md) explica las opciones una a una**, con sus
preguntas, sus valores por defecto y lo que significa cada resultado.

## Comandos

Todo lo que hace el menú está disponible también como módulo. Se ejecutan
desde la raíz del repositorio:

| Comando | Qué hace |
|---|---|
| `python -m iberia.estado_actual` | las cifras principales del modelo, re-derivadas en vivo |
| `python -m iberia.barrido_rapido --red apagon` | barrido N-1 completo: 3.277 contingencias |
| `python -m iberia.barrido_rapido --red punta --plan` | cuántas contingencias de cada clase y cuánto costaría |
| `python -m iberia.analisis_btm_cascada --red apagon` | el evento del 28-A, sin y con caída de BTM |
| `python -m iberia.deslastre_btm_espana --red apagon --caida 80` | deslastre consciente del BTM frente al reparto proporcional |
| `python -m iberia.umbral_penetracion --red apagon --sensibilidad` | a partir de qué penetración de BTM dispara el deslastre |
| `python -m iberia.validar_traza_28a` | contraste de la dinámica contra la frecuencia medida |
| `python -m iberia.comparar_escenarios --n1 0` | el apagón y la punta, lado a lado |
| `python -m iberia.barrido_lambda_normal` | el peso λ del MILP en operación normal |
| `python -m iberia.calibrar_lambda_espana` | calibración completa de λ |
| `python -m iberia.mapas todos --red apagon` | mapas de la red, del BTM y de cargabilidad |
| `python -m iberia.visualize_network` | mapa con fondo cartográfico y mapa interactivo HTML |
| `python -m tools.correr_todo --rapido` | el proyecto entero por lotes |

Los módulos de simulación aceptan `--red {apagon,punta,escenario}` para elegir
el punto de operación:

```bash
python -m iberia.deslastre_btm_espana --red punta
python -m iberia.mapas carga --red punta
python -m iberia.barrido_rapido --red punta --procesos 8
```

Las salidas se escriben en `resultados/`, con el punto de operación en el
nombre del fichero (`contingencias_n1_apagon.csv`,
`comparacion_deslastre_punta.csv`) para que una ejecución no pise a otra.

El repositorio incluye en `data/referencia/` los barridos N-1 de los dos
escenarios principales, de modo que el ranking de contingencias y sus figuras
están disponibles nada más descargar. En cuanto corres un barrido propio, el
modelo pasa a usar el tuyo.

## Comprobaciones

```bash
python -m tests.verificar_parametros_linea        # impedancias contra la impedancia característica
python -m tests.verificar_invariancia_frecuencia  # invariantes de la dinámica
python -m tests.verificar_escalones_espana        # los seis escalones del P.O. 1.6
python -m tests.verificar_milp_espana             # garantías del MILP de deslastre
python -m tests.verificar_limites_reactivos       # curva de capacidad y lazo PV-PQ
python -m tests.verificar_compensacion            # compensación shunt
python -m tests.verify_pt_fr_flows                # intercambios con Portugal y Francia
```

Y para reconstruir la red entera desde los CSV de origen y comprobar que
reproduce el modelo publicado (reescribe `data/redes/`):

```bash
python -m tests.test_pipeline_smoke
python -m iberia.construccion.build_blackout_snapshot
python -m iberia.construccion.build_punta_snapshot
python -m iberia.construccion.dimensionar_trafos --aplicar
```

La opción *Reconstruir la red* del menú hace estos cuatro pasos en orden y se
detiene en el primero que falle.

## Estructura

```
menu.py           punto de entrada interactivo
GUIA_DE_USO.md    el manual del menú, opción por opción
iberia/           el modelo
  config.py         rutas, resueltas desde la raíz, y los puntos de operación
  construccion/     la cadena que construye la red desde los CSV de origen
  ...               flujo, N-1, límites de reactivo, frecuencia, BTM,
                    deslastre, cascada, mapas
data/
  fuentes/          los CSV de la red y el contorno geográfico
  redes/            las redes PyPSA de cada punto de operación, ya construidas
  referencia/       barridos N-1 de referencia de los dos escenarios
tests/            las comprobaciones del modelo
tools/            el proyecto entero por lotes
resultados/       salidas: CSV, figuras y mapas (se crea sola)
```

## Alcance del modelo

- **Tres puntos de operación.** El del **apagón** se reconstruye con el mix de
  generación y los intercambios publicados para las 12:33 del 28 de abril; su
  dinámica está contrastada contra la frecuencia medida ese día. La **punta
  invernal** se deriva de las cuotas medias de enero, y el **escenario
  genérico** es una exportación sintética de 3.000 MW.
- **Portugal y Francia** se representan como sistemas agregados por tecnología
  conectados en sus puntos de interconexión, no como redes internas. Portugal
  forma parte de la isla síncrona y entra en la inercia; Francia es condición
  de contorno.
- **El N-1 del escenario de punta** se lee como severidad relativa entre
  contingencias: su caso base arrastra un nudo radial (`L1357`, en Madrid) que
  domina la cargabilidad absoluta. El del apagón no tiene esa limitación.
- **La inercia** se calcula por tecnología a partir de la capacidad acoplada
  en cada punto de operación, no máquina a máquina.
- Cada punto de operación es un **instante**, no una serie temporal.

## Fuentes de datos

- **Red, generación y demanda:** Nokandi, E. (2025). *Data of the Spanish
  Electric Power System* (v1.0.0) [Dataset]. Zenodo.
  [doi:10.5281/zenodo.14748878](https://doi.org/10.5281/zenodo.14748878).
  Licencia [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Los
  ficheros de `data/fuentes/*.csv` son los del dataset sin modificar; las
  transformaciones las hace la cadena de `iberia/construccion/`.
- **El punto de operación del 28 de abril de 2025:** NERC, *Iberian Peninsula
  Blackout – Contextual Comparison with North America* (26 de junio de 2025),
  y las cifras de generación e intercambio de REE y ENTSO-E para ese instante.
- **La validación de la dinámica:** la medida de frecuencia en Málaga del
  Fraunhofer ISE, reproducida en el informe de NERC.
- **El esquema de deslastre:** Procedimiento de Operación P.O. 1.6 de Red
  Eléctrica de España (BOE-A-1998-20053 y BOE-A-2009-8813).
- **El escenario de punta:** cuotas medias de generación por tecnología de
  enero publicadas por REE.
- **El contorno geográfico de los mapas:** [Natural Earth](https://www.naturalearthdata.com/),
  dominio público.

Si utilizas este modelo en un trabajo publicado, cita también el dataset de
Nokandi (2025): la licencia CC BY 4.0 lo exige.

## Cómo colaborar

Los puntos donde más rinde una contribución son los que hoy se apoyan en
reconstrucciones o en valores por tecnología:

- **datos de inercia y estatismo por unidad** del parque español, que
  sustituirían los valores por tecnología de `iberia/dinamica_frecuencia.py`;
- **el despacho real por unidad** de un instante concreto, que permitiría
  construir puntos de operación con compromiso de unidades;
- **la capacidad real de los transformadores** y los límites de emergencia por
  rama.

Cada aporte de datos necesita su fuente citada. Antes de abrir un *pull
request*, las comprobaciones de `tests/` deben pasar.

## Licencia

El código se distribuye bajo licencia MIT; ver [LICENSE](LICENSE). Los datos de
`data/fuentes/` mantienen su licencia original, CC BY 4.0 (ver [Fuentes de
datos](#fuentes-de-datos)).
