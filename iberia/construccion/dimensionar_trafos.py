"""Dimensiona los 179 transformadores por el flujo que de verdad llevan.

EL DEFECTO
----------
`fix_network_v2.py` los creaba a todos iguales: `s_nom=1000, x=0.1,
r=0.01`. Un solo valor para los 179, en una red con niveles 132/220/400
kV y flujos que van de 0,5 a 3.865 MVA. No es un modelo, es un marcador
de posicion - y era el elemento mas cargado de los dos escenarios, asi
que la cifra de "cargabilidad maxima" que el proyecto venia citando
(317,6 % en apagon, 793,5 % en punta) medía sobre todo ese marcador.

QUE SE CORRIGE, Y QUE NO
------------------------
`x = 0,10` p.u. se CONSERVA: va en por-unidad sobre `s_nom` (verificado
en la definicion de atributos de PyPSA) y un 10 % de impedancia de
cortocircuito es correcto - los tipos estandar de PyPSA dan vsc =
12,0-12,2 % para transformadores de transmision.

`r` baja de 0,010 a 0,0025 p.u. Los mismos tipos estandar dan vscr =
0,25 %, asi que el modelo tenia los transformadores ~4 veces mas
resistivos de lo real. Eso inflaba las perdidas (217 MW en apagon, 457
en punta, con unas perdidas ibericas totales del 5,74 % frente al
1,5-2 % real de transmision).

`s_nom` pasa a ser la potencia TOTAL DEL BANCO. Una subestacion no tiene
un transformador sino varios en paralelo; N unidades iguales dan N veces
la potencia y LA MISMA impedancia en p.u. sobre la base combinada, asi
que basta con escalar `s_nom`. (`num_parallel` NO sirve aqui: PyPSA lo
ignora cuando el transformador no tiene `type`, y estos no lo tienen.)

COMO SE DIMENSIONA
------------------
Por el flujo |S| MAXIMO de los DOS puntos de operacion, no de uno. No es
un detalle: la punta manda en 139 de los 179. Dimensionar solo con el
apagon dejaria la mayoria corta en el pico invernal.

    n_unidades = ceil(|S|_max / (MARGEN * unidad))
    s_nom      = n_unidades * unidad

con unidades realistas de REE por nivel de tension y MARGEN = 0,60, que
deja reserva para el N-1.

HONESTIDAD SOBRE ESTA CIFRA
---------------------------
El dimensionado es DERIVADO DEL PROPIO MODELO, no un dato de REE (no se
dispone de su tabla de transformadores). Es mejor que 179 copias de un
numero inventado, pero NO es un dato medido, y asi debe citarse - el
mismo criterio que el escenario de punta.

Y tiene una consecuencia que hay que declarar: la cargabilidad de los
transformadores en el CASO BASE pasa a ser TAUTOLOGICA. Se les ha dado
la potencia necesaria para no ir sobrecargados, asi que que no lo esten
no informa de nada. Lo que si sigue informando:
  - la cargabilidad de las LINEAS, que no se toca;
  - el N-1, donde las contingencias los llevan por encima del caso base.

Uso:
    python dimensionar_trafos.py            # muestra el plan, no escribe
    python dimensionar_trafos.py --aplicar  # lo escribe en las redes
"""
import argparse
import math
import warnings
import logging

warnings.filterwarnings('ignore')
logging.disable(logging.INFO)

import numpy as np
import pandas as pd

from iberia import config
import pypsa

from iberia import analisis_n1 as an
from iberia import limites_reactivos_espana as L

# Potencia de UNA unidad, por par de tensiones (kV). Valores tipicos del
# parque de REE: autotransformadores de 600 MVA en 400/220, y 150 MVA en
# 220/132.
UNIDAD_MVA = {
    (220.0, 400.0): 600.0,
    (132.0, 220.0): 150.0,
    (132.0, 400.0): 300.0,
    (220.0, 225.0): 150.0,
    (320.0, 400.0): 600.0,
}
UNIDAD_POR_DEFECTO = 300.0
MARGEN = 0.60          # carga objetivo en el peor de los dos escenarios
R_PU = 0.0025          # vscr ~ 0,25 %, tipos estandar de PyPSA
X_PU = 0.10            # se conserva: vsc ~ 10-12 %, correcto

REDES = ('escenario', 'apagon', 'punta')
# Los dos puntos de operacion sobre los que se mide el flujo.
ESCENARIOS_FLUJO = ('apagon', 'punta')


def flujo_trafos(red, r_pu):
    """|S| por transformador en el caso base resuelto con limites de Q.

    Se impone `r_pu` ANTES de resolver: la resistencia si entra en el
    flujo (a diferencia de s_nom, que es solo un limite y no afecta a la
    solucion), asi que medir con la r vieja y dimensionar para la nueva
    seria medir otra red.
    """
    n = pypsa.Network(config.red_de(red))
    n.transformers['r'] = r_pu
    an.preparar_para_flujo_ac(n)
    n.pf()
    n_lim, info = L.aplicar(n, verbose=False)
    if not info['convergio']:
        raise RuntimeError(f"el caso base de '{red}' no converge con limites")
    return np.hypot(n_lim.transformers_t.p0.iloc[0],
                    n_lim.transformers_t.q0.iloc[0]).abs()


def plan(verbose=True):
    """Calcula el dimensionado. Devuelve un DataFrame indexado por trafo."""
    flujos = {}
    for red in ESCENARIOS_FLUJO:
        if verbose:
            print(f"  midiendo flujos en '{red}' ...")
        flujos[red] = flujo_trafos(red, R_PU)
    S = pd.concat(flujos.values(), axis=1).max(axis=1)

    n = pypsa.Network(config.red_de('escenario'))
    T = n.transformers
    v0 = n.buses.v_nom.reindex(T.bus0).values
    v1 = n.buses.v_nom.reindex(T.bus1).values

    filas = []
    for k, a, b in zip(T.index, v0, v1):
        unidad = UNIDAD_MVA.get((a, b), UNIDAD_POR_DEFECTO)
        s = float(S.get(k, 0.0))
        nu = max(1, math.ceil(s / (MARGEN * unidad)))
        filas.append({'trafo': k, 'kV': f"{a:.0f}/{b:.0f}", 'S_max_MVA': s,
                      'unidad_MVA': unidad, 'n_unidades': nu,
                      's_nom_MVA': nu * unidad})
    d = pd.DataFrame(filas).set_index('trafo')
    d['carga_pct'] = 100.0 * d.S_max_MVA / d.s_nom_MVA
    for red, s in flujos.items():
        d[f'S_{red}'] = s.reindex(d.index)
    return d


def informar(d):
    print("\nDIMENSIONADO PROPUESTO")
    print(f"  s_nom: min={d.s_nom_MVA.min():.0f}  mediana={d.s_nom_MVA.median():.0f}"
          f"  max={d.s_nom_MVA.max():.0f} MVA")
    print(f"  capacidad instalada: {d.s_nom_MVA.sum():,.0f} MVA "
          f"(antes {len(d)*1000:,} MVA, todos a 1.000)")
    manda_punta = int((d.S_punta > d.S_apagon).sum())
    print(f"  la PUNTA manda en {manda_punta} de {len(d)} trafos")
    print("\n  unidades por banco:")
    for nu, c in d.n_unidades.value_counts().sort_index().items():
        print(f"    {nu:2d} unidad{'es' if nu > 1 else ' '} : {c:4d} trafos")
    print(f"\n  cargabilidad en el peor de los dos escenarios: "
          f"max {d.carga_pct.max():.1f} %")
    grandes = d[d.n_unidades >= 6]
    if len(grandes):
        print(f"\n  AVISO: {len(grandes)} banco(s) con 6 o mas unidades. Una "
              f"subestacion real\n  rara vez pasa de 4-6 autotransformadores: "
              f"eso apunta a que esa rama\n  del modelo esta absorbiendo flujo "
              f"que en la realidad va por varios\n  corredores paralelos que "
              f"la topologia ha colapsado en uno.")
        print(grandes[['kV', 'S_max_MVA', 'n_unidades', 's_nom_MVA']]
              .round(1).to_string(header=True))


def aplicar(d):
    for red in REDES:
        ruta = config.red_de(red)
        n = pypsa.Network(ruta)
        comunes = n.transformers.index.intersection(d.index)
        n.transformers.loc[comunes, 's_nom'] = d.s_nom_MVA.reindex(comunes).values
        n.transformers['r'] = R_PU
        n.transformers['x'] = X_PU
        n.export_to_netcdf(ruta)
        print(f"  escrito {red}: {len(comunes)} trafos, "
              f"s_nom {n.transformers.s_nom.min():.0f}-"
              f"{n.transformers.s_nom.max():.0f} MVA, r={R_PU}, x={X_PU}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--aplicar', action='store_true',
                    help="escribe el resultado en las redes (si no, solo informa)")
    args = ap.parse_args()

    print("DIMENSIONADO DE TRANSFORMADORES POR FLUJO REAL")
    print("=" * 68)
    d = plan()
    informar(d)
    salida = config.salida('dimensionado_trafos.csv')
    d.to_csv(salida, encoding='utf-8-sig')
    print(f"\n  detalle en {salida}")

    if args.aplicar:
        print("\nAPLICANDO a las redes...")
        aplicar(d)
        print("\n  Hecho. Re-corre los verificadores: la red ha cambiado.")
    else:
        print("\n  (no se ha escrito nada; usa --aplicar)")


if __name__ == '__main__':
    main()
