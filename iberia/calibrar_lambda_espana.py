"""Barrido de lambda (peso de la penalizacion por BTM sano en el MILP)
contra la penetracion BTM REAL espanola, para elegir un valor por defecto.

NO SE PUEDE REUSAR LAMBDA_BTM=5,0 DE COLOMBIA SIN COMPROBARLO: ese valor
se calibro contra el regimen normal colombiano (14-60% de penetracion).
Espana, en iberia_blackout.nc, tiene 8.500 / 27.000 MW = 31,5% de PLACA
de BTM sobre la demanda solo-Espana, y 5.029 / 27.000 = 18,6% de BTM
PRODUCIENDO, que es lo unico que puede caerse (este script mide y
reporta el valor real). La cifra de 40,4% que figuraba aqui usaba la
placa de dic-2025, ya retirada. Aun con la placa de abril se sigue
dentro del rango donde el barrido colombiano mostro que lambda=25 deja
de deslastrar por completo.
Ver 06_documentacion/2026-09-27-diseno-sub-proyecto-E-deslastre-btm.md,
seccion E3."""
import numpy as np
import pandas as pd

from iberia import config
import pypsa
from iberia import dinamica_frecuencia as din
from iberia import deslastre_btm_espana as D
from iberia.btm_regional import produccion_btm_por_bus, region_de_bus

CANDIDATOS_LAMBDA = (0.5, 5.0, 25.0)   # mismos candidatos que probo Colombia
SEMILLAS = (0, 1, 2)
CAIDA_PCT = 80.0
FRACCION_ACUMULADA = np.cumsum([0.15, 0.15, 0.10, 0.10])


def main():
    n = pypsa.Network(config.red('iberia_blackout.nc'))
    sis = din.Sistema(n)

    btm = produccion_btm_por_bus(n)
    es_buses = n.buses[n.buses.index.str.startswith('ES')].index
    carga = n.loads.groupby('bus').p_set.sum()
    carga = carga.reindex(es_buses).fillna(0.0)
    carga = carga[carga > 0]

    pen_pct = 100 * float(btm.sum()) / float(carga.sum())
    print(f"Penetracion BTM real en iberia_blackout.nc: "
          f"{btm.sum():.1f} / {carga.sum():.1f} MW = {pen_pct:.1f}%")

    region = {b: region_de_bus(n.buses.at[b, 'x'], n.buses.at[b, 'y'])
             for b in btm.index}

    filas = []
    for lam in CANDIDATOS_LAMBDA:
        for s in SEMILLAS:
            btm_est = D.estimar_btm(btm, region, semilla=s)
            caido_est, resto_est = D.aplicar_caida_btm(
                btm_est, CAIDA_PCT, semilla=s)
            caido_real, resto_real = D.aplicar_caida_btm(
                btm, CAIDA_PCT, semilla=s)
            alv, piso = D.escenarios_alivio(
                carga, btm_est, CAIDA_PCT, semilla=s)
            objetivos = pd.DataFrame({
                sc: [float(alv[sc].sum()) * f for f in FRACCION_ACUMULADA]
                for sc in alv.columns})
            asign = D.milp_asignacion(alv, resto_est, objetivos, lam=lam,
                                      alivio_piso=piso)
            elegidos = asign.index[asign.sum(axis=1) > 0]
            plan = float(piso.reindex(elegidos).fillna(0.0).sum())
            meta = float(objetivos.iloc[-1].mean())
            btm_sano_perdido = float(
                resto_real.reindex(elegidos).fillna(0.0).sum())
            filas.append({'lambda': lam, 'semilla': s,
                         'pct_objetivo': 100 * plan / meta if meta > 0 else 0.0,
                         'btm_sano_perdido_MW': btm_sano_perdido})
            print(f"  lambda={lam:g} semilla={s}: "
                  f"{100*plan/meta:.1f}% del objetivo, "
                  f"{btm_sano_perdido:.1f} MW de BTM sano perdido")

    df = pd.DataFrame(filas)
    resumen = df.groupby('lambda').agg(
        pct_objetivo_medio=('pct_objetivo', 'mean'),
        btm_sano_perdido_medio=('btm_sano_perdido_MW', 'mean')).round(1)
    print(f"\n--- Resumen (penetracion real {pen_pct:.1f}%) ---")
    print(resumen.to_string())
    df.to_csv(config.salida('calibracion_lambda_espana.csv'), index=False)


if __name__ == '__main__':
    main()
