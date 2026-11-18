"""Construye el punto de operacion previo al apagon del 28 de abril de 2025
(~12:33 CEST) con los DATOS MEDIDOS de la plataforma de transparencia de
ENTSO-E, sobre la topologia de iberia_scenario.nc.

FUENTE (desde el 15-nov-2026)
-----------------------------
ENTSO-E Transparency Platform, API REST, dominio ES = 10YES-REE------0,
ultimo cuarto de hora completo antes del evento (12:15-12:30 CEST,
10:15 UTC). Descargado el 13-nov-2026:

    generacion real por tecnologia (A75/A16), 15 min
    demanda real (A65/A16), 15 min ---incluye perdidas, excluye bombeo---
    flujo fisico Espana->Francia (A11), 15 min
    flujo fisico Espana->Portugal (A11) y demanda de Portugal (A65): son
        horarias y la hora 12-13 h incluye los ceros posteriores al apagon,
        asi que se toma la hora 11-12 h CEST.

Lo que NO es dato medido, y se declara:
  - El reparto de la solar entre fotovoltaica y termoelectrica: ENTSO-E
    publica una sola cifra (19.104 MW). La termoelectrica se fija en
    1.500 MW (NERC) y la fotovoltaica es el resto. Que la cifra de ENTSO-E
    incluye las dos lo confirma el balance: con ella, generacion - bombeo -
    demanda = 4.100 MW, lo que se exporta (FR + PT + Marruecos).
  - El reparto de cada tecnologia entre sus generadores (proporcional al
    despacho de iberia_scenario.nc) y de la demanda entre barras (por
    comunidad autonoma, REE 2024).
  - Marruecos y Andorra: la red no tiene esas interconexiones.

CIERRE DEL BALANCE (15-nov-2026)
--------------------------------
Hasta esta fecha el punto no cerraba: Espana tenia 2.600 MW de excedente y
exportaba 3.800, y el nudo de referencia (G0031, 1.452 MW de placa) cubria
el deficit de 1.200 MW mas todas las perdidas produciendo 2.740 MW. Esa
inyeccion concentrada cargaba L0348 al 99,2 % (83,6 % con el deficit
repartido). Ahora el punto se cierra por iteracion con el flujo AC:

  1. la demanda en barras se ajusta para que demanda + perdidas espanolas
     = 24.944 MW, que es como mide ENTSO-E la carga;
  2. el residuo que queda (lo que en la realidad iba a Marruecos y Andorra,
     ~0,7 GW) se reparte entre los generadores espanoles en proporcion a su
     despacho ---salvo la nuclear, que se queda en el dato medido---, hasta
     que el nudo de referencia produce exactamente su p_set.

La version anterior (NERC / fuentes secundarias) se conserva en la copia de
desarrollo del modelo; no se distribuye.

No modifica iberia_scenario.nc: escribe iberia_blackout.nc."""
from iberia import config
import pypsa

n = pypsa.Network(config.red('iberia_scenario.nc'))

# --- Datos medidos de ENTSO-E, 28-abr-2025 ---------------------------------
ENTSOE_SOLAR_MW = 19104.0        # B16, 12:15 CEST (fotovoltaica + termoelectrica)
SOLAR_TERMICA_MW = 1500.0        # NERC; ENTSO-E no la separa
ENTSOE_EOLICA_MW = 3104.0        # B19 (B18 marina = 0)
ENTSOE_NUCLEAR_MW = 3384.0       # B14
ENTSOE_HIDRO_MW = 3400.0         # B11 fluyente + B12 embalse
ENTSOE_TERMICA_MW = 3048.0       # B04 gas 2.204 + B05 carbon 228 + otros 616
ENTSOE_BOMBEO_MW = 3032.0        # consumo de bombeo (serie de consumo de B10)
ENTSOE_DEMANDA_ES_MW = 24944.0   # A65, 12:15 CEST, incluye perdidas
ENTSOE_EXPORT_FR_MW = 1060.0     # A11 ES->FR, 12:15 CEST
ENTSOE_EXPORT_PT_MW = 2308.0     # A11 ES->PT, hora 11-12 CEST
ENTSOE_DEMANDA_PT_MW = 5814.0    # A65 PT, hora 11-12 CEST

OBJETIVO_MW = {
    'PV': ENTSOE_SOLAR_MW - SOLAR_TERMICA_MW,
    'Solar Thermal': SOLAR_TERMICA_MW,
    'Nuclear': ENTSOE_NUCLEAR_MW,
    # BOMBEO: NEGATIVO, estaba CONSUMIENDO. Confirmado por ENTSO-E
    # (3.032 MW) y por NERC, lamina 4 ("Pumped Storage 3GW consume").
    # Despacharlo como generacion borraba los dos escalones de bombeo del
    # P.O. 1.6 (ver Seccion de errores de datos del informe).
    'Pumped_storage': -ENTSOE_BOMBEO_MW,
}

es_buses = n.buses[n.buses.index.str.startswith('ES')].index
es_gens = n.generators[n.generators.bus.isin(es_buses)]


def escalar_tecnologia(carriers, objetivo_mw):
    """Escala p_set de todos los generadores de las tecnologias dadas para
    que su suma total sea objetivo_mw, preservando el reparto relativo entre
    generadores individuales (mismo criterio que el ajuste de Francia en el
    sub-proyecto B)."""
    idx = es_gens[es_gens.carrier.isin(carriers)].index
    actual = float(n.generators.loc[idx, 'p_set'].sum())
    if actual <= 0:
        print(f"  AVISO: {carriers} no tiene despacho actual, no se puede escalar")
        return
    factor = objetivo_mw / actual
    n.generators.loc[idx, 'p_set'] *= factor
    print(f"  {carriers}: {actual:.1f} -> {objetivo_mw:.1f} MW (factor {factor:.4f})")


print("Generacion de España al dato medido de ENTSO-E (12:15 CEST)...")
for carrier, objetivo in OBJETIVO_MW.items():
    escalar_tecnologia([carrier], objetivo)
escalar_tecnologia(['Onshore', 'Offshore_floating'], ENTSOE_EOLICA_MW)
escalar_tecnologia(['Reservoir', 'Run_of_river'], ENTSOE_HIDRO_MW)

# Termica (gas, carbon, cogeneracion, biomasa y residuos): ENTSO-E la da
# por tipo, pero la placa de biomasa y residuos del modelo (530 MW) no
# alcanza los 616 MW medidos de "otros". Se reparte el total termico
# proporcional a la placa, el criterio del resto del proyecto.
TERMICA = ['Coal', 'Gas_turbine', 'ICCC', 'Steam_turbine', 'Biomass',
           'Combined_cycle']
idx_term = es_gens[es_gens.carrier.isin(TERMICA)].index
placa_term = n.generators.loc[idx_term, 'p_nom']
n.generators.loc[idx_term, 'p_set'] = placa_term / placa_term.sum() * ENTSOE_TERMICA_MW
print(f"  termica (gas, carbon, cogeneracion y otros): {ENTSOE_TERMICA_MW:.1f} MW")

# --- Demanda de España: punto de partida. El cierre la ajusta despues para
# que demanda en barras + perdidas = 24.944 MW. Se arranca con una
# estimacion de perdidas de 850 MW.
es_loads = n.loads[n.loads.bus.isin(es_buses)].index
_d0 = ENTSOE_DEMANDA_ES_MW - 850.0
n.loads.loc[es_loads, 'p_set'] *= _d0 / float(n.loads.loc[es_loads, 'p_set'].sum())

# --- Portugal y Francia: demanda e intercambio medidos ---
pt_buses = n.buses[n.buses.index.str.startswith('PT')].index
fr_buses = n.buses[n.buses.index.str.startswith('FR')].index

pt_loads = n.loads[n.loads.bus.isin(pt_buses)].index
n.loads.loc[pt_loads, 'p_set'] *= ENTSOE_DEMANDA_PT_MW / float(n.loads.loc[pt_loads, 'p_set'].sum())
pt_gen_idx = n.generators[n.generators.bus.isin(pt_buses)].index
pt_gen_actual = float(n.generators.loc[pt_gen_idx, 'p_set'].sum())
n.generators.loc[pt_gen_idx, 'p_set'] *= (ENTSOE_DEMANDA_PT_MW - ENTSOE_EXPORT_PT_MW) / pt_gen_actual
print(f"\nPortugal: demanda {ENTSOE_DEMANDA_PT_MW:,.0f} MW, generacion "
      f"{n.generators.loc[pt_gen_idx, 'p_set'].sum():,.0f} MW, importa "
      f"{ENTSOE_EXPORT_PT_MW:,.0f} MW de España")

fr_dem = float(n.loads[n.loads.bus.isin(fr_buses)].p_set.sum())
fr_gen_idx = n.generators[n.generators.bus.isin(fr_buses)].index
fr_gen_actual = float(n.generators.loc[fr_gen_idx, 'p_set'].sum())
n.generators.loc[fr_gen_idx, 'p_set'] *= (fr_dem - ENTSOE_EXPORT_FR_MW) / fr_gen_actual
print(f"Francia: importa {ENTSOE_EXPORT_FR_MW:,.0f} MW de España")

n.export_to_netcdf(config.red('iberia_blackout.nc'))

# --- Cierre del balance con el flujo AC (ver docstring) -------------------
from iberia import analisis_n1 as an                    # noqa: E402
from iberia import limites_reactivos_espana as L        # noqa: E402

print("\nCerrando el balance con el flujo AC (limites de reactivo activos)...")
for it in range(1, 11):
    base, _ = an.caso_base(verbose=False, con_limites=True, red='apagon')
    nl, _ = L.aplicar(base, verbose=False)
    g = nl.generators
    slack = g.index[g.control == 'Slack'][0]
    desvio = float(nl.generators_t.p.iloc[0][slack] - g.at[slack, 'p_set'])
    en_es0 = nl.lines.bus0.isin(es_buses)
    en_es0_t = nl.transformers.bus0.isin(es_buses)
    perd_es = float((nl.lines_t.p0.iloc[0] + nl.lines_t.p1.iloc[0])[en_es0].sum()
                    + (nl.transformers_t.p0.iloc[0] + nl.transformers_t.p1.iloc[0])[en_es0_t].sum())
    n = pypsa.Network(config.red('iberia_blackout.nc'))
    carga_es = float(n.loads.loc[es_loads, 'p_set'].sum())
    exceso_dem = carga_es + perd_es - ENTSOE_DEMANDA_ES_MW
    print(f"  iteracion {it}: nudo de referencia {slack} desvio {desvio:+8.1f} MW | "
          f"demanda en barras {carga_es:9.1f} + perdidas {perd_es:6.1f} = "
          f"{carga_es + perd_es:9.1f} MW")
    if abs(desvio) < 1.0 and abs(exceso_dem) < 1.0:
        break
    # (1) demanda en barras + perdidas = dato de ENTSO-E
    n.loads.loc[es_loads, 'p_set'] *= (carga_es - exceso_dem) / carga_es
    # (2) lo que el nudo de referencia aun tendria que cubrir se reparte
    #     entre los generadores espanoles que producen, proporcional a su
    #     despacho. Quedan fuera el propio nudo de referencia (conserva su
    #     p_set) y la NUCLEAR: no modula, y su cifra es la mas fiable del
    #     punto (ENTSO-E la publica unidad a unidad, cobertura del 100 %).
    falta = desvio - exceso_dem
    gi = n.generators[n.generators.bus.isin(es_buses) & (n.generators.p_set > 0)
                      & (n.generators.index != slack)
                      & (n.generators.carrier != 'Nuclear')].index
    n.generators.loc[gi, 'p_set'] += falta * n.generators.loc[gi, 'p_set'] / n.generators.loc[gi, 'p_set'].sum()
    n.export_to_netcdf(config.red('iberia_blackout.nc'))
else:
    raise SystemExit("El cierre del balance no convergio en 10 iteraciones")

gen_es = float(n.generators[n.generators.bus.isin(es_buses) & (n.generators.p_set > 0)].p_set.sum())
print(f"\nPunto cerrado: generacion española {gen_es:,.1f} MW "
      f"(ENTSO-E {ENTSOE_SOLAR_MW + ENTSOE_EOLICA_MW + ENTSOE_NUCLEAR_MW + ENTSOE_HIDRO_MW + ENTSOE_TERMICA_MW:,.0f}), "
      f"bombeo {ENTSOE_BOMBEO_MW:,.0f}, demanda en barras {carga_es:,.1f} + perdidas {perd_es:,.1f} MW")
print(f"✓ Guardado en data/redes/iberia_blackout.nc")
