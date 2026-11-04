"""Umbral de penetracion de BTM con inversor: a partir de que punto una
desconexion masiva llega a disparar el deslastre automatico.

Es el gemelo espanol del analisis titular del modelo colombiano
(JUANCHO/menu.py::ana_umbral y ana_sensibilidad). Existe para que las dos
tesis puedan comparar la MISMA magnitud sobre los dos sistemas, no dos
magnitudes parecidas.

    python umbral_penetracion.py                 # barrido + umbral, apagon
    python umbral_penetracion.py --red punta     # sobre la punta nocturna
    python umbral_penetracion.py --sensibilidad  # como se mueve el umbral

POR QUE NO SE PUEDE COPIAR EL DE COLOMBIA TAL CUAL
--------------------------------------------------
El esquema colombiano (Acuerdo 2105) tiene escalones que actuan todos
sobre demanda de clientes. El espanol (P.O. 1.6) tiene SEIS, y los dos
primeros -49,5 y 49,3 Hz- sueltan BOMBEO, no clientes. Soltar bombeo no
es "deslastrar" en el sentido en que lo es cortar a un consumidor: es
una reserva que el operador tiene contratada justamente para esto.

Si se definiera el umbral como "dispara algun escalon", Espana saldria
con un umbral ridiculamente bajo y la comparacion con Colombia seria una
comparacion entre dos cosas distintas. Por eso aqui se informan LOS DOS
umbrales y se dice cual es el comparable:

  - umbral de BOMBEO    : primer escalon de 49,5 Hz. Propio de Espana.
  - umbral GENERAL      : primer escalon de 49,0 Hz, el que corta
                          clientes. ES EL COMPARABLE con Colombia.

La segunda diferencia que hay que tener delante: la fraccion del BTM
conectada por inversor. Colombia 96,9 % (los AGPE de PARATEC); Espana
84,93 % (el resto es cogeneracion, que es sincrona y no se desconecta en
bloque). A igualdad de penetracion, Espana pierde MENOS MW de golpe. La
opcion --fraccion-inversor permite igualar el supuesto y separar cuanto
de la diferencia es del sistema y cuanto del parque.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd
import pypsa

from iberia import config
from iberia import dinamica_frecuencia as din
from iberia.btm_regional import produccion_btm_por_bus
from iberia.deslastre_btm_espana import (FRACCION_INVERSOR_BTM_ESPANA,
                                  aplicar_caida_btm)

# Penetraciones del barrido. Incluye la del propio modelo, que se marca
# en la tabla, y llega hasta el 40 % porque es donde el barrido de lambda
# del proyecto situa el regimen de penetracion alta.
PENETRACIONES = (2.0, 4.0, 6.0, 8.0, 10.0, 12.5, 15.0, 20.0, 25.0, 30.0, 40.0)

CAIDA_POR_DEFECTO = 80.0   # % del BTM con inversor que se desconecta


def _escala_a(btm, carga_total, penetracion_pct):
    """Reescala el BTM del modelo para que represente `penetracion_pct`
    de la demanda, conservando su REPARTO espacial.

    El reparto importa: el MILP de E2 asigna buses a escalones, y un BTM
    repartido de otra forma cambiaria el resultado por una razon que no
    es la penetracion. Aqui solo se mueve el total."""
    objetivo = carga_total * penetracion_pct / 100.0
    actual = float(btm.sum())
    if actual <= 0:
        return btm * 0.0
    return btm * (objetivo / actual)


def _correr(sis, btm, caida_pct, fraccion_inversor, t_btm=0.5,
            con_bombeo=True):
    """Un punto del barrido: cae el BTM, se integra la frecuencia con el
    esquema del P.O. 1.6 activo.

    `t_btm` = 0,5 s NO es inocente. Es el mismo supuesto de temporizacion
    que D4, y el proyecto ya tiene documentado que la cifra de
    aceleracion del colapso por BTM es CONDICIONAL a el. Aqui se deja
    como parametro y se informa en la cabecera, para que nadie cite el
    umbral sin saber de que supuesto cuelga."""
    caido, _ = aplicar_caida_btm(btm, caida_pct,
                                 fraccion_inversor=fraccion_inversor,
                                 semilla=0)
    mw = float(caido.sum())
    eventos = [{'t': t_btm, 'dP_carga': mw, 'etiqueta': 'caida de BTM'}]
    kw = {} if con_bombeo else {'umbrales_bombeo': (), 'fracciones_bombeo': ()}
    _, _, tr = din.simular_frecuencia(sis, eventos, con_deslastre=True, **kw)
    gen = sum(1 for e in tr['escalones'] if e['disparado'])
    bom = sum(1 for e in tr.get('escalones_bombeo', []) if e['disparado'])
    return mw, tr, gen, bom


def barrido(sis, btm0, carga_total, caida_pct, fraccion_inversor,
            penetracion_modelo):
    print(f"\n  {'penetracion':>13} {'BTM cae':>11} {'desenlace':>34} "
          f"{'bombeo':>7} {'general':>8}")
    print("  " + "-" * 78)
    filas = []
    for pen in PENETRACIONES:
        btm = _escala_a(btm0, carga_total, pen)
        mw, tr, gen, bom = _correr(sis, btm, caida_pct, fraccion_inversor)
        marca = ''
        if penetracion_modelo and abs(pen - penetracion_modelo) < 0.75:
            marca = '  <- el del modelo'
        etq = f"{pen:.1f} %"
        print(f"  {etq:>13} {mw:8.1f} MW {din.describir(tr):>34} "
              f"{bom:>7d} {gen:>8d}{marca}")
        filas.append({'penetracion_pct': pen, 'btm_caido_mw': mw,
                      'colapsa': tr['colapso'],
                      'nadir_hz': np.nan if tr['colapso'] else tr['nadir'],
                      't_colapso_s': tr['t_colapso'] if tr['colapso'] else np.nan,
                      'escalones_bombeo': bom, 'escalones_generales': gen})
    return pd.DataFrame(filas)


def buscar_umbral(sis, btm0, carga_total, caida_pct, fraccion_inversor,
                  cual='general', lo=0.5, hi=60.0, iteraciones=18,
                  con_bombeo=True):
    """Biseccion sobre la penetracion hasta el primer disparo.

    Devuelve None si el extremo alto NO dispara: un umbral que no se ha
    encontrado no es lo mismo que un umbral en el extremo del intervalo,
    y devolver `hi` lo haria parecer un resultado."""
    def dispara(pen):
        btm = _escala_a(btm0, carga_total, pen)
        _, _, gen, bom = _correr(sis, btm, caida_pct, fraccion_inversor,
                                 con_bombeo=con_bombeo)
        return (gen if cual == 'general' else bom) > 0

    if not dispara(hi):
        return None
    if dispara(lo):
        return lo      # ya dispara en el extremo bajo: el umbral esta por debajo
    for _ in range(iteraciones):
        mid = (lo + hi) / 2
        if dispara(mid):
            hi = mid
        else:
            lo = mid
    return hi


def sensibilidad(sis, btm0, carga_total):
    """Cuanto se mueve el umbral general si cambian los supuestos.

    Sirve para la misma pregunta que su gemelo colombiano: si el umbral
    es firme o cuelga de lo que no sabemos."""
    casos = [
        ("base del modelo (caida 80 %, inversor 84,9 %)",
         CAIDA_POR_DEFECTO, FRACCION_INVERSOR_BTM_ESPANA, True),
        ("caida total del inversor (100 %)",
         100.0, FRACCION_INVERSOR_BTM_ESPANA, True),
        ("caida parcial (60 %)",
         60.0, FRACCION_INVERSOR_BTM_ESPANA, True),
        ("supuesto de inversor COLOMBIANO (96,9 %)",
         CAIDA_POR_DEFECTO, 0.969, True),
        ("todo el BTM por inversor (100 %)",
         CAIDA_POR_DEFECTO, 1.0, True),
        ("solo la mitad por inversor (50 %)",
         CAIDA_POR_DEFECTO, 0.50, True),
        ("SIN los escalones de bombeo (como Colombia)",
         CAIDA_POR_DEFECTO, FRACCION_INVERSOR_BTM_ESPANA, False),
    ]
    print(f"\n  {'supuesto':>46} {'umbral general':>16}")
    print("  " + "-" * 78)
    for etq, caida, frac, bombeo in casos:
        u = buscar_umbral(sis, btm0, carga_total, caida, frac,
                          con_bombeo=bombeo)
        txt = "no dispara hasta 60 %" if u is None else f"{u:.2f} %"
        print(f"  {etq:>46} {txt:>16}")
    print()
    print("  La ULTIMA fila es la que hay que mirar para comparar con")
    print("  Colombia: mide el mismo sistema espanol con un esquema de")
    print("  deslastre de la misma forma que el colombiano. La distancia")
    print("  entre esa fila y la primera es cuanto del margen espanol lo")
    print("  aporta el bombeo y no la red.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    config.anadir_arg_red(ap)
    ap.add_argument('--caida', type=float, default=CAIDA_POR_DEFECTO,
                    help="%% del BTM con inversor que se desconecta")
    ap.add_argument('--fraccion-inversor', type=float,
                    default=FRACCION_INVERSOR_BTM_ESPANA,
                    help="fraccion del BTM conectada por inversor "
                         "(0,8493 Espana; 0,969 Colombia)")
    ap.add_argument('--sensibilidad', action='store_true',
                    help="ademas del barrido, mueve los supuestos")
    ap.add_argument('--csv', default=None, help="guarda el barrido")
    args = ap.parse_args()

    n = pypsa.Network(config.red_de(args.red))
    sis = din.Sistema(n)
    btm0 = produccion_btm_por_bus(n)
    es = n.buses[n.buses.index.str.startswith('ES')].index
    carga_total = float(n.loads[n.loads.bus.isin(es)].p_set.sum())
    pen_modelo = 100.0 * float(btm0.sum()) / carga_total if carga_total else 0.0

    print("=" * 80)
    print(" UMBRAL DE PENETRACION DE BTM CON INVERSOR")
    print("=" * 80)
    print(f"  punto de operacion : {args.red} "
          f"({config.describir_escenario(args.red)})")
    print(f"  demanda espanola   : {carga_total:.1f} MW")
    print(f"  BTM del modelo     : {float(btm0.sum()):.1f} MW "
          f"({pen_modelo:.2f} % de la demanda)")
    print(f"  caida del inversor : {args.caida:.0f} %   "
          f"fraccion por inversor: {100*args.fraccion_inversor:.1f} %")
    print(f"  inercia            : H = {sis.H:.3f} s | "
          f"S_base = {sis.S_base:.1f} MVA | "
          f"Ek = {sis.H*sis.S_base/1000:.1f} GW.s")
    print(f"  supuesto de tiempo : el BTM cae en t = 0,50 s (el mismo de D4; "
          f"el resultado es CONDICIONAL a el)")

    if float(btm0.sum()) <= 1e-6:
        print("\n  El BTM de este punto de operacion es CERO (escenario "
              "nocturno: el\n  autoconsumo solar no produce). El umbral no "
              "esta definido aqui.\n  Corre el analisis sobre --red apagon.")
        return 0

    d = barrido(sis, btm0, carga_total, args.caida, args.fraccion_inversor,
                pen_modelo)

    u_gen = buscar_umbral(sis, btm0, carga_total, args.caida,
                          args.fraccion_inversor, cual='general')
    u_bom = buscar_umbral(sis, btm0, carga_total, args.caida,
                          args.fraccion_inversor, cual='bombeo')
    print()
    print("  UMBRALES")
    print(f"    bombeo  (49,5 Hz, propio de Espana) : "
          f"{'no dispara' if u_bom is None else f'{u_bom:.2f} %'}")
    print(f"    GENERAL (49,0 Hz, EL COMPARABLE)    : "
          f"{'no dispara' if u_gen is None else f'{u_gen:.2f} %'}")
    print(f"    penetracion actual del modelo       : {pen_modelo:.2f} %")
    if u_gen is not None:
        rel = "POR ENCIMA" if pen_modelo > u_gen else "por debajo"
        print(f"    -> Espana queda {rel} del umbral general")

    if args.sensibilidad:
        print("\n  SENSIBILIDAD DEL UMBRAL GENERAL")
        sensibilidad(sis, btm0, carga_total)

    if args.csv:
        d.to_csv(args.csv, index=False, encoding='utf-8-sig')
        print(f"\n  barrido en {args.csv}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
