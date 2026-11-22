"""Variante MEDIDA de la punta: 15-ene-2025, cuarto de 20:45 a 21:00 CET.

No sustituye a iberia_punta.nc: escribe una red aparte para comparar.

    --paso 1  ->  03_redes_pypsa/iberia_punta_medida.nc   (IBERIA_VARIANTE=medida)
    --paso 2  ->  03_redes_pypsa/iberia_punta_i90.nc      (IBERIA_VARIANTE=i90)

PASO 1: los totales por tecnologia, la demanda y los intercambios pasan a ser
los MEDIDOS por ENTSO-E (y contrastados con el tiempo real de ESIOS), en vez
de las cuotas medias de enero que usa build_punta_snapshot.py. Dentro de cada
tecnologia el reparto sigue siendo proporcional, igual que en el apagon.

PASO 2: lo mismo, pero la generacion convencional se asigna CENTRAL A CENTRAL
con el P48 del I90DIA de REE (ESIOS) del mismo cuarto de hora:
  - nuclear: cada grupo a su generador del modelo;
  - ciclos combinados y carbon: cada central a su barra; los grupos grandes
    que el I90 no programa quedan PARADOS;
  - bombeo: las cinco centrales que el I90 identifica (La Muela, Moralets,
    Sallente, Aguayo, Bolarque) a su barra; el resto del bombeo medido va
    dentro de las unidades hidraulicas agregadas por cuenca, y se reparte en
    proporcion entre los demas bombeos.
La tabla unidad -> barra es 02_datos_originales/up_barra_i90.csv (codigos y
descripciones del listado de unidades de OMIE). El extracto del P48 es
02_datos_originales/p48_i90_20250115_2045.csv.

Lo que sigue SIN ser dato en los dos pasos: el reparto de la eolica, de la
hidraulica y de la demanda entre barras (proporcional y por comunidad
autonoma). El I90 no ubica las renovables: van en carteras sin barra.

El balance se cierra con el flujo AC igual que en el apagon: la demanda en
barras mas las perdidas iguala la carga medida, y lo que el nudo de
referencia tendria que cubrir se reparte entre los generadores que no son
dato unidad a unidad (en el paso 2, ni la nuclear ni las centrales del I90).
"""
import argparse

import pandas as pd
import pypsa

from iberia import config

# --- ENTSO-E, 15-ene-2025, 19:45-20:00 UTC (20:45-21:00 CET) ---------------
# A75 por tipo; las series vienen en bloques de valor constante, se toma el
# vigente en ese cuarto. Contraste con ESIOS (tiempo real, 20:45 CET) entre
# parentesis.
ENTSOE_NUCLEAR_MW = 7120.0       # B14 (ESIOS 549: 7.124)
ENTSOE_EOLICA_MW = 13160.0       # B19, B18 = 0 (ESIOS 551: 13.252)
ENTSOE_HIDRO_MW = 6604.0         # B11 1.292 + B12 5.312 (ESIOS 2080: 6.561)
ENTSOE_BOMBEO_GEN_MW = 2596.0    # B10 generando; consumo 0. ESIOS no publica
                                 # la turbinacion (2079 = 0), pero su balance
                                 # deja un hueco de ~2.570 MW: es esto.
ENTSOE_SOLAR_MW = 100.0          # B16 (ESIOS: FV 70 + termosolar 31)
SOLAR_TERMICA_MW = 31.0          # ESIOS 1294
ENTSOE_TERMICA_MW = 12800.0      # B04 gas 10.904 + B05 carbon 1.080 + B01
                                 # biomasa 500 + B17 residuos 204 + B06/B15/B20
                                 # 112 (ESIOS: CC 8.848 + carbon 1.084 +
                                 # cogeneracion 2.280 + termica renovable 541)
ENTSOE_DEMANDA_ES_MW = 39808.0   # A65, incluye perdidas (ESIOS 1293: 39.746;
                                 # punta instantanea REE: 40.070 a las 20:57)
ENTSOE_EXPORT_FR_MW = 2184.0     # A11 ES->FR, cuarto de 20:45 (FR->ES: 0)
ENTSOE_EXPORT_PT_MW = 106.0      # A11 neto, hora 20-21 CET (129 - 23)
ENTSOE_DEMANDA_PT_MW = 9285.0    # A65 PT, hora 20-21 CET
# A75 PT, hora 20-21 CET, agrupado en los cuatro carriers de sus agregados:
PT_MEZCLA_MW = {
    'Hydro': 2300.0 + 2220.0 + 972.0,     # B10 bombeo generando + B11 + B12
    'Combined_cycle': 2053.0 + 338.0 + 23.0,  # B04 gas + B01 biomasa + B20
    'Onshore': 1183.0 + 4.0,              # B19 + B18
    'PV': 0.0,                            # B16
}

TERMICA = ['Coal', 'Gas_turbine', 'ICCC', 'Steam_turbine', 'Biomass',
           'Combined_cycle']
SALIDA = {1: 'iberia_punta_medida.nc', 2: 'iberia_punta_i90.nc'}


def _es(n):
    es_buses = n.buses[n.buses.index.str.startswith('ES')].index
    return es_buses, n.generators[n.generators.bus.isin(es_buses)]


def escalar(n, es_gens, carriers, objetivo):
    idx = es_gens[es_gens.carrier.isin(carriers)].index
    placa = n.generators.loc[idx, 'p_nom']
    n.generators.loc[idx, 'p_set'] = placa / placa.sum() * objetivo
    print(f"  {'+'.join(carriers):28s} {objetivo:9.1f} MW (proporcional a la placa)")


def asignar_i90(n, es_gens, p48_csv, total_nuclear, total_bombeo):
    """Paso 2: convencional central a central con el P48 del I90.

    Comun a la punta y al apagon (build_blackout_i90.py). Una unidad del
    mapa que no aparece en el P48 de ese cuarto de hora esta PARADA. El
    bombeo lleva signo: positivo turbinando (punta), negativo consumiendo
    (apagon). Devuelve (generadores fijados, tabla unidad -> MW)."""
    p48 = pd.read_csv(config.dato(p48_csv))
    mapa = pd.read_csv(config.dato('up_barra_i90.csv'))
    m = mapa.merge(p48.groupby('UP', as_index=False).MW.sum(),
                   left_on='up', right_on='UP', how='left')
    m['MW'] = m.MW.fillna(0.0)
    fijos = []

    # Nuclear: grupo a grupo, escalado al total medido (el P48 es el
    # programa; la medida difiere menos de un 1 %). Sin P48, parado.
    nuc = m[m.carrier == 'Nuclear']
    f = total_nuclear / nuc.MW.sum()
    for r in nuc.itertuples():
        n.generators.at[r.destino, 'p_set'] = r.MW * f
        fijos.append(r.destino)
    print(f"  Nuclear: {int((nuc.MW > 0).sum())} de 7 grupos en servicio "
          f"({nuc.MW.sum():.0f} MW programados, escalados a {total_nuclear:.0f})")

    # Ciclos, carbon y bombeo: por barra. Los grupos de ciclo o carbon que
    # el I90 no programa quedan a cero.
    for carrier in ['Combined_cycle', 'Coal', 'Pumped_storage']:
        grupos = es_gens[es_gens.carrier == carrier].index
        sub = m[(m.carrier == carrier) & (m.MW.abs() > 0)]
        por_barra = {}
        for r in sub.itertuples():
            barras = r.destino.split(';')
            for b in barras:
                por_barra[b] = por_barra.get(b, 0.0) + r.MW / len(barras)
        asignados, desborde = [], 0.0
        for b, mw in por_barra.items():
            g = es_gens[(es_gens.bus == b) & (es_gens.carrier == carrier)].index
            if not len(g):
                raise SystemExit(f"{carrier}: no hay generador en {b}")
            placa = n.generators.loc[g, 'p_nom']
            if abs(mw) > placa.sum() + 1e-6:
                if carrier != 'Pumped_storage':
                    raise SystemExit(f"{carrier} en {b}: {mw:.0f} MW > placa {placa.sum():.0f}")
                # bombeo: lo que no cabe en su barra pasa al resto
                lleno = placa.sum() * (1 if mw > 0 else -1)
                desborde += mw - lleno
                mw = lleno
            n.generators.loc[g, 'p_set'] = placa / placa.sum() * mw
            asignados += list(g)
        if carrier == 'Pumped_storage':
            resto = [g for g in grupos if g not in asignados]
            falta = total_bombeo - sub.MW.sum() + desborde
            placa = n.generators.loc[resto, 'p_nom']
            n.generators.loc[resto, 'p_set'] = placa / placa.sum() * falta
            print(f"  Bombeo: {sub.MW.sum() - desborde:.0f} MW en {len(sub)} centrales "
                  f"del I90 + {falta:.0f} MW repartidos entre los otros {len(resto)}")
        else:
            parados = [g for g in grupos if g not in asignados
                       and n.generators.at[g, 'p_nom'] >= 100]
            n.generators.loc[parados, 'p_set'] = 0.0
            print(f"  {carrier}: {sub.MW.sum():.0f} MW en {len(por_barra)} barras; "
                  f"{len(parados)} grupos de 100 MW o mas PARADOS")
        fijos += asignados
    return pd.Index(fijos), m


def resto_termico(n, es_gens, fijos, m, total_termico):
    """Lo termico medido que no explican las centrales del I90 (cogeneracion,
    biomasa, residuos), sobre la termica pequena; lo que no cabe, a las
    centrales termicas del I90 en servicio (SUPUESTO declarado abajo)."""
    conv = m[m.carrier.isin(['Combined_cycle', 'Coal'])].MW.sum()
    resto_mw = total_termico - conv
    cand = es_gens[es_gens.carrier.isin(TERMICA) & ~es_gens.index.isin(fijos)
                   & ~(es_gens.carrier.isin(['Combined_cycle', 'Coal'])
                       & (es_gens.p_nom >= 100))].index
    placa = n.generators.loc[cand, 'p_nom']
    en_pequenos = min(resto_mw, float(placa.sum()))
    n.generators.loc[cand, 'p_set'] = placa / placa.sum() * en_pequenos
    print(f"  Resto termico (cogeneracion, biomasa, residuos): {resto_mw:.0f} MW; "
          f"{en_pequenos:.0f} en {len(cand)} grupos pequeños "
          f"(al {100 * en_pequenos / placa.sum():.0f} % de su placa)")
    # SUPUESTO DECLARADO. El modelo no tiene la cogeneracion como
    # tecnologia (ESIOS mide 2.280 MW en la punta) y su termica pequena
    # no la alcanza. Lo que sobra se coloca en las centrales termicas
    # que el I90 tiene en servicio, en proporcion a su margen libre:
    # es generacion sincrona, como la cogeneracion, y suele estar en
    # los mismos polos industriales. Altera el valor del I90 de esas
    # centrales en la proporcion que se imprime.
    sobra = resto_mw - en_pequenos
    if sobra > 1.0:
        term = es_gens[es_gens.index.isin(fijos)
                       & es_gens.carrier.isin(['Combined_cycle', 'Coal'])].index
        margen = (n.generators.loc[term, 'p_nom'] - n.generators.loc[term, 'p_set']).clip(lower=0)
        if sobra > margen.sum():
            raise SystemExit(f"No cabe el resto termico: {sobra:.0f} > {margen.sum():.0f} MW")
        antes = float(n.generators.loc[term, 'p_set'].sum())
        n.generators.loc[term, 'p_set'] += margen / margen.sum() * sobra
        print(f"  (supuesto) {sobra:.0f} MW de cogeneracion sin representar van a las "
              f"centrales termicas del I90 en servicio: {antes:.0f} -> "
              f"{antes + sobra:.0f} MW (+{100 * sobra / antes:.1f} %)")


def fijar_variante(variante):
    """Fija (o quita) IBERIA_VARIANTE ANTES de leer nada, para que el caso
    base del cierre (analisis_n1) lea la red que se esta construyendo."""
    import importlib
    import os
    if variante:
        os.environ['IBERIA_VARIANTE'] = variante
    else:
        os.environ.pop('IBERIA_VARIANTE', None)
    importlib.reload(config)


def main():
    # En esta copia no hay variantes (IBERIA_VARIANTE solo existe en la
    # copia de desarrollo): se construye el punto vigente.
    construir(2, 'iberia_punta.nc', None)


def construir(paso, salida, variante):
    """Construye la punta medida. Desde el 19-nov-2026 el punto VIGENTE es
    el paso 2 escrito en iberia_punta.nc sin variante (build_punta_snapshot.py)."""
    fijar_variante(variante)

    n = pypsa.Network(config.red('iberia_scenario.nc'))
    es_buses, es_gens = _es(n)
    print("=" * 70)
    print(f" PUNTA MEDIDA, paso {paso}: 15-ene-2025, 20:45-21:00 CET")
    print("=" * 70)

    # --- Totales medidos por tecnologia (paso 1 y base del paso 2) ---
    escalar(n, es_gens, ['PV'], ENTSOE_SOLAR_MW - SOLAR_TERMICA_MW)
    escalar(n, es_gens, ['Solar Thermal'], SOLAR_TERMICA_MW)
    escalar(n, es_gens, ['Nuclear'], ENTSOE_NUCLEAR_MW)
    escalar(n, es_gens, ['Onshore', 'Offshore_floating'], ENTSOE_EOLICA_MW)
    escalar(n, es_gens, ['Reservoir', 'Run_of_river'], ENTSOE_HIDRO_MW)
    escalar(n, es_gens, ['Pumped_storage'], ENTSOE_BOMBEO_GEN_MW)
    escalar(n, es_gens, TERMICA, ENTSOE_TERMICA_MW)

    fijos = pd.Index([])
    if paso == 2:
        print("\nAsignacion central a central con el P48 del I90:")
        fijos, m = asignar_i90(n, es_gens, 'p48_i90_20250115_2045.csv',
                               ENTSOE_NUCLEAR_MW, ENTSOE_BOMBEO_GEN_MW)
        resto_termico(n, es_gens, fijos, m, ENTSOE_TERMICA_MW)

    # --- Demanda e intercambios ---
    es_loads = n.loads[n.loads.bus.isin(es_buses)].index
    n.loads.loc[es_loads, 'p_set'] *= (ENTSOE_DEMANDA_ES_MW - 700.0) / float(
        n.loads.loc[es_loads, 'p_set'].sum())
    # Portugal: demanda y mezcla medidas. Sus cuatro agregados tienen una
    # placa EQUIVALENTE (heredada del escenario generico, 3.984 MW), que no
    # alcanza los ~9.180 MW que produce a esta hora. Se sube solo hasta
    # p_set / 0,70, el factor de carga que la dinamica aplica a Portugal,
    # para que la placa no recorte su capacidad acoplada.
    from iberia import dinamica_frecuencia as din
    b = n.buses[n.buses.index.str.startswith('PT')].index
    ld = n.loads[n.loads.bus.isin(b)].index
    n.loads.loc[ld, 'p_set'] *= ENTSOE_DEMANDA_PT_MW / float(n.loads.loc[ld, 'p_set'].sum())
    gen_pt = ENTSOE_DEMANDA_PT_MW - ENTSOE_EXPORT_PT_MW
    mezcla = {k: v / sum(PT_MEZCLA_MW.values()) * gen_pt for k, v in PT_MEZCLA_MW.items()}
    for carrier, mw in mezcla.items():
        gi = n.generators[n.generators.bus.isin(b) & (n.generators.carrier == carrier)].index
        n.generators.loc[gi, 'p_set'] = mw / len(gi)
        n.generators.loc[gi, 'p_nom'] = n.generators.loc[gi, ['p_nom', 'p_set']].assign(
            p_set=lambda d: d.p_set / din.FACTOR_CARGA_UNIDAD).max(axis=1)
    print(f"  PT: demanda {ENTSOE_DEMANDA_PT_MW:,.0f} MW, genera {gen_pt:,.0f} "
          f"({', '.join(f'{k} {v:,.0f}' for k, v in mezcla.items())}), importa "
          f"{ENTSOE_EXPORT_PT_MW:,.0f} MW de España")
    b = n.buses[n.buses.index.str.startswith('FR')].index
    dem = float(n.loads[n.loads.bus.isin(b)].p_set.sum())
    gi = n.generators[n.generators.bus.isin(b)].index
    n.generators.loc[gi, 'p_set'] *= (dem - ENTSOE_EXPORT_FR_MW) / float(n.generators.loc[gi, 'p_set'].sum())
    print(f"  FR: importa {ENTSOE_EXPORT_FR_MW:,.0f} MW de España")

    rotos = n.generators[n.generators.p_set > n.generators.p_nom + 1e-6]
    assert not len(rotos), rotos[['carrier', 'p_nom', 'p_set']]
    n.export_to_netcdf(config.red(salida))
    cerrar(salida, es_buses, es_loads, fijos, 'punta', ENTSOE_DEMANDA_ES_MW)


def cerrar(salida, es_buses, es_loads, fijos, red, demanda_mw, max_iter=12):
    """Cierre del balance con el flujo AC (mismo criterio que el apagon).
    Comun a la punta y a build_blackout_i90.py."""
    from iberia import analisis_n1 as an
    from iberia import limites_reactivos_espana as L
    assert config.red_de(red).endswith(salida), config.red_de(red)
    print("\nCerrando el balance con el flujo AC (limites de reactivo activos)...")
    for it in range(1, max_iter + 1):
        base, _ = an.caso_base(verbose=False, con_limites=True, red=red)
        nl, _ = L.aplicar(base, verbose=False)
        g = nl.generators
        slack = g.index[g.control == 'Slack'][0]
        desvio = float(nl.generators_t.p.iloc[0][slack] - g.at[slack, 'p_set'])
        e0 = nl.lines.bus0.isin(es_buses)
        t0 = nl.transformers.bus0.isin(es_buses)
        perd = float((nl.lines_t.p0.iloc[0] + nl.lines_t.p1.iloc[0])[e0].sum()
                     + (nl.transformers_t.p0.iloc[0] + nl.transformers_t.p1.iloc[0])[t0].sum())
        n = pypsa.Network(config.red(salida))
        carga = float(n.loads.loc[es_loads, 'p_set'].sum())
        exceso = carga + perd - demanda_mw
        print(f"  iteracion {it}: {slack} desvio {desvio:+8.1f} MW | demanda en "
              f"barras {carga:9.1f} + perdidas {perd:6.1f} = {carga + perd:9.1f} MW")
        if abs(desvio) < 1.0 and abs(exceso) < 1.0:
            break
        n.loads.loc[es_loads, 'p_set'] *= (carga - exceso) / carga
        falta = desvio - exceso
        gi = n.generators[n.generators.bus.isin(es_buses) & (n.generators.p_set > 0)
                          & (n.generators.index != slack)
                          & (n.generators.carrier != 'Nuclear')
                          & ~n.generators.index.isin(fijos)].index
        nuevo = n.generators.loc[gi, 'p_set'] + falta * n.generators.loc[gi, 'p_set'] / n.generators.loc[gi, 'p_set'].sum()
        n.generators.loc[gi, 'p_set'] = nuevo.clip(upper=n.generators.loc[gi, 'p_nom'])
        n.export_to_netcdf(config.red(salida))
    else:
        raise SystemExit("El cierre del balance no convergio")
    gen = n.generators[n.generators.bus.isin(es_buses)]
    print(f"\nPunto cerrado: generacion española {gen.p_set.sum():,.1f} MW; demanda "
          f"en barras {carga:,.1f} + perdidas {perd:,.1f} = {carga + perd:,.1f} MW")
    print(gen.groupby('carrier').p_set.sum().round(1).to_string())
    print(f"Guardado en 03_redes_pypsa/{salida}")


if __name__ == '__main__':
    main()
