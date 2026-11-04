"""Escenario de cascada calibrado contra las perdidas reales del 28 de abril
de 2025, mas una barrida de sensibilidad sobre la penetracion de BTM.

Perdidas reales (fuente: ENTSO-E/FERC, ver diseño): solar -9.813 MW,
nuclear -3.387 MW, hidraulica -1.940 MW, eolica -1.357 MW, en ~5 segundos.
La secuencia temporal sigue el orden narrado por ENTSO-E: disparo local,
luego solar de gran escala, luego eolica+distribuida, luego el resto."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from iberia import config
import pypsa
from iberia import dinamica_frecuencia as din


from iberia.btm_regional import produccion_btm_por_bus, factor_produccion

# Instantes de la secuencia narrada por ENTSO-E, en segundos desde el
# disparo local que inicia la perturbacion.
IBERIA_T = (0.0, 0.5, 1.2, 2.0, 3.0, 4.2, 5.0)

_desenlace = din.describir   # ver dinamica_frecuencia.describir


# Perdidas reales del 28-A por tecnologia (MW), de ENTSO-E/FERC.
PERDIDA_28A = {'solar': 9813.0, 'eolica': 1357.0,
               'hidro': 1940.0, 'nuclear': 3387.0}

# Que carriers del modelo corresponden a cada tecnologia de esa tabla.
CARRIERS = {
    'solar':   ('PV', 'Solar Thermal'),
    'eolica':  ('Onshore', 'Offshore_floating'),
    'hidro':   ('Reservoir', 'Run_of_river'),
    'nuclear': ('Nuclear',),
}


def _despachado(n, tecnologia):
    """MW espanoles despachados de una tecnologia en este punto."""
    es = n.buses[n.buses.index.str.startswith('ES')].index
    g = n.generators
    sel = g[(g.bus.isin(es)) & (g.carrier.isin(CARRIERS[tecnologia]))]
    return float(sel.p_set.sum())


def escenario_real(n, sis):
    """La cascada calibrada contra las cifras reales de ENTSO-E.

    Las perdidas se TOPAN EN LO QUE CADA TECNOLOGIA ESTA DESPACHANDO en
    el punto de operacion que se este simulando. En el apagon eso no
    cambia nada -la tabla de ENTSO-E es de ese instante, asi que las
    cifras pasan intactas- pero en cualquier otro escenario es
    imprescindible: aplicar la cascada del 28-A a la punta invernal
    nocturna pedia perder 9.813 MW de solar a las 21 h de enero, cuando
    la solar vale CERO. No se puede perder lo que no se esta generando.

    Es ademas lo que hace fisicamente interesante el contraste: el mismo
    disturbio, evaluado en dos puntos de operacion, tiene magnitudes
    distintas porque el parque despachado es distinto."""
    perdida = {}
    for tec, mw in PERDIDA_28A.items():
        disponible = _despachado(n, tec)
        perdida[tec] = min(mw, disponible)
        if perdida[tec] < mw - 1.0:
            print(f"  [cascada] {tec}: se pierden {perdida[tec]:.0f} MW en vez "
                  f"de los {mw:.0f} del 28-A; es lo unico despachado")

    return [
        {'t': IBERIA_T[0], 'etiqueta': 'disparo local que inicia la perturbacion'},
        {'t': IBERIA_T[1], 'dP_gen': perdida['solar'] * 0.6,
         'etiqueta': 'solar de gran escala (60%)'},
        {'t': IBERIA_T[2], 'dP_gen': perdida['solar'] * 0.4,
         'etiqueta': 'solar de gran escala (resto)'},
        {'t': IBERIA_T[3], 'dP_gen': perdida['eolica'], 'etiqueta': 'eolica'},
        {'t': IBERIA_T[4], 'dP_gen': perdida['hidro'], 'etiqueta': 'hidraulica'},
        {'t': IBERIA_T[5], 'dP_gen': perdida['nuclear'],
         'etiqueta': 'nuclear (disparo automatico)'},
    ]


def escenario_con_btm(n, sis, penetracion_btm_pct, btm_por_bus,
                      t_entrada=IBERIA_T[1]):
    """Igual que escenario_real, pero ademas incluye la penetracion de BTM
    dada (0-100%) como dP_carga en el instante `t_entrada`. Por defecto es
    t=IBERIA_T[1]=0,5 s (mismo instante que la solar de gran escala, porque el
    BTM residencial es tambien solar de inversor grid-following y cae por el
    mismo mecanismo de disparo por sub/sobre-frecuencia o hueco de tension ante
    la misma perturbacion local). El diseño (D4) situaba el "BTM regional" mas
    tarde, en la ventana 2,0-3,0 s; por eso `t_entrada` se parametriza y la
    barrida de timing de abajo lo hace variar explicitamente. btm_por_bus es la
    Serie que devuelve capacidad_btm_por_bus (Tarea 2)."""
    base = escenario_real(n, sis)
    mw_btm = float(btm_por_bus.sum()) * (penetracion_btm_pct / 100.0)
    base.append({'t': t_entrada, 'dP_carga': mw_btm,
                 'etiqueta': f'BTM invisible ({penetracion_btm_pct:.0f}% de {btm_por_bus.sum():.0f} MW) en t={t_entrada:.1f}s'})
    return base


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    config.anadir_arg_red(ap)
    args = ap.parse_args()
    print(f"Punto de operacion: {args.red} "
          f"({config.describir_escenario(args.red)})")
    n = pypsa.Network(config.red_de(args.red))
    sis = din.Sistema(n)
    print(f"=== Sistema en el punto de operacion: {args.red} ===")
    sis.resumen()

    # PRODUCCION, no placa: lo que puede caerse es lo que se estaba
    # generando. Antes se tiraba la placa entera, que equivalia a
    # suponer todo el autoconsumo de Espana a plena potencia.
    btm_por_bus = produccion_btm_por_bus(n)
    fc = factor_produccion(n)
    print(f"\nBTM produciendo: {btm_por_bus.sum():.1f} MW "
          f"(factor de carga {fc:.3f} sobre la placa instalada)")

    print("\n=== Escenario calibrado SIN BTM adicional ===")
    t, f, traza = din.simular_frecuencia(sis, escenario_real(n, sis))
    print(_desenlace(traza))

    # RoCoF inicial FISICO del primer evento real (la tranche solar de t=0,5 s,
    # dP=9813*0,6=5887,8 MW), por la relacion de la ecuacion de oscilacion
    # RoCoF = -dP / (2*H*S_base) * F0. NO es traza['rocof_inicial'], que vale
    # 0 Hz/s porque el evento t=0 ('disparo local') tiene dP nulo: mide la
    # pendiente entre f[0] y f[1], antes de que se aplique ningun escalon real.
    dP_primer = 9813.0 * 0.6
    rocof_inicial = -dP_primer / (2.0 * sis.H * sis.S_base) * din.F0
    print(f"RoCoF inicial (analitico, primer evento dP={dP_primer:.1f} MW): "
          f"{rocof_inicial:.3f} Hz/s  [traza['rocof_inicial']={traza['rocof_inicial']:.3f} Hz/s, "
          f"artefacto del placeholder t=0 sin escalon]")

    print("\n=== Barrida de sensibilidad: penetracion de BTM (0-100%) ===")
    resultados = []
    for pct in range(0, 101, 10):
        t, f, traza = din.simular_frecuencia(
            sis, escenario_con_btm(n, sis, pct, btm_por_bus))
        resultados.append({'penetracion_pct': pct,
                            't_colapso': traza['t_colapso'],
                            'nadir': traza['nadir'],
                            'colapso': traza['colapso']})
        print(f"  {pct:3d}%: {_desenlace(traza)}")

    df = pd.DataFrame(resultados)
    df.to_csv(config.salida(f'sensibilidad_btm_{args.red}.csv'), index=False)

    # Barrida de sensibilidad al INSTANTE de entrada del BTM. Penetracion fija
    # al 100% (el caso mas extremo/claro), variando t_entrada sobre los cuatro
    # instantes de IBERIA_T que enmarcan la eleccion actual (0,5 s) y la
    # ventana 2,0-3,0 s que el diseño (D4) declaraba para el "BTM regional".
    print("\n=== Barrida de sensibilidad: instante de entrada del BTM (100%) ===")
    tiempos = [IBERIA_T[1], IBERIA_T[2], IBERIA_T[3], IBERIA_T[4]]
    resultados_t = []
    for te in tiempos:
        t, f, traza = din.simular_frecuencia(
            sis, escenario_con_btm(n, sis, 100, btm_por_bus, t_entrada=te))
        resultados_t.append({'t_entrada_btm': te,
                             't_colapso': traza['t_colapso'],
                             'nadir': traza['nadir'],
                             'colapso': traza['colapso']})
        print(f"  t_entrada={te:.1f}s: {_desenlace(traza)}")

    df_t = pd.DataFrame(resultados_t)
    df_t.to_csv(config.salida(f'sensibilidad_btm_timing_{args.red}.csv'), index=False)

    # Grafico de la curva de frecuencia del escenario calibrado
    t, f, traza = din.simular_frecuencia(sis, escenario_real(n, sis))
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(t, f, color='crimson', linewidth=1.5)
    ax.axhline(50.0, color='gray', linestyle=':', label='50 Hz nominal')
    ax.axhline(din.F_COLAPSO, color='black', linestyle='--',
               label=f'{din.F_COLAPSO} Hz (colapso)')
    ax.set_xlabel('Tiempo (s)')
    ax.set_ylabel('Frecuencia (Hz)')
    ax.set_title(f'Dinamica de frecuencia — {args.red}: '
                 f'{config.describir_escenario(args.red)}')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(config.visualizacion(f'btm_cascada_frecuencia_{args.red}.png'), dpi=150)
    print(f"\n✓ Resultados de '{args.red}' en resultados/ y resultados/visualizaciones/")


if __name__ == '__main__':
    main()
