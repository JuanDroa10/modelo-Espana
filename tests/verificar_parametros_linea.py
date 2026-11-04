"""Verifica los parametros de linea contra la FISICA, no contra una cifra
documentada.

Por que este test es distinto a los demas del proyecto
------------------------------------------------------
Los otros verificadores comprueban que el modelo reproduce cifras que
nosotros mismos medimos antes. Eso detecta regresiones, pero no detecta un
error que estuviera presente desde el principio - y de hecho no lo detecto:
el doble conteo de `circuits` sobrevivio a todo el desarrollo de los
sub-proyectos A-G porque ninguna cifra publicada tenia con que compararse.

Este test se ancla en constantes fisicas externas al proyecto. La
impedancia caracteristica de una linea aerea

    Zc = sqrt(L/C) ~ sqrt(x_km / b_km)

depende de la geometria de la torre (separacion entre fases y radio
equivalente del haz de conductores), no del modelo. Para lineas aereas de
transporte vale 240-280 ohm en 400 kV, 260-300 en 220 kV y 330-400 en
132 kV, y NINGUNA linea aerea baja de ~200 ohm: habria que enterrarla
(un cable subterraneo tiene Zc de 20-60 ohm, porque su capacidad es ~20x
mayor).

Asi que un Zc de 119 ohm en una linea aerea de 400 kV no es un numero
discutible: es imposible. Eso fue lo que delato el doble conteo.

La otra ancla es la corriente admisible: s_nom = sqrt(3)*V*Imax debe dar
la capacidad de UN circuito, que REE publica en 1.700-2.800 MVA para sus
lineas de 400 kV.
"""
import sys
import warnings
import logging

warnings.filterwarnings('ignore')
logging.disable(logging.INFO)

import numpy as np
import pandas as pd

from iberia import config
import pypsa

# Rangos fisicos de linea AEREA de transporte. Deliberadamente anchos: el
# objetivo es cazar un error de factor 2 o 4, no validar el diseno de la
# torre. Un fallo aqui no significa "ajusta el parametro": significa que
# el calculo tiene un error estructural.
RANGO_ZC = {400.0: (210.0, 300.0),
            220.0: (230.0, 330.0),
            132.0: (300.0, 430.0)}

# Capacidad de UN circuito, en MVA (REE publica 1.700-2.800 para 400 kV).
RANGO_SNOM = {400.0: (1400.0, 3000.0),
              220.0: (250.0, 900.0)}

ZC_MINIMO_AEREO = 200.0   # por debajo de esto no es una linea aerea


def _por_nivel(n):
    """Lineas con su tension nominal, filtrando las que no sirven para
    medir Zc (sin longitud o sin susceptancia)."""
    L = n.lines.copy()
    L['v'] = n.buses.v_nom.reindex(L.bus0).values
    L = L[(L.length > 1.0) & (L.b > 0) & (L.x > 0)].copy()
    L['zc'] = np.sqrt((L.x / L.length) / (L.b / L.length))
    return L


def test_impedancia_caracteristica():
    """EL TEST CENTRAL. Zc = sqrt(x/b) debe caer en el rango fisico."""
    L = _por_nivel(pypsa.Network(config.red('iberia_full_network.nc')))
    fallos = []
    print(f"{'kV':>6} {'n':>6} {'Zc mediana':>11} {'rango fisico':>16}")
    for v, (lo, hi) in sorted(RANGO_ZC.items(), reverse=True):
        s = L[L.v == v]
        if len(s) < 5:
            continue
        zc = float(s.zc.median())
        ok = lo <= zc <= hi
        print(f"{v:6.0f} {len(s):6d} {zc:10.1f}  {lo:7.0f}-{hi:<7.0f} "
              f"{'OK' if ok else '<<< FUERA DE RANGO'}")
        if not ok:
            factor = zc / ((lo + hi) / 2)
            fallos.append(
                f"{v:.0f} kV: Zc mediana {zc:.1f} ohm, fuera de [{lo:.0f}, {hi:.0f}]. "
                f"Es {factor:.2f}x el centro del rango fisico"
                + (f" -> sugiere un doble conteo (factor ~{round(1/factor)}x)"
                   if factor < 0.75 else ""))
    assert not fallos, ("los parametros de linea no son fisicos:\n  "
                        + "\n  ".join(fallos))
    print("OK: la impedancia caracteristica es fisica en todos los niveles")


def test_ninguna_linea_aerea_por_debajo_del_minimo():
    """Ningun caso individual debe bajar de 200 ohm, no solo la mediana."""
    L = _por_nivel(pypsa.Network(config.red('iberia_full_network.nc')))
    bajas = L[L.zc < ZC_MINIMO_AEREO]
    assert len(bajas) == 0, (
        f"{len(bajas)} de {len(L)} lineas tienen Zc < {ZC_MINIMO_AEREO} ohm, "
        f"que es territorio de cable subterraneo, no de linea aerea "
        f"(minimo {bajas.zc.min():.1f} ohm en {bajas.zc.idxmin()}). "
        f"Revisar el calculo de x o de b en build_full_network.py")
    print(f"OK: las {len(L)} lineas tienen Zc >= {ZC_MINIMO_AEREO} ohm")


def test_capacidad_por_circuito():
    """s_nom debe ser la capacidad de UN circuito."""
    L = _por_nivel(pypsa.Network(config.red('iberia_full_network.nc')))
    fallos = []
    for v, (lo, hi) in sorted(RANGO_SNOM.items(), reverse=True):
        s = L[L.v == v]
        if len(s) < 5:
            continue
        sn = float(s.s_nom.median())
        print(f"  {v:.0f} kV: s_nom mediana {sn:.0f} MVA "
              f"(un circuito: {lo:.0f}-{hi:.0f})")
        if not lo <= sn <= hi:
            fallos.append(f"{v:.0f} kV: s_nom mediana {sn:.0f} MVA, fuera de "
                          f"[{lo:.0f}, {hi:.0f}] para UN circuito")
    assert not fallos, ("s_nom no corresponde a un solo circuito:\n  "
                        + "\n  ".join(fallos))
    print("OK: s_nom es la capacidad de un circuito")


def test_cada_fila_es_un_circuito():
    """La premisa del arreglo, comprobada sobre el dato de origen.

    Si esto falla, el CSV de entrada cambio de convencion y hay que
    revisar build_full_network.py antes que nada."""
    d = pd.read_csv(config.dato('line_data.csv'))
    d['base'] = d.line_id.str.replace(r'[a-z]$', '', regex=True)
    g = d.groupby('base').agg(filas=('circuits', 'size'),
                              circ=('circuits', 'first'),
                              circ_u=('circuits', 'nunique'))
    malos = g[(g.filas != g.circ) | (g.circ_u > 1)]
    assert len(malos) == 0, (
        f"{len(malos)} de {len(g)} line_id no cumplen que el numero de filas "
        f"sea igual a su columna `circuits`. La premisa del calculo de "
        f"parametros (una fila = un circuito) ya no se sostiene:\n"
        f"{malos.head(10).to_string()}")
    print(f"OK: los {len(g)} line_id tienen una fila por circuito "
          f"({len(d)} filas, {int(g.circ.sum())} circuitos)")


def test_x_sobre_r_crece_con_la_tension():
    """Comprobacion de cordura invariante al arreglo (X/R viene del dato
    de origen y no lo toca el factor `circuits`, porque afecta igual a r
    y a x). Se incluye para que quede trazado que se miro."""
    L = _por_nivel(pypsa.Network(config.red('iberia_full_network.nc')))
    L = L[L.r > 0]
    xr = {}
    for v in (400.0, 220.0, 132.0):
        s = L[L.v == v]
        if len(s) >= 5:
            xr[v] = float((s.x / s.r).median())
    for v, val in sorted(xr.items(), reverse=True):
        print(f"  {v:.0f} kV: X/R mediana {val:.2f}")
    niveles = sorted(xr, reverse=True)
    for a, b in zip(niveles, niveles[1:]):
        assert xr[a] > xr[b], (
            f"X/R deberia crecer con la tension y {a:.0f} kV ({xr[a]:.2f}) "
            f"no supera a {b:.0f} kV ({xr[b]:.2f})")
    print("OK: X/R crece monotonamente con la tension")


if __name__ == '__main__':
    pruebas = [test_cada_fila_es_un_circuito,
               test_impedancia_caracteristica,
               test_ninguna_linea_aerea_por_debajo_del_minimo,
               test_capacidad_por_circuito,
               test_x_sobre_r_crece_con_la_tension]
    fallos = 0
    for p in pruebas:
        print(f"\n--- {p.__name__} ---")
        try:
            p()
        except AssertionError as e:
            fallos += 1
            print(f"FALLO: {e}")
    print()
    if fallos:
        print(f"{fallos} de {len(pruebas)} verificaciones FALLARON")
        sys.exit(1)
    print("Todas las verificaciones de parametros de linea pasaron.")
