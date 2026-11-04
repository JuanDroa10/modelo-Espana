"""Pasa DOS puntos de operacion por la MISMA bateria de pruebas y los
presenta uno al lado del otro.

Por que existe
--------------
El modelo tiene dos puntos de operacion que son casi opuestos:

    apagon  28-abr-2025 12:33  DIURNO   18 GW de FV, inercia minima
    punta   15-ene 20-21 h     NOCTURNO solar CERO, inercia maxima

Hasta ahora cada uno se medía con el script que tocara y con la bateria
que a ese script le daba la gana, asi que las cifras no eran
comparables: el N-1 se corria sobre uno y la dinamica sobre el otro, y
`estado_actual.py` cablea `iberia_scenario.nc` para la red e
`iberia_blackout.nc` para la dinamica. Comparar dos columnas medidas con
reglas distintas es justo el error que este proyecto lleva diez veces
cometiendo.

Aqui la bateria es UNA, el codigo que la ejecuta es EL MISMO, y lo unico
que cambia entre las dos columnas es el .nc de entrada. Si una cifra
difiere, la diferencia es del punto de operacion y de nada mas.

Que NO hace: el barrido N-1 completo (~18 h por escenario). Hace una
muestra dirigida a los elementos mas cargados, que es donde aparecen las
violaciones, y lo dice en la cabecera para que nadie lo confunda con el
barrido entero.

Uso:
    python comparar_escenarios.py                 # apagon vs punta
    python comparar_escenarios.py --n1 0          # sin muestra N-1 (rapido)
    python comparar_escenarios.py --redes punta escenario
    python comparar_escenarios.py --md            # Markdown, para pegar
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

from iberia import analisis_n1 as an
from iberia import dinamica_frecuencia as din
from iberia import limites_reactivos_espana as L
from iberia.analisis_btm_cascada import escenario_real
from iberia.btm_regional import (capacidad_btm_por_bus, produccion_btm_por_bus,
                          factor_produccion)


def _f(x, dec=1):
    """Numero en notacion espanola (1.234,5)."""
    if x is None or (isinstance(x, float) and (np.isnan(x) or np.isinf(x))):
        return "n/d"
    return f"{x:,.{dec}f}".replace(",", "@").replace(".", ",").replace("@", ".")


def buses_de(n, prefijo):
    return n.buses[n.buses.index.str.startswith(prefijo)].index


# --------------------------------------------------------------------------
# La bateria. Una funcion por bloque; todas reciben lo mismo y devuelven
# un dict {etiqueta: (valor_formateado, nota)} para que la comparacion
# final sea mecanica.
# --------------------------------------------------------------------------

def bloque_red(n):
    return {
        'buses': (_f(len(n.buses), 0), ''),
        'lineas': (_f(len(n.lines), 0), ''),
        'transformadores': (_f(len(n.transformers), 0), ''),
        'generadores': (_f(len(n.generators), 0), ''),
        'cargas': (_f(len(n.loads), 0), ''),
        'reactores shunt': (_f(len(n.shunt_impedances), 0), ''),
    }


def bloque_balance(n):
    out = {}
    for pref, nombre in (('ES', 'Espana'), ('PT', 'Portugal'), ('FR', 'Francia')):
        b = buses_de(n, pref)
        g = float(n.generators[n.generators.bus.isin(b)].p_set.sum())
        d = float(n.loads[n.loads.bus.isin(b)].p_set.sum())
        out[f'{nombre}: demanda [MW]'] = (_f(d), '')
        out[f'{nombre}: generacion [MW]'] = (_f(g), '')
        out[f'{nombre}: balance [MW]'] = (_f(g - d), 'gen - dem')

    es = buses_de(n, 'ES')
    g = n.generators[n.generators.bus.isin(es)]
    # Mix espanol por tecnologia, solo lo que de verdad esta despachado.
    mix = g.groupby('carrier').p_set.sum()
    mix = mix[mix.abs() > 1.0].sort_values(ascending=False)
    total_pos = float(mix[mix > 0].sum())
    for carrier, mw in mix.items():
        pct = 100.0 * mw / total_pos if total_pos else 0.0
        out[f'  mix ES: {carrier}'] = (
            _f(mw), f"{pct:.1f} %".replace('.', ',') if mw > 0 else 'CONSUMO')
    return out


def bloque_flujo(red):
    """Flujo de potencia AC con limites de reactivo aplicados.

    OJO con `analisis_n1.caso_base`: devuelve la red SIN conmutar pero el
    diagnostico CON limites, y mezclarlos da un caso base incoherente (lo
    dice su propio docstring). Aqui se resuelve y se conmuta en el mismo
    sitio, asi que la red que se mide y las cifras que se informan son el
    mismo estado.
    """
    n = pypsa.Network(config.red_de(red))
    slack = an.preparar_para_flujo_ac(n)
    res = n.pf()
    convergio_sin = bool(res['converged'].iloc[0, 0])
    if not convergio_sin:
        return None, {'converge sin limites de Q': ('NO', 'el caso base no resuelve')}

    n_lim, info = L.aplicar(n, verbose=False)
    out = {'slack': (str(slack), 'designado'),
           'converge sin limites de Q': ('si', ''),
           'converge con limites de Q': ('si' if info['convergio'] else 'NO', '')}
    if not info['convergio']:
        return None, out

    d = an.estado(n_lim)
    gen = float(n_lim.generators_t.p.iloc[0].sum())
    car = float(n_lim.loads_t.p.iloc[0].sum())
    perd = gen - car
    p_lin = float((n_lim.lines_t.p0.iloc[0] + n_lim.lines_t.p1.iloc[0]).sum())
    p_tra = float((n_lim.transformers_t.p0.iloc[0]
                   + n_lim.transformers_t.p1.iloc[0]).sum())
    q_gen = float(n_lim.generators_t.q.iloc[0].sum())
    q_car = float(n_lim.loads_t.q.iloc[0].sum())

    # PERDIDAS IBERICAS, aparte del total.
    #
    # Francia son 4 buses ficticios que representan un pais entero (un
    # generador por tecnologia), asi que sus ~58 GW de demanda y las
    # perdidas de sus ramas no son fisicas: son el precio de tener una
    # condicion de contorno. Citar "perdidas del 2,0 %" sobre una base
    # que es 2/3 proxy frances no significa nada. La cifra que vale es la
    # de las ramas con los DOS extremos en Iberia.
    ib = set(buses_de(n_lim, 'ES')) | set(buses_de(n_lim, 'PT'))
    def _perd_ib(tabla, tt):
        if not len(tabla):
            return 0.0
        m = tabla.bus0.isin(ib) & tabla.bus1.isin(ib)
        if not m.any():
            return 0.0
        return float((tt.p0.iloc[0][m.values] + tt.p1.iloc[0][m.values]).sum())
    perd_ib = (_perd_ib(n_lim.lines, n_lim.lines_t)
               + _perd_ib(n_lim.transformers, n_lim.transformers_t))
    dem_ib = float(n_lim.loads_t.p.iloc[0][
        n_lim.loads.bus.isin(ib).values].sum())

    out.update({
        'generacion resuelta [MW]': (_f(gen), 'tras el flujo, no p_set'),
        'demanda resuelta [MW]': (_f(car), 'incluye el proxy frances'),
        'perdidas totales [MW]': (_f(perd), 'con Francia, no citable'),
        '  en lineas [MW]': (_f(p_lin), ''),
        '  en trafos [MW]': (_f(p_tra), ''),
        'PERDIDAS IBERICAS [MW]': (_f(perd_ib), 'ramas ES/PT, la cifra buena'),
        'perdidas ibericas [% dem. ES+PT]': (
            f"{100*perd_ib/dem_ib:.2f} %".replace('.', ',') if dem_ib else 'n/d', ''),
        'Q generada [MVAr]': (_f(q_gen), ''),
        'Q de la demanda [MVAr]': (_f(q_car), 'cos phi = 1, por diseno'),
        'tension minima [p.u.]': (_f(d['v_min'], 4), ''),
        'tension maxima [p.u.]': (_f(d['v_max'], 4), ''),
        'barras con tension baja': (_f(len(d['v_bajas']), 0), f"< {an.V_MIN}"),
        'barras con tension alta': (_f(len(d['v_altas']), 0), f"> {an.V_MAX}"),
        'cargabilidad maxima [%]': (_f(d['carga_max_pct']), ''),
        'elementos sobrecargados': (_f(len(d['sobrecargados']), 0),
                                    f"> {an.CARGA_MAX_PCT} %"),
        'generadores conmutados a PQ': (_f(len(info['conmutados']), 0), ''),
        'siguen fuera de su curva Q': (_f(len(info['restantes']), 0), ''),
    })

    # VEREDICTO. Un caso base que converge NO es lo mismo que un caso
    # base valido: Newton-Raphson resuelve encantado una red con barras a
    # 0,66 p.u. y ramas al 800%, porque nada en el algoritmo impide que
    # el punto de equilibrio sea fisicamente absurdo. Sin esta linea es
    # facil leer "converge: si" y dar por bueno un escenario que no se
    # sostiene - y entonces cualquier N-1 lanzado encima mide ruido.
    motivos = []
    if d['carga_max_pct'] > an.CARGA_MAX_PCT:
        motivos.append(f"{len(d['sobrecargados'])} sobrecargas "
                       f"(max {d['carga_max_pct']:.0f} %)")
    if d['v_bajas']:
        motivos.append(f"{len(d['v_bajas'])} barras bajo {an.V_MIN} p.u. "
                       f"(min {d['v_min']:.3f})")
    if d['v_altas']:
        motivos.append(f"{len(d['v_altas'])} barras sobre {an.V_MAX} p.u.")
    if len(info['restantes']):
        motivos.append(f"{len(info['restantes'])} generadores fuera de su "
                       f"curva Q")
    out['CASO BASE UTILIZABLE'] = (
        'si' if not motivos else 'NO', '; '.join(motivos))
    return n_lim, out


def bloque_permanente(n_lim):
    """Como opera el sistema FUNCIONANDO: sin contingencia, sin
    perturbacion, sin deslastre. El regimen permanente resuelto.

    Los bloques de dinamica y N-1 responden "que pasa cuando algo falla".
    Este responde "como esta el sistema mientras no falla nada", que es
    una pregunta distinta y es la que hay que contestar primero: si el
    permanente no se sostiene, todo lo que se simule encima es ruido.
    """
    out = {}

    # --- Intercambios por las interconexiones, con signo ---
    #
    # Se orienta SIEMPRE de `a` hacia `b`. Sin eso, las ramas definidas
    # al reves entran con el signo cambiado y los dos sentidos se
    # cancelan: el intercambio sale ~0 y parece que no fluye nada.
    intercambio = {}
    for tabla, tt in ((n_lim.lines, n_lim.lines_t),
                      (n_lim.transformers, n_lim.transformers_t)):
        if not len(tabla) or not len(tt.p0):
            continue
        # El pais va en el prefijo del nombre del bus (ES.../PT.../FR...),
        # que es lo mismo que usa buses_de() en el resto del modulo.
        p0 = tabla.bus0.str[:2]
        p1 = tabla.bus1.str[:2]
        for a, b in (('ES', 'PT'), ('ES', 'FR'), ('PT', 'FR')):
            directa = (p0 == a) & (p1 == b)
            inversa = (p0 == b) & (p1 == a)
            if not (directa.any() or inversa.any()):
                continue
            mw = float(tt.p0.iloc[0][directa].sum()
                       + tt.p1.iloc[0][inversa].sum())
            intercambio[(a, b)] = intercambio.get((a, b), 0.0) + mw
    for (a, b), mw in intercambio.items():
        out[f'intercambio {a} -> {b} [MW]'] = (
            _f(mw), f"positivo = {a} exporta a {b}")

    # --- Perfil de tension ---
    v = n_lim.buses_t.v_mag_pu.iloc[0]
    out['tension: percentil 1 [p.u.]'] = (_f(float(v.quantile(0.01)), 4), '')
    out['tension: mediana [p.u.]'] = (_f(float(v.median()), 4), '')
    out['tension: percentil 99 [p.u.]'] = (_f(float(v.quantile(0.99)), 4), '')
    for lo, hi, etq in ((0.0, 0.90, '< 0,90 (baja)'),
                        (0.90, 0.95, '0,90-0,95'),
                        (0.95, 1.05, '0,95-1,05 (sana)'),
                        (1.05, 1.10, '1,05-1,10'),
                        (1.10, 9.9, '> 1,10 (alta)')):
        cnt = int(((v >= lo) & (v < hi)).sum())
        out[f'  barras {etq}'] = (
            f"{cnt} ({100*cnt/len(v):.1f} %)".replace('.', ','), '')

    # --- Reparto de cargabilidad ---
    pct = an.cargabilidad(n_lim)
    if len(pct):
        out['cargabilidad: mediana [%]'] = (_f(float(pct.median())), '')
        out['cargabilidad: percentil 95 [%]'] = (_f(float(pct.quantile(0.95))), '')
        for lo, hi, etq in ((0, 50, '< 50 %'), (50, 80, '50-80 %'),
                            (80, 100, '80-100 %'), (100, 1e9, '> 100 % (sobrecarga)')):
            cnt = int(((pct >= lo) & (pct < hi)).sum())
            out[f'  ramas al {etq}'] = (
                f"{cnt} ({100*cnt/len(pct):.1f} %)".replace('.', ','), '')
        top = pct.sort_values(ascending=False).head(3)
        for i, (nombre, val) in enumerate(top.items(), 1):
            out[f'  rama mas cargada #{i}'] = (_f(val) + ' %', str(nombre))

    # --- Generacion y reactivo resueltos, por tecnologia espanola ---
    es = buses_de(n_lim, 'ES')
    g = n_lim.generators[n_lim.generators.bus.isin(es)]
    p = n_lim.generators_t.p.iloc[0].reindex(g.index)
    q = n_lim.generators_t.q.iloc[0].reindex(g.index)
    porq = q.groupby(g.carrier).sum().sort_values()
    for carrier, mvar in porq.items():
        if abs(mvar) > 1.0:
            out[f'  Q resuelta ES: {carrier} [MVAr]'] = (_f(mvar), '')
    out['Q total generadores ES [MVAr]'] = (_f(float(q.sum())), '')

    # --- Compensacion shunt en servicio ---
    sh = n_lim.shunt_impedances
    if len(sh):
        vn = n_lim.buses.v_nom.reindex(sh.bus).values
        mvar = float((-sh.b.values * vn ** 2).sum())
        out['reactores shunt [MVAr]'] = (_f(mvar), 'instalados, signo inductivo')
    return out


def bloque_inercia(n):
    """Inercia y reserva DISPONIBLES en permanente. No hay falla aqui:
    son propiedades del despacho, no de ningun evento."""
    sis = din.Sistema(n)
    ek = sis.H * sis.S_base / 1000.0
    return sis, {
        'capacidad girando S_base [MVA]': (_f(sis.S_base), ''),
        'inercia equivalente H [s]': (_f(sis.H, 3), 'sobre S_base'),
        'ENERGIA CINETICA [GW.s]': (_f(ek), ''),
        'energia cinetica [s de demanda]': (
            _f(1000 * ek / sis.P_carga, 2), 'base ES+PT'),
        'reserva primaria [MW]': (_f(sis.reserva), ''),
        'reserva [% de la demanda ES]': (
            f"{100*sis.reserva/sis.P_carga_es:.2f} %".replace('.', ','), ''),
        'bombeo espanol en consumo [MW]': (_f(sis.P_bombeo_es), ''),
        'exportacion neta Iberia [MW]': (_f(sis.exportacion), ''),
    }


def bloque_perturbacion(n, sis):
    """Aqui SI hay falla: la cascada del 28-A evaluada en este punto."""
    esc = escenario_real(n, sis)
    dP = next((e.get('dP_gen', 0.0) for e in esc if e.get('dP_gen', 0.0) > 0), 0.0)
    rocof = -dP / (2.0 * sis.H * sis.S_base) * din.F0 if sis.S_base else np.nan
    total = sum(e.get('dP_gen', 0.0) for e in esc)
    return {
        'perturbacion total [MW]': (_f(total), 'topada en lo despachado'),
        'perturbacion [% de la demanda ES]': (
            f"{100*total/sis.P_carga_es:.1f} %".replace('.', ','), ''),
        'primer escalon de la cascada [MW]': (_f(dP), ''),
        'RoCoF inicial [Hz/s]': (_f(rocof, 3), 'analitico'),
    }


def bloque_btm(n, sis):
    cap = capacidad_btm_por_bus(n)
    prod = produccion_btm_por_bus(n)
    fp = factor_produccion(n)
    return {
        'BTM instalado, placa [MW]': (_f(cap.sum()), 'dato REE'),
        'factor de produccion': (_f(fp, 3), 'FV del propio snapshot'),
        'BTM PRODUCIENDO [MW]': (_f(prod.sum()), 'lo que puede caerse'),
        'penetracion BTM / demanda ES': (
            f"{100*prod.sum()/sis.P_carga_es:.1f} %".replace('.', ','), ''),
    }


def bloque_deslastre(n, sis):
    esc = escenario_real(n, sis)
    mw_evento = sum(e.get('dP_gen', 0.0) for e in esc)
    casos = [
        ('sin deslastre', dict(con_deslastre=False)),
        ('solo 4 generales', dict(con_deslastre=True, umbrales_bombeo=(),
                                  fracciones_bombeo=())),
        ('los SEIS escalones', dict(con_deslastre=True)),
    ]
    out = {}
    for etiqueta, kw in casos:
        _, _, tr = din.simular_frecuencia(sis, esc, **kw)
        out[f'P.O. 1.6 - {etiqueta}'] = (din.describir(tr), '')
    return out


def bloque_n1(n_base, red, cuantos):
    """Muestra DIRIGIDA, no el barrido completo.

    Se eligen los elementos mas cargados del caso base: es donde se
    concentran las violaciones, asi que una muestra pequena ahi dice mas
    que una aleatoria grande. NO es una cobertura N-1 y no debe citarse
    como tal.
    """
    if cuantos <= 0:
        return {'muestra N-1': ('omitida', '--n1 0')}
    # caso_base devuelve (red, diagnostico); simular() hace base.copy() y
    # necesita la RED. Pasarle la tupla entera no explota de forma
    # visible: revienta dentro del try y sale como "no convergio", que es
    # indistinguible de un resultado fisico. Costo: una tanda entera
    # leida como "8 de 8 no convergen".
    base_n, _ = an.caso_base(verbose=False, con_limites=True, red=red)
    pct = an.cargabilidad(base_n)
    objetivos = list(pct.sort_values(ascending=False).head(cuantos).index)
    lineas = set(n_base.lines.index)
    res = []
    for nombre in objetivos:
        tipo = 'Line' if nombre in lineas else 'Transformer'
        r = an.simular(base_n, tipo, nombre, con_limites=True)
        if r is not None:
            res.append(r)
    if not res:
        return {'muestra N-1': ('vacia', 'ningun elemento simulable')}
    d = pd.DataFrame(res)
    sob = (d.n_sobrecargas > 0) if 'n_sobrecargas' in d else pd.Series(False, index=d.index)
    nc = (~d.convergio) if 'convergio' in d else pd.Series(False, index=d.index)
    desc = (d.MW_desconectados > 0.1) if 'MW_desconectados' in d else pd.Series(False, index=d.index)
    limpio = ~(sob | nc | desc)
    out = {
        'muestra N-1 (dirigida)': (_f(len(d), 0), 'los mas cargados'),
        '  sin problemas': (f"{int(limpio.sum())} de {len(d)}", ''),
        '  con sobrecargas': (_f(int(sob.sum()), 0), ''),
        '  no convergen': (_f(int(nc.sum()), 0), ''),
    }
    if 'MW_desconectados' in d and desc.any():
        peor = d.loc[d.MW_desconectados.idxmax()]
        out['  peor desconexion [MW]'] = (
            _f(float(peor.MW_desconectados)), str(peor.elemento))
    return out


# La bateria esta partida en dos mitades y la etiqueta lo dice en cada
# cabecera, porque son preguntas distintas y se habian venido mezclando:
# [NORMAL] es el sistema operando sin que falle nada, [FALLA] es su
# respuesta a una perturbacion. El orden no es cosmetico - si el
# permanente no se sostiene, las cifras de [FALLA] no significan nada.
BLOQUES = [
    '1. Topologia de la red',
    '2. Balance y mix despachado          [NORMAL]',
    '3. Flujo de potencia AC              [NORMAL]',
    '4. Regimen permanente: como opera    [NORMAL]',
    '5. Inercia y reserva disponibles     [NORMAL]',
    '6. BTM presente                      [NORMAL]',
    '7. La perturbacion aplicada          [FALLA]',
    '8. Deslastre P.O. 1.6                [FALLA]',
    '9. Muestra N-1 dirigida              [FALLA]',
]


def evaluar(red, cuantos_n1):
    """Toda la bateria sobre un punto de operacion."""
    n = pypsa.Network(config.red_de(red))
    r = {}
    r[BLOQUES[0]] = bloque_red(n)
    r[BLOQUES[1]] = bloque_balance(n)
    n_lim, flujo = bloque_flujo(red)
    r[BLOQUES[2]] = flujo
    r[BLOQUES[3]] = bloque_permanente(n_lim) if n_lim is not None else {}
    sis, inercia = bloque_inercia(n)
    r[BLOQUES[4]] = inercia
    r[BLOQUES[5]] = bloque_btm(n, sis)
    r[BLOQUES[6]] = bloque_perturbacion(n, sis)
    r[BLOQUES[7]] = bloque_deslastre(n, sis)
    r[BLOQUES[8]] = bloque_n1(n, red, cuantos_n1)
    return r


def imprimir_individual(red, r, md):
    titulo = f"{red.upper()} — {config.describir_escenario(red)}"
    print(f"\n{'#' if md else ''}{'#' if md else ''} {titulo}")
    if not md:
        print('=' * max(len(titulo), 68))
    for bloque, datos in r.items():
        print(f"\n{'### ' if md else ''}{bloque}")
        if md:
            print("\n| cifra | valor | nota |\n|---|---|---|")
        else:
            print('-' * len(bloque))
        for k, (v, nota) in datos.items():
            if md:
                print(f"| {k} | **{v}** | {nota} |")
            else:
                print(f"  {k:36s} {v:>18}" + (f"   {nota}" if nota else ''))


def imprimir_comparacion(resultados, md):
    redes = list(resultados)
    print(f"\n\n{'#' if md else ''}{'#' if md else ''} COMPARACION DIRECTA")
    if not md:
        print('=' * 68)
    for bloque in BLOQUES:
        claves = []
        for red in redes:
            for k in resultados[red].get(bloque, {}):
                if k not in claves:
                    claves.append(k)
        if not claves:
            continue
        print(f"\n{'### ' if md else ''}{bloque}")
        # Ancho por contenido: hay valores que son frases enteras ("sobrevive
        # | nadir=48,000 Hz en t=6,12 s") y a 20 columnas fijas se pegaban
        # unos con otros, dejando la tabla ilegible justo en la fila que mas
        # importa.
        ancho = max([20] + [len(resultados[r].get(bloque, {}).get(k, ('', ''))[0])
                            for r in redes for k in claves]) + 2
        if md:
            print("\n| cifra | " + " | ".join(redes) + " |")
            print("|---" * (len(redes) + 1) + "|")
        else:
            print('-' * len(bloque))
            print(f"  {'cifra':36s}" + "".join(f"{r:>{ancho}}" for r in redes))
        for k in claves:
            vals = [resultados[r].get(bloque, {}).get(k, ('—', ''))[0]
                    for r in redes]
            if md:
                print(f"| {k} | " + " | ".join(f"**{v}**" for v in vals) + " |")
            else:
                print(f"  {k:36s}" + "".join(f"{v:>{ancho}}" for v in vals))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--redes', nargs='+', default=['apagon', 'punta'],
                    choices=list(config.ESCENARIOS),
                    help="puntos de operacion a comparar (por defecto apagon punta)")
    ap.add_argument('--n1', type=int, default=6,
                    help="elementos de la muestra N-1 dirigida (0 = omitir). "
                         "OJO: ~187 s por contingencia con limites de Q")
    ap.add_argument('--md', action='store_true', help="salida en Markdown")
    args = ap.parse_args()

    print(f"{'# ' if args.md else ''}Bateria comparativa de puntos de operacion")
    print("\nMisma bateria, mismo codigo; lo unico que cambia es el .nc de "
          "entrada.\nLa seccion N-1 es una MUESTRA DIRIGIDA a los elementos "
          "mas cargados,\nno el barrido completo.")
    if args.n1 > 0:
        mins = args.n1 * len(args.redes) * 187 / 60.0
        print(f"\n  La muestra N-1 son {args.n1} contingencias x "
              f"{len(args.redes)} escenarios a ~187 s cada una:\n"
              f"  unos {mins:.0f} min. Con --n1 0 el resto sale en segundos.")

    resultados = {}
    for red in args.redes:
        print(f"\n[evaluando {red} ...]")
        resultados[red] = evaluar(red, args.n1)

    for red in args.redes:
        imprimir_individual(red, resultados[red], args.md)
    if len(args.redes) > 1:
        imprimir_comparacion(resultados, args.md)

    print("\nTodas las cifras se han medido en esta ejecucion. Si un "
          "documento dice\notra cosa, el documento esta obsoleto.")


if __name__ == '__main__':
    main()
