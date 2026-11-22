"""Validacion de la dinamica de frecuencia contra el 28-A con datos medidos.

Sustituye como contraste principal a validar_contra_entsoe.py, que usaba cuatro
valores leidos a ojo de la lamina 7 de NERC y un evento de tres perdidas.
Aqui se usan:

  - la traza de la PMU de Malaga a 10 muestras/s (y la de Zurich como
    referencia de Europa continental), del conjunto publico de Zenodo
    (data/fuentes/pmu_28a_zenodo.csv);
  - la secuencia de eventos al milisegundo de la Tabla 3-1 del informe final
    de ENTSO-E (data/fuentes/eventos_28a_entsoe_final.csv): cada perdida
    de generacion, cada bombeo y cada escalon de deslastre, con sus MW;
  - los instantes en que actuaron los escalones de deslastre por frecuencia
    (49,0 ... 48,0 Hz): son instantes de cruce de umbral medidos.

El contraste se separa en fases, porque el modelo es una Iberia AISLADA de una
sola masa y solo una de ellas es comparable:

  A. Sincronizada (12:32:00-12:33:16,4): Iberia sigue unida a Europa. La PMU
     de Malaga mide la frecuencia de Europa continental (coincide con Zurich).
     El modelo aislado NO es aplicable: se muestra, no se valida.
  B. Perdida de sincronismo (12:33:16,4-12:33:21,5): oscilacion de angulo con
     Francia que un modelo de una masa no tiene.
  C. Isla (desde 12:33:21,535, ultimo disparo AC con Francia): Iberia sola.
     Es el regimen que estudia la tesis y el unico donde el modelo es
     aplicable. Se arranca la simulacion en la separacion con la frecuencia
     medida (48,4 Hz, escalon de 12:33:21,537) y el desequilibrio que da la
     tabla de eventos, y se comparan los instantes en que el modelo cruza
     48,2 y 48,0 Hz con los medidos (12:33:21,838 y 12:33:22,080).

Ademas se compara la energia cinetica del modelo con la que calcula ENTSO-E
para las 12:30 (Tabla 2-4 del informe final). Desde el 19-nov-2026 la H del
apagon esta CALIBRADA con esa cifra (build_blackout_snapshot.py): antes el
modelo daba 88,5 GW.s (EK_MODELO_PREVIO), un 26 % menos.

Uso:  python -m iberia.validar_28a_isla
"""
import contextlib
import copy
import io
import logging
import warnings

warnings.filterwarnings('ignore')
logging.disable(logging.INFO)

import numpy as np            # noqa: E402
import pandas as pd           # noqa: E402
import pypsa                  # noqa: E402

from iberia import config      # noqa: E402
from iberia import dinamica_frecuencia as din   # noqa: E402

LAG_MALAGA_S = 0.411          # mode_shape.csv del conjunto de Zenodo
T_4A = 76.443                 # 12:33:16,443, evento 4a (inicio de la cascada)
T_SEP = 81.535                # 12:33:21,535, ultimo disparo AC con Francia
T_PMU_FIN = 80.59             # Malaga se congela desde 12:33:21,0 de su reloj (80,59 s corregido)
EXPORT_MARRUECOS_MW = 750.0   # informe final, sec. 3.1.2.1.3 (constante antes del evento)
HVDC_FRANCIA_MW = 1000.0      # 2 x 500 MW de consigna (sec. 3.1.2.2)
FR_TOTAL_1215_MW = 1060.0     # ENTSO-E A11, 12:15 (lo que lleva el punto del modelo)
EK_ENTSOE = {'ES': 97590.0, 'PT': 21884.0, 'IP': 119474.0}   # MW.s, Tabla 2-4
EK_MODELO_PREVIO = {'ES': 78189.7, 'PT': 10318.6, 'IP': 88508.3}   # antes de calibrar

# Escalones de deslastre por frecuencia de la peninsula (Tabla 3-1):
# instante medido de actuacion y umbral.
CRUCES = [(80.574, 49.0), (80.788, 48.8), (81.060, 48.7), (81.300, 48.6),
          (81.537, 48.4), (81.838, 48.2), (82.080, 48.0)]


def eventos_tabla():
    """Eventos del modelo a partir de la Tabla 3-1 (t en s desde 12:32:00).

    Positivo = deficit (dP_gen); negativo = superavit (dP_carga negativo).
    Los disparos sin MW reciben su efecto en el balance del modelo:
      - Marruecos (12:33:20,473): Iberia deja de exportar 750 MW. El modelo
        no tiene esa interconexion (el cierre del balance la desconto de la
        generacion), asi que el disparo entra como 750 MW de superavit.
      - Francia AC (12:33:21,535): el punto del modelo exporta 1.060 MW a
        Francia, de los que 1.000 son el HVDC; los 60 MW de AC desaparecen.
      - HVDC Francia (12:33:23,960): bloqueo, 1.000 MW de superavit.
    """
    d = pd.read_csv(config.dato('eventos_28a_entsoe_final.csv'))
    ev = []
    for r in d.itertuples():
        if pd.isna(r.mw):
            continue
        mw = float(r.mw)
        if str(r.cluster) == '1':          # rampa de 317,3 MW en 57 s
            for k in range(57):
                ev.append({'t': float(k), 'dP_gen': mw / 57.0, 'etiqueta': 'cluster 1'})
            continue
        if mw >= 0:
            ev.append({'t': float(r.t_s), 'dP_gen': mw, 'etiqueta': f'{r.cluster} {r.tipo}'})
        else:
            ev.append({'t': float(r.t_s), 'dP_carga': mw, 'etiqueta': f'{r.cluster} {r.tipo}'})
    ev += [{'t': 80.473, 'dP_carga': -EXPORT_MARRUECOS_MW, 'etiqueta': '16b Marruecos'},
           {'t': T_SEP, 'dP_carga': -(FR_TOTAL_1215_MW - HVDC_FRANCIA_MW), 'etiqueta': '31b Francia AC'},
           {'t': 83.960, 'dP_carga': -HVDC_FRANCIA_MW, 'etiqueta': '51 HVDC Francia'}]
    return sorted(ev, key=lambda e: e['t'])


def _sim(sis, ev, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return din.simular_frecuencia(sis, [dict(e) for e in ev], **kw)


def cruce(t, f, umbral):
    i = np.where(f <= umbral)[0]
    if not len(i):
        return np.nan
    k = int(i[0])
    if k == 0:
        return float(t[0])
    return float(t[k - 1] + (umbral - f[k - 1]) * (t[k] - t[k - 1]) / (f[k] - f[k - 1]))


def isla(sis, ev, escala_h=1.0, primaria='nula', extra_mw=0.0):
    """Simula la fase de isla desde T_SEP con la frecuencia medida."""
    previos = [e for e in ev if e['t'] <= T_SEP]
    s = copy.copy(sis)
    dg = sum(e.get('dP_gen', 0.0) for e in previos) + extra_mw
    dc = sum(e.get('dP_carga', 0.0) for e in previos)
    s.P_gen = sis.P_gen - dg
    s.P_carga = sis.P_carga + dc
    s.P_carga_es = sis.P_carga_es + dc
    s.H = sis.H * escala_h
    post = [dict(e, t=e['t'] - T_SEP) for e in ev if e['t'] > T_SEP]
    t, f, tr = _sim(s, post, con_deslastre=False, con_agc=False, t_fin=3.0,
                    f_inicial=48.4, primaria_inicial=primaria)
    return t + T_SEP, f, dg + dc


def main():
    n = pypsa.Network(config.red_de('apagon'))
    sis = din.Sistema(n)
    ek = sis.gen.H * sis.gen.s_sinc
    pt = sis.gen.bus.str.startswith('PT')
    ek_m = {'ES': float(ek[~pt].sum()), 'PT': float(ek[pt].sum())}
    ek_m['IP'] = ek_m['ES'] + ek_m['PT']

    print('=' * 72)
    print(' VALIDACION DEL 28-A CON DATOS MEDIDOS (PMU, ENTSO-E)')
    print('=' * 72)
    print('\n1. Energia cinetica a las 12:30 (ENTSO-E, Tabla 2-4) frente al modelo')
    for k in ('ES', 'PT', 'IP'):
        print(f'   {k}: ENTSO-E {EK_ENTSOE[k]/1e3:6.1f} GW.s | modelo {ek_m[k]/1e3:6.1f} GW.s '
              f'| antes de calibrar {EK_MODELO_PREVIO[k]/1e3:6.1f} GW.s '
              f'({100*(EK_MODELO_PREVIO[k]/EK_ENTSOE[k]-1):+5.1f} %)')

    pmu = pd.read_csv(config.dato('pmu_28a_zenodo.csv'))
    pmu['t'] = pmu.t_s - LAG_MALAGA_S
    pmu = pmu[pmu.t <= T_PMU_FIN]                 # despues, dato congelado
    ev = eventos_tabla()
    t, f, tr = _sim(sis, ev, con_deslastre=False, t_fin=90.0)
    fm = np.interp(pmu.t, t, f, right=np.nan)

    print('\n2. Fases: modelo aislado alimentado con la Tabla 3-1 frente a la PMU de Malaga')
    filas = []
    for nombre, a, b in (('A sincronizada', 0.0, T_4A), ('B perdida de sincronismo', T_4A, T_PMU_FIN + 0.01)):
        m = (pmu.t >= a) & (pmu.t < b)
        e_mod = (fm[m] - pmu.f_malaga_hz[m]).dropna() if hasattr(fm, 'dropna') else pd.Series(fm[m] - pmu.f_malaga_hz[m]).dropna()
        e_zur = (pmu.f_zurich_hz[m] - pmu.f_malaga_hz[m])
        fila = {'fase': nombre, 'n_puntos': int(m.sum()),
                'rmse_modelo_hz': float(np.sqrt((e_mod**2).mean())) if len(e_mod) else np.nan,
                'max_modelo_hz': float(e_mod.abs().max()) if len(e_mod) else np.nan,
                'rmse_zurich_malaga_hz': float(np.sqrt((e_zur**2).mean())),
                'max_zurich_malaga_hz': float(e_zur.abs().max())}
        filas.append(fila)
        print(f"   {nombre:26s} {fila['n_puntos']:4d} puntos | modelo-Malaga RMSE {fila['rmse_modelo_hz']:.3f} "
              f"max {fila['max_modelo_hz']:.3f} Hz | Zurich-Malaga RMSE {fila['rmse_zurich_malaga_hz']:.3f} "
              f"max {fila['max_zurich_malaga_hz']:.3f} Hz")
    print(f"   el modelo aislado cruza 47,5 Hz a {tr['t_colapso']} s" if tr['t_colapso'] else '')

    print('\n3. Fase de isla: instantes de cruce desde la separacion (12:33:21,535, 48,4 Hz)')
    med = {u: tt for tt, u in CRUCES}
    d_med = {u: med[u] - med[48.4] for u in (48.2, 48.0)}
    rocof_med = (48.0 - 48.4) / (med[48.0] - med[48.4])
    print(f'   medido: 48,2 Hz a +{d_med[48.2]:.3f} s, 48,0 Hz a +{d_med[48.0]:.3f} s; '
          f'RoCoF medio {rocof_med:.3f} Hz/s')
    previos = [e for e in ev if e['t'] <= T_SEP]
    neto = sum(e.get('dP_gen', 0.0) + e.get('dP_carga', 0.0) for e in previos)
    print(f'   desequilibrio registrado en la Tabla 3-1 hasta la separacion: {neto:+.0f} MW '
          f'(positivo = deficit)')
    cotas = []
    for et, ekv in (('inercia calibrada (ENTSO-E)', EK_ENTSOE['IP']),
                    ('inercia previa del modelo', EK_MODELO_PREVIO['IP'])):
        # Cota minima: solo inercia, sin regulacion ni amortiguamiento de carga
        # (los dos se oponen a la caida y solo pueden AUMENTAR el deficit que
        # hace falta). dP = 2 Ek |df/dt| / f0.
        minimo = 2.0 * ekv * abs(rocof_med) / din.F0
        cotas.append({'inercia': et, 'ek_mws': ekv, 'deficit_inercial_mw': minimo,
                      'no_registrado_minimo_mw': minimo - neto})
        print(f'   {et:18s} Ek {ekv/1e3:5.1f} GW.s: la caida medida exige >= {minimo:5.0f} MW de deficit '
              f'-> al menos {minimo - neto:5.0f} MW no registrados')
    casos = []
    for et, eh in (('inercia del modelo', 1.0),):
        for prim in ('nula', 'estacionaria'):
            ti, fi, desq = isla(sis, ev, eh, prim)
            c = {u: cruce(ti, fi, u) - T_SEP for u in (48.2, 48.0)}
            k = int(np.searchsorted(ti, T_SEP + 0.5))
            rocof = float((fi[k] - fi[0]) / (ti[k] - ti[0]))   # pendiente en los primeros 0,5 s
            casos.append({'inercia': et, 'primaria': prim, 'desequilibrio_mw': desq,
                          't_48_2_s': c[48.2], 't_48_0_s': c[48.0], 'rocof_hz_s': rocof,
                          'error_48_0_s': c[48.0] - d_med[48.0],
                          'error_rocof_pct': 100 * (rocof / rocof_med - 1)})
            print(f'   {et:18s} primaria {prim:12s} desequilibrio {desq:7.0f} MW | 48,2 a +{c[48.2]:.3f} s, '
                  f'48,0 a +{c[48.0]:.3f} s | pendiente en 0,5 s {rocof:+.3f} Hz/s (medida {rocof_med:+.3f})')

    pd.DataFrame(filas).to_csv(config.salida('validacion_28a_fases.csv'), index=False)
    pd.DataFrame(casos).to_csv(config.salida('validacion_28a_isla.csv'), index=False)
    pd.DataFrame(cotas).to_csv(config.salida('validacion_28a_deficit_minimo.csv'), index=False)
    _figura(pmu, t, f, sis, ev, ek_m)
    print('\n   CSV en resultados/validacion_28a_fases.csv y validacion_28a_isla.csv')


def _figura(pmu, t, f, sis, ev, ek_m):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={'width_ratios': [1.6, 1]})
    a1.plot(pmu.t, pmu.f_zurich_hz, color='0.55', lw=1.0, label='Zúrich (PMU)')
    a1.plot(pmu.t, pmu.f_malaga_hz, color='C3', lw=1.2, label='Málaga (PMU)')
    a1.plot(t, f, color='C0', lw=1.2, ls='--', label='Modelo aislado')
    a1.plot([c[0] for c in CRUCES], [c[1] for c in CRUCES], 'kv', ms=5, label='Escalones de deslastre')
    a1.axvline(T_4A, color='0.3', lw=0.7, ls=':'); a1.axvline(T_SEP, color='0.3', lw=0.7, ls=':')
    a1.set_xlim(70, 83); a1.set_ylim(47.8, 50.05)
    a1.set_xlabel('Segundos desde 12:32:00'); a1.set_ylabel('Frecuencia [Hz]')
    a1.legend(loc='lower left', fontsize=7.5)
    ti, fi, _ = isla(sis, ev, 1.0, 'nula')
    a2.plot(ti, fi, color='C0', lw=1.2, label='Modelo con el desequilibrio registrado')
    a2.plot([c[0] for c in CRUCES], [c[1] for c in CRUCES], 'kv', ms=6, label='Escalones de deslastre')
    a2.set_xlim(81.2, 82.4); a2.set_ylim(47.8, 48.8)
    a2.set_xlabel('Segundos desde 12:32:00'); a2.legend(loc='lower left', fontsize=7.5)
    fig.tight_layout()
    fig.savefig(config.visualizacion('validacion_28a_isla.png'), dpi=150)


if __name__ == '__main__':
    main()
