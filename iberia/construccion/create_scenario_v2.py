import pypsa
import pandas as pd
import numpy as np
from iberia import config

print("="*70)
print("ESCENARIO: ESPAÑA EXPORTA 3000 MW A FRANCIA")
print("="*70)

n = pypsa.Network(config.red("iberia_complete_network.nc"))
n.set_snapshots(pd.DatetimeIndex(['2023-01-01']))

EXCHANGE_MW = 3000  # España exporta a Francia

# --- 1. AUMENTAR generación renovable en España ---
es_buses = n.buses[n.buses.index.str.startswith('ES')].index
es_gens = n.generators[n.generators.bus.isin(es_buses)].index

renovable_mask = n.generators.loc[es_gens, 'carrier'].isin(['PV', 'Onshore'])
renovable_gens = n.generators.loc[es_gens][renovable_mask].index

# Reparto PROPORCIONAL AL MARGEN DISPONIBLE (p_nom - p_set), no a partes
# iguales.
#
# Antes era `EXCHANGE_MW / len(renovable_gens)`: 4,4910 MW a CADA uno de
# los 668 renovables espanoles, tuviera 1 MW o 1.401 MW de placa. Tres
# consecuencias, todas malas:
#
#  (a) 82 generadores (el 12,3%) recibian mas MW que toda su placa. De
#      ahi salian los "96 fotovoltaicos con p_set > p_nom, hasta 4,7x"
#      que el sub-proyecto F tuvo que absorber con una red de seguridad:
#      no eran un bug de los datos de origen, los creaba ESTA linea.
#  (b) Los 3.000 MW entraban en los buses equivocados. Medido: 2.807,8 MW
#      de los 3.000 (el 93,6%) estaban mal colocados respecto a un
#      reparto proporcional, lo que falsea el patron de flujos internos
#      y transfronterizos.
#  (c) Un generador de 1 MW no puede subir 4,5 MW. No es una
#      aproximacion: es un punto de operacion imposible.
#
# El margen disponible es el criterio fisico: una central solo puede
# subir hasta su placa, y reparte el esfuerzo en proporcion a lo que le
# queda libre. Es ademas lo que haria un despacho real.
margen = (n.generators.loc[renovable_gens, 'p_nom']
          - n.generators.loc[renovable_gens, 'p_set']).clip(lower=0.0)
margen_total = float(margen.sum())

if margen_total < EXCHANGE_MW:
    raise SystemExit(
        f"Las renovables espanolas solo tienen {margen_total:.0f} MW de "
        f"margen libre y el escenario pide {EXCHANGE_MW} MW. Hay que "
        f"reducir EXCHANGE_MW o ampliar el conjunto de generadores que "
        f"participan.")

extra = margen / margen_total * EXCHANGE_MW
n.generators.loc[renovable_gens, 'p_set'] += extra

# Comprobacion de que lo anterior hizo lo que dice: ningun generador
# puede acabar por encima de su placa. Si esto salta, el reparto esta
# mal y NO conviene seguir construyendo sobre el.
excedidos = n.generators.loc[renovable_gens]
excedidos = excedidos[excedidos.p_set > excedidos.p_nom + 1e-6]
if len(excedidos):
    raise SystemExit(
        f"{len(excedidos)} generadores quedaron por encima de su placa "
        f"tras el reparto proporcional, lo que no deberia poder pasar:\n"
        f"{excedidos[['p_nom', 'p_set']].head().to_string()}")

print(f"\n1. España: +{EXCHANGE_MW} MW repartidos entre "
      f"{len(renovable_gens)} renovables, proporcional al margen libre")
print(f"   margen total disponible : {margen_total:,.0f} MW "
      f"(se usa el {100*EXCHANGE_MW/margen_total:.1f}%)")
print(f"   reparto                 : {extra.min():.3f} - {extra.max():.1f} MW "
      f"por generador")

# --- 2. REDUCIR generación en Francia para absorber el excedente ---
fr_buses = n.buses[n.buses.index.str.startswith('FR')].index
fr_gens = n.generators[n.generators.bus.isin(fr_buses)].index

# Reducir generación nuclear (los que más pueden regular)
nuclear_mask = n.generators.loc[fr_gens, 'carrier'] == 'Nuclear'
nuclear_gens = n.generators.loc[fr_gens][nuclear_mask].index

reduccion_per_gen = EXCHANGE_MW / len(nuclear_gens)
n.generators.loc[nuclear_gens, 'p_set'] -= reduccion_per_gen

print(f"2. Francia: -{EXCHANGE_MW} MW en {len(nuclear_gens)} nucleares")

# --- 3. Verificar balances ---
print(f"\n" + "="*70)
print("BALANCE POR ZONA (después del ajuste)")
print("="*70)
for zona, prefix in [('España', 'ES'), ('Portugal', 'PT'), ('Francia', 'FR')]:
    buses = n.buses[n.buses.index.str.startswith(prefix)].index
    gen = n.generators[n.generators.bus.isin(buses)].p_set.sum()
    dem = n.loads[n.loads.bus.isin(buses)].p_set.sum()
    balance = gen - dem
    print(f"  {zona:12}: Gen={gen:>10.1f} MW | Dem={dem:>10.1f} MW | Balance={balance:>+10.1f} MW")

# --- 4. Flujo de potencia ---
print(f"\nEjecutando flujo de potencia...")
n.lpf()

flows = n.lines_t.p0.iloc[0]
loading = (flows.abs() / n.lines.s_nom).fillna(0)

print(f"\n=== RESULTADO ===")
print(f"Flujo máximo: {flows.abs().max():.1f} MW")
print(f"Carga máxima: {loading.max()*100:.1f}%")
print(f"Líneas >100%: {(loading > 1.0).sum()}")

# --- 5. Flujos transfronterizos ---
es_set = set(n.buses[n.buses.index.str.startswith('ES')].index)
fr_set = set(n.buses[n.buses.index.str.startswith('FR')].index)
pt_set = set(n.buses[n.buses.index.str.startswith('PT')].index)

print(f"\n" + "="*70)
print("FLUJOS TRANSFRONTERIZOS")
print("="*70)

cross_fr = n.lines[
    ((n.lines.bus0.isin(es_set)) & (n.lines.bus1.isin(fr_set))) |
    ((n.lines.bus0.isin(fr_set)) & (n.lines.bus1.isin(es_set)))
]
total_fr = 0
print(f"\nES ↔ FR:")
for _, line in cross_fr.iterrows():
    flow = flows[line.name]
    flow_es_fr = flow if line.bus0.startswith('ES') else -flow
    total_fr += flow_es_fr
    print(f"  {line.name}: {flow_es_fr:>8.1f} MW")
print(f"  TOTAL ES→FR: {total_fr:>8.1f} MW")

cross_pt = n.lines[
    ((n.lines.bus0.isin(es_set)) & (n.lines.bus1.isin(pt_set))) |
    ((n.lines.bus0.isin(pt_set)) & (n.lines.bus1.isin(es_set)))
]
total_pt = 0
print(f"\nES ↔ PT:")
for _, line in cross_pt.iterrows():
    flow = flows[line.name]
    flow_es_pt = flow if line.bus0.startswith('ES') else -flow
    total_pt += flow_es_pt
    print(f"  {line.name}: {flow_es_pt:>8.1f} MW")
print(f"  TOTAL ES→PT: {total_pt:>8.1f} MW")

# --- 6. Guardar ---
n.export_to_netcdf(config.red("iberia_scenario.nc"))
print(f"\n✓ Escenario guardado")
