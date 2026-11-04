"""Rutas del proyecto y puntos de operacion del modelo.

Todas las rutas se resuelven desde la posicion de ESTE fichero, no desde el
directorio de trabajo: da igual desde donde se lance el menu o un modulo
(`python -m iberia.analisis_n1`), las rutas son las mismas.

    data/fuentes/      los CSV de entrada y el contorno geografico
    data/redes/        las redes PyPSA (.nc) de cada punto de operacion
    data/referencia/   barridos N-1 de referencia incluidos en el repositorio
    resultados/        todas las salidas; se crea sola la primera vez
"""
import logging
from pathlib import Path


class _SinAvisoDeVersion(logging.Filter):
    """Oculta UN aviso de PyPSA: el de que una red se guardo con otra version.

    Las redes de data/redes/ se guardaron con PyPSA 1.3. Con 1.4 el aviso sale
    en CADA carga de red, y se ha comprobado que los resultados son identicos
    con las dos versiones (validacion, umbral, deslastre, cascada, N-1, tests).
    Cualquier otro aviso de PyPSA sigue saliendo."""

    def filter(self, registro):
        return not registro.getMessage().startswith(
            'Importing network from PyPSA version')


logging.getLogger('pypsa.network.io').addFilter(_SinAvisoDeVersion())

#: Raiz del repositorio: la carpeta que contiene `iberia/`.
RAIZ = Path(__file__).resolve().parent.parent
DIR_PROYECTO = RAIZ                      # nombre historico, se conserva

DIR_DATOS = RAIZ / "data" / "fuentes"
DIR_REDES = RAIZ / "data" / "redes"
DIR_REFERENCIA = RAIZ / "data" / "referencia"
DIR_RESULTADOS = RAIZ / "resultados"
DIR_VISUALIZACIONES = DIR_RESULTADOS / "visualizaciones"
DIR_MAPAS = DIR_RESULTADOS / "mapas"


def dato(nombre):
    """Ruta a un fichero de entrada en data/fuentes/."""
    return str(DIR_DATOS / nombre)


def red(nombre):
    """Ruta a una red PyPSA (.nc) en data/redes/."""
    return str(DIR_REDES / nombre)


def salida(nombre):
    """Ruta de un fichero de resultados en resultados/, creando la carpeta."""
    DIR_RESULTADOS.mkdir(parents=True, exist_ok=True)
    return str(DIR_RESULTADOS / nombre)


def visualizacion(nombre):
    """Ruta de una figura en resultados/visualizaciones/, creando la carpeta."""
    DIR_VISUALIZACIONES.mkdir(parents=True, exist_ok=True)
    return str(DIR_VISUALIZACIONES / nombre)


def mapa(nombre):
    """Ruta de un mapa en resultados/mapas/, creando la carpeta."""
    DIR_MAPAS.mkdir(parents=True, exist_ok=True)
    return str(DIR_MAPAS / nombre)


# --- Los puntos de operacion del modelo ----------------------------------
#
# Hasta ahora cada analisis tenia su red cableada: el N-1 sobre el
# escenario generico y la dinamica sobre el apagon. Eso significaba que
# las contingencias y el BTM se estudiaban en PUNTOS DE OPERACION
# DISTINTOS, asi que no eran resultados del mismo sistema. Con este
# registro los tres analisis aceptan --red y se pueden comparar entre si.
ESCENARIOS = {
    'escenario': ('iberia_scenario.nc',
                  'exportacion generica de 3.000 MW (despacho uniforme)'),
    'apagon':    ('iberia_blackout.nc',
                  '28-abr-2025 12:33, solar dominante (18 GW de FV)'),
    'punta':     ('iberia_punta.nc',
                  '15-ene 20-21 h, punta invernal nocturna, solar CERO'),
}
ESCENARIO_POR_DEFECTO = 'apagon'


def red_de(nombre):
    """Ruta del .nc de un punto de operacion, por su nombre corto."""
    if nombre not in ESCENARIOS:
        raise SystemExit(
            f"Escenario '{nombre}' desconocido. Disponibles:\n  " +
            "\n  ".join(f"{k:10s} {d}" for k, (_, d) in ESCENARIOS.items()))
    return red(ESCENARIOS[nombre][0])


def describir_escenario(nombre):
    return ESCENARIOS.get(nombre, ('', '?'))[1]


def anadir_arg_red(ap, por_defecto=ESCENARIO_POR_DEFECTO):
    """Anade --red a un ArgumentParser, con la ayuda ya formateada."""
    ap.add_argument('--red', choices=list(ESCENARIOS),
                    default=por_defecto,
                    help="punto de operacion: " + " | ".join(
                        f"{k} ({d})" for k, (_, d) in ESCENARIOS.items()))
    return ap
