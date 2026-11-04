"""Barrido de lambda contra el eje de REGIMEN NORMAL - el que nunca se probo.

Por que existe
--------------
`calibrar_lambda_espana.py` valida LAMBDA_BTM_ESPANA=25 contra el EVENTO
(CAIDA_PCT=80%, una caida masiva de BTM). Eso deja sin probar el otro
eje: demanda ordinaria, SIN ningun evento, con el BTM simplemente
conectado y sano. Y ese es exactamente el eje que en Colombia revelo el
"precipicio" - un lambda que parecia seguro contra el evento resultaba
APAGAR el esquema por completo en operacion normal a partir de cierta
penetracion (ver la memoria stn-btm-lambda-precipicio).

El mecanismo: lambda penaliza tocar barras con BTM SANO. En regimen
normal TODO el BTM esta sano, asi que la penalizacion es maxima. Si
lambda es alto y la penetracion tambien, al optimizador puede salirle
mas barato no deslastrar que tocar una barra con BTM.

LA HIPOTESIS QUE ESTO PONE A PRUEBA. Con la restriccion de suficiencia
DURA (`e_min >= requisito` en milp_asignacion), lambda solo puede elegir
ENTRE PLANES SUFICIENTES: no puede deslastrar de menos. Si la hipotesis
es correcta, NO debe aparecer ningun precipicio a ninguna penetracion.
Este barrido lo confirma o lo refuta; hasta ahora era una conjetura
razonada, no un resultado medido.

Que se mide
-----------
Para cada (lambda, penetracion): el porcentaje del objetivo del ULTIMO
escalon del P.O. 1.6 que el plan del MILP llega a cubrir. Es la misma
cantidad que vigila `verificar_guarda_lambda()` en tiempo de ejecucion.

  100% o mas  -> el esquema planifica lo que debe
  < 75%       -> la guarda salta: el esquema esta efectivamente apagado

El objetivo se calcula sobre la DEMANDA MEDIDA (`demanda_medida * f`),
igual que `ejecutar_espana`. OJO: `calibrar_lambda_espana.py` todavia usa
la formula vieja (`alv[sc].sum() * f`), que infla la base con el BTM
estimado; ver el bloque de comentarios de ejecutar_espana sobre por que
se abandono.

Uso:
    python barrido_lambda_normal.py
    python barrido_lambda_normal.py --semillas 3 --rapido
"""
import argparse
import warnings
import logging

warnings.filterwarnings('ignore')
logging.disable(logging.INFO)

import numpy as np
import pandas as pd

from iberia import config
import pypsa

from iberia import deslastre_btm_espana as D
from iberia.btm_regional import produccion_btm_por_bus, region_de_bus

# SIN EVENTO. Esta es toda la diferencia con calibrar_lambda_espana.py.
CAIDA_PCT_NORMAL = 0.0

# Se incluye 100 a proposito, muy por encima del adoptado (25): si hay
# precipicio en algun sitio, es hacia alla.
CANDIDATOS_LAMBDA = (0.5, 5.0, 25.0, 100.0)

# Penetracion = BTM PRODUCIENDO / demanda espanola. La real del apagon es
# ~18,6%; el precipicio colombiano aparecio hacia el 40%, asi que se
# barre bastante por encima para cubrirlo.
PENETRACIONES_PCT = (0.0, 10.0, 18.6, 30.0, 40.0, 60.0)

FRACCION_ACUMULADA = [0.15, 0.30, 0.40, 0.50]
UMBRAL_GUARDA_PCT = 75.0


def evaluar(carga, btm, region, lam, semilla):
    """Un punto del barrido. Devuelve (% del objetivo, BTM sano tocado)."""
    btm_est = D.estimar_btm(btm, region, semilla=semilla)
    # caida 0: nada se cae, todo el BTM queda SANO y penalizable
    _, resto_est = D.aplicar_caida_btm(btm_est, CAIDA_PCT_NORMAL,
                                       semilla=semilla)
    _, resto_real = D.aplicar_caida_btm(btm, CAIDA_PCT_NORMAL,
                                        semilla=semilla)
    alv, piso = D.escenarios_alivio(carga, btm_est, CAIDA_PCT_NORMAL,
                                    semilla=semilla)
    demanda_medida = float(carga.sum())
    objetivos = pd.DataFrame({
        sc: [demanda_medida * f for f in FRACCION_ACUMULADA]
        for sc in alv.columns})
    asign = D.milp_asignacion(alv, resto_est, objetivos, lam=lam,
                              alivio_piso=piso, verbose=False)
    elegidos = asign.index[asign.sum(axis=1) > 0]
    plan = float(piso.reindex(elegidos).fillna(0.0).sum())
    meta = float(objetivos.iloc[-1].mean())
    sano = float(resto_real.reindex(elegidos).fillna(0.0).sum())
    return (100.0 * plan / meta if meta > 0 else 0.0), sano


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--semillas', type=int, default=2,
                    help="semillas del estimador por punto (defecto 2)")
    ap.add_argument('--rapido', action='store_true',
                    help="solo lambda 25 y 3 penetraciones, para una prueba")
    args = ap.parse_args()

    lambdas = (25.0,) if args.rapido else CANDIDATOS_LAMBDA
    penetraciones = (18.6, 40.0, 60.0) if args.rapido else PENETRACIONES_PCT

    n = pypsa.Network(config.red_de('apagon'))
    btm_real = produccion_btm_por_bus(n)
    es_buses = n.buses[n.buses.index.str.startswith('ES')].index
    carga = n.loads.groupby('bus').p_set.sum().reindex(es_buses).fillna(0.0)
    carga = carga[carga > 0]
    region = {b: region_de_bus(n.buses.at[b, 'x'], n.buses.at[b, 'y'])
              for b in btm_real.index}
    demanda = float(carga.sum())
    pen_real = 100.0 * float(btm_real.sum()) / demanda

    print("BARRIDO DE LAMBDA EN REGIMEN NORMAL (sin evento de BTM)")
    print("=" * 68)
    print(f"  demanda espanola      : {demanda:,.1f} MW")
    print(f"  BTM produciendo real  : {btm_real.sum():,.1f} MW "
          f"({pen_real:.1f} % de penetracion)")
    print(f"  objetivo del escalon 4: {demanda * 0.50:,.1f} MW (50 % de la demanda)")
    print(f"  la guarda salta por debajo del {UMBRAL_GUARDA_PCT:.0f} %")
    print()

    filas = []
    for pen in penetraciones:
        # escalar el BTM por bus para alcanzar la penetracion pedida,
        # conservando su reparto espacial
        factor = (pen / pen_real) if pen_real > 0 else 0.0
        btm = (btm_real * factor).round(6)
        for lam in lambdas:
            pcts, sanos = [], []
            for s in range(args.semillas):
                p, sa = evaluar(carga, btm, region, lam, s)
                pcts.append(p); sanos.append(sa)
            pct, sano = float(np.mean(pcts)), float(np.mean(sanos))
            apagado = pct < UMBRAL_GUARDA_PCT
            filas.append({'penetracion_pct': pen, 'lambda': lam,
                          'btm_MW': float(btm.sum()),
                          'pct_objetivo': round(pct, 1),
                          'btm_sano_tocado_MW': round(sano, 1),
                          'esquema_apagado': apagado})
            print(f"  penetracion {pen:5.1f} %  lambda {lam:6g}  ->  "
                  f"{pct:6.1f} % del objetivo   "
                  f"{sano:8.1f} MW de BTM sano tocado"
                  f"{'   <<< PRECIPICIO' if apagado else ''}")

    d = pd.DataFrame(filas)
    salida = config.salida('barrido_lambda_normal.csv')
    d.to_csv(salida, index=False, encoding='utf-8-sig')

    print()
    print("--- Veredicto ---")
    if d.esquema_apagado.any():
        peor = d[d.esquema_apagado]
        print(f"  HAY PRECIPICIO en {len(peor)} de {len(d)} puntos. El menor "
              f"lambda afectado es {peor['lambda'].min():g} y la menor "
              f"penetracion, {peor.penetracion_pct.min():.1f} %.")
        print("  LAMBDA_BTM_ESPANA debe bajarse por debajo de ese valor.")
    else:
        print(f"  NO hay precipicio en ninguno de los {len(d)} puntos "
              f"({d.pct_objetivo.min():.1f} % el peor).")
        print("  Es lo que predecia la restriccion de suficiencia DURA: "
              "lambda\n  solo elige ENTRE PLANES SUFICIENTES, y por tanto no "
              "puede apagar\n  el esquema. El riesgo que el codigo declaraba "
              "abierto queda CERRADO.")
    print(f"\n  CSV en {salida}")


if __name__ == '__main__':
    main()
