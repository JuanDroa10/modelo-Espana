"""Verifica el MILP de asignacion bus->escalon de deslastre_btm_espana.py
con un conjunto pequeno de buses sinteticos (no la red completa - el MILP
real se ejecuta en E4 sobre iberia_blackout.nc)."""
import numpy as np
import pandas as pd

from iberia import deslastre_btm_espana as D


def _datos_sinteticos(semilla=0):
    """10 buses: cargas entre 50 y 500 MW, BTM entre 0 y 40% de la carga
    de cada bus (3 buses sin BTM, para probar que el MILP tambien puede
    asignar buses limpios cuando hace falta)."""
    rng = np.random.default_rng(semilla)
    buses = [f'bus{i}' for i in range(10)]
    carga = pd.Series(rng.uniform(50, 500, 10), index=buses)
    btm_pct = np.array([0.0, 0.0, 0.0, 0.35, 0.30, 0.25, 0.20, 0.15, 0.10, 0.05])
    btm = pd.Series(carga.values * btm_pct, index=buses)
    region = {b: 'unica' for b in buses}
    return carga, btm, region


def test_asignacion_respeta_una_vez_por_bus():
    carga, btm, region = _datos_sinteticos()
    btm_est = D.estimar_btm(btm, region, semilla=0)
    alv, piso = D.escenarios_alivio(carga, btm_est, caida_pct=80.0, semilla=0)
    _, resto_est = D.aplicar_caida_btm(btm_est, 80.0, semilla=0)
    objetivos = pd.DataFrame({
        sc: [float(alv[sc].sum()) * f
             for f in np.cumsum([0.15, 0.15, 0.10, 0.10])]
        for sc in alv.columns})
    asign = D.milp_asignacion(alv, resto_est, objetivos, lam=5.0,
                              alivio_piso=piso)
    assert (asign.sum(axis=1) <= 1).all(), (
        "ningun bus deberia asignarse a mas de un escalon")
    print(f"OK: asignacion valida, "
          f"{int((asign.sum(axis=1) > 0).sum())} de {len(asign)} buses "
          f"asignados a algun escalon")


def test_lambda_alto_protege_mas_btm_sano():
    """Con lambda mas alto, el MILP deberia preferir buses SIN BTM (o con
    menos) sobre buses con mucho BTM sano, cuando hay alternativa - mismo
    contraste que documenta JUANCHO/deslastre_btm.py para Colombia."""
    carga, btm, region = _datos_sinteticos()
    btm_est = D.estimar_btm(btm, region, semilla=0)
    alv, piso = D.escenarios_alivio(carga, btm_est, caida_pct=80.0, semilla=0)
    caido, resto_est = D.aplicar_caida_btm(btm_est, 80.0, semilla=0)
    objetivos = pd.DataFrame({
        sc: [float(alv[sc].sum()) * f
             for f in np.cumsum([0.15, 0.15, 0.10, 0.10])]
        for sc in alv.columns})

    resultados = {}
    for lam in (0.5, 25.0):
        asign = D.milp_asignacion(alv, resto_est, objetivos, lam=lam,
                                  alivio_piso=piso)
        elegidos = asign.index[asign.sum(axis=1) > 0]
        resultados[lam] = float(resto_est.reindex(elegidos).fillna(0.0).sum())
        print(f"  lambda={lam:g}: BTM sano perdido = {resultados[lam]:.1f} MW")

    assert resultados[25.0] <= resultados[0.5] + 1e-6, (
        f"lambda=25 (resultados[25.0]:.1f MW) deberia destruir menos o "
        f"igual BTM sano que lambda=0,5 ({resultados[0.5]:.1f} MW)")
    print("OK: un lambda mayor protege igual o mas BTM sano")





# ---------------------------------------------------------------------
# Las DOS garantias del metodo. Ambos tests FALLAN contra la version con
# la restriccion de suficiencia blanda y el objetivo sobre BTM estimado.
# ---------------------------------------------------------------------

def _caso_real():
    import pypsa
    from iberia import config
    from iberia.btm_regional import produccion_btm_por_bus, region_de_bus
    n = pypsa.Network(config.red('iberia_blackout.nc'))
    b_es = n.buses[n.buses.index.str.startswith('ES')].index
    carga = n.loads[n.loads.bus.isin(b_es)].groupby('bus').p_set.sum()
    carga = carga[carga > 0]
    btm = produccion_btm_por_bus(n).reindex(carga.index).fillna(0.0)
    reg = {b: region_de_bus(n.buses.at[b, 'x'], n.buses.at[b, 'y'])
           for b in carga.index}
    return carga, btm, reg


def _plan(carga, btm_est, caida_pct, lam):
    """MW que el plan deslastra, medidos sobre el piso (carga medida)."""
    alv, piso = D.escenarios_alivio(carga, btm_est, caida_pct, semilla=0)
    dem = float(carga.sum())
    objs = pd.DataFrame({sc: [dem * f for f in (0.15, 0.30, 0.40, 0.50)]
                         for sc in alv.columns})
    _, resto = D.aplicar_caida_btm(btm_est, caida_pct, semilla=0)
    a = D.milp_asignacion(alv, resto, objs, lam=lam, alivio_piso=piso,
                          verbose=False)
    eleg = a.index[a.sum(axis=1) > 0]
    return float(piso.reindex(eleg).fillna(0.0).sum()), dem


def test_la_suficiencia_no_depende_de_lambda():
    """EL PRECIPICIO DE LAMBDA NO DEBE EXISTIR.

    Con la restriccion de suficiencia BLANDA que tenia este MILP, lambda
    podia COMPRAR incumplimiento: a lambda=25 el esquema planificaba
    966,4 MW en vez de 13.500 en regimen normal, es decir el 3,58% de la
    demanda en vez del 50% que manda el P.O. 1.6. El esquema quedaba
    efectivamente APAGADO en operacion normal, y la calibracion no lo
    veia porque solo barria el eje del evento (CAIDA_PCT=80).

    Con la restriccion dura, lambda solo puede elegir ENTRE planes
    suficientes. Este test barre el eje que la calibracion no miraba."""
    carga, btm, reg = _caso_real()
    btm_est = D.estimar_btm(btm, reg, semilla=0)
    for lam in (0.5, 25.0, 100.0):
        plan, dem = _plan(carga, btm_est, 0.0, lam)   # 0% = regimen normal
        pct = 100.0 * plan / dem
        assert abs(pct - 50.0) < 1.0, (
            f"con lambda={lam} el esquema planifica el {pct:.2f}% de la "
            f"demanda en REGIMEN NORMAL, y el P.O. 1.6 manda el 50%. "
            f"Lambda ha vuelto a poder comprar insuficiencia: revisar que "
            f"la restriccion 'suficiencia' de milp_asignacion siga siendo "
            f"DURA (sin variable de holgura).")
    print("OK: la suficiencia se cumple al 50% para lambda de 0,5 a 100 "
          "(antes, lambda=25 la dejaba en 3,58%)")


def test_desacople_de_das():
    """EL TAMANO DEL PLAN NO DEBE DEPENDER DEL ESTIMADOR DE BTM.

    Es la garantia que da nombre al metodo de Das: el error de estimacion
    del BTM no puede causar deslastre insuficiente. Antes el objetivo se
    calculaba sobre alv(btm_ESTIMADO), asi que el plan escalaba con el
    sesgo del estimador y se movia 11 puntos de demanda (52,1% a 63,1%).
    Ahora sale de la demanda MEDIDA."""
    carga, btm, reg = _caso_real()
    base = D.estimar_btm(btm, reg, semilla=0)
    pcts = []
    for k in (0.2, 1.0, 2.0):     # 10x de rango en el BTM estimado
        plan, dem = _plan(carga, base * k, 80.0, 25.0)
        pcts.append(100.0 * plan / dem)
    assert max(pcts) - min(pcts) < 1.0, (
        f"el plan se mueve {max(pcts)-min(pcts):.2f} puntos de demanda al "
        f"variar el sesgo del estimador ({[round(p,2) for p in pcts]}). "
        f"El objetivo del esquema ha vuelto a depender del BTM estimado: "
        f"revisar que `objetivos` en ejecutar_espana salga de la demanda "
        f"medida y no de alv().")
    print(f"OK: el plan se mantiene en {pcts[0]:.2f}% de la demanda con un "
          f"rango de 10x en el BTM estimado (antes variaba 11 puntos)")


if __name__ == '__main__':
    test_asignacion_respeta_una_vez_por_bus()
    test_lambda_alto_protege_mas_btm_sano()
    print("\nTodas las verificaciones del MILP pasaron.")
    test_la_suficiencia_no_depende_de_lambda()
    test_desacople_de_das()
    print('\nTodas las verificaciones del MILP pasaron.')
