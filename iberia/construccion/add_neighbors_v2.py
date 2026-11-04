import pypsa
import pandas as pd
import numpy as np
from iberia import config

print("="*70)
print("AÑADIENDO PORTUGAL Y FRANCIA CON DISTRIBUCIÓN PROPORCIONAL")
print("="*70)

# Cargar la red ANTES de añadir vecinos (usamos la red sin vecinos)
n = pypsa.Network(config.red("iberia_final_network.nc"))
n.set_snapshots(pd.DatetimeIndex(['2023-01-01']))

pt_buses = list(n.buses[n.buses.index.str.startswith('PT')].index)
fr_buses = list(n.buses[n.buses.index.str.startswith('FR')].index)

print(f"\nBuses Portugal: {pt_buses}")
print(f"Buses Francia: {fr_buses}")

# --- Datos de cada zona ---
# Portugal: demanda ~4800 MW, mix de generación
PORTUGAL_DEMAND = 4800
# Portugal fue importador neto de ~17% de su demanda en 2025 (9,3 TWh/ano, dato REN/REE) -
# se escala el mismo mix relativo (31/25/17/27) a un total de 83% en vez de 100%.
PORTUGAL_MIX = {
    'Hydro': 0.31 * 0.83,          # 25,73% hidro
    'Onshore': 0.25 * 0.83,        # 20,75% eolica
    'PV': 0.17 * 0.83,             # 14,11% solar
    'Combined_cycle': 0.27 * 0.83, # 22,41% gas
}

# Francia: demanda ~58000 MW, mix de generación
FRANCE_DEMAND = 58000
# Francia es tipicamente exportador neto en Europa por su flota nuclear - un pequeno superavit
# (+2,5%) sobre el mismo mix relativo, sin rediseñar un proxy de 4 buses para un pais de 58 GW.
FRANCE_MIX = {
    'Nuclear': 0.69 * 1.025,        # 70,7% nuclear
    'Hydro': 0.17 * 1.025,          # 17,4% hidro
    'Combined_cycle': 0.09 * 1.025, # 9,2% gas
    'Onshore': 0.03 * 1.025,        # 3,1% eolica
    'PV': 0.02 * 1.025,             # 2,1% solar
}
# NOTA: este superavit de +2,5% se ve en iberia_complete_network.nc (justo despues de
# este script), pero create_scenario_v2.py (etapa siguiente) resta 3.000 MW a la
# generacion nuclear de Francia para simular que España exporta ese excedente a
# Francia - asi que en la red FINAL (iberia_scenario.nc), Francia termina como
# IMPORTADOR neto (~-1.550 MW), no exportador. Esto es intencional y consistente
# con las condiciones reales del apagon del 28 de abril de 2025 (España exportaba
# en TODAS sus interconexiones justo antes del colapso, segun el informe de
# ENTSO-E) - el +2,5% de aqui solo afecta la capacidad/inercia propia de Francia,
# no la direccion final del flujo transfronterizo. Ver tambien la verificacion
# del check 4 de verify_pt_fr_flows.py.

# Parámetros dinámicos por tecnología
TECH_PARAMS = {
    'Nuclear':        {'H': 6.0, 'X_d': 1.8, 'X_d_prime': 0.25},
    'Combined_cycle': {'H': 5.0, 'X_d': 1.8, 'X_d_prime': 0.20},
    'Hydro':          {'H': 4.0, 'X_d': 1.0, 'X_d_prime': 0.30},
    'Onshore':        {'H': 0.0, 'X_d': 0.0, 'X_d_prime': 0.0},
    'PV':             {'H': 0.0, 'X_d': 0.0, 'X_d_prime': 0.0},
}

# --- Función para añadir zona ---
def add_zone(n, buses, zone_prefix, demand, mix):
    """Añade generadores y cargas distribuidas proporcionalmente"""
    n_buses = len(buses)
    demand_per_bus = demand / n_buses
    
    print(f"\nAñadiendo {zone_prefix}: {n_buses} buses, {demand_per_bus:.0f} MW por bus")
    
    for i, bus in enumerate(buses):
        # 1. Añadir carga
        n.add("Load", name=f"load_{zone_prefix}_{bus}",
              bus=bus, p_set=demand_per_bus)
        
        # 2. Añadir generadores proporcionales en cada bus
        for tech, share in mix.items():
            gen_mw = demand_per_bus * share
            if gen_mw < 1:
                continue
            params = TECH_PARAMS[tech]
            n.add(
                "Generator",
                name=f"{zone_prefix}_{tech}_{bus}",
                bus=bus,
                p_nom=gen_mw,
                carrier=tech,
                p_set=gen_mw,
                H=params['H'],
                X_d=params['X_d'],
                X_d_prime=params['X_d_prime'],
            )

# --- Añadir Portugal ---
add_zone(n, pt_buses, 'PT', PORTUGAL_DEMAND, PORTUGAL_MIX)

# --- Añadir Francia ---
add_zone(n, fr_buses, 'FR', FRANCE_DEMAND, FRANCE_MIX)

# --- Verificar balance ---
print(f"\n" + "="*70)
print("BALANCE POR ZONA")
print("="*70)
for zona, prefix in [('España', 'ES'), ('Portugal', 'PT'), ('Francia', 'FR')]:
    buses = n.buses[n.buses.index.str.startswith(prefix)].index
    gen = n.generators[n.generators.bus.isin(buses)].p_set.sum()
    dem = n.loads[n.loads.bus.isin(buses)].p_set.sum()
    print(f"  {zona:12}: Gen={gen:>10.1f} MW | Dem={dem:>10.1f} MW | Balance={gen-dem:+.1f} MW")

# --- Designar un Slack realista ---------------------------------------------
# Sin esto, PyPSA asigna automaticamente como Slack el PRIMER generador por
# orden de creacion (G0001, un panel solar de 161 MW en ES00007) la primera vez
# que se resuelve un flujo de potencia en la cadena - no el de mayor capacidad.
# El resultado matematico del flujo en las lineas es el mismo, pero la historia
# de generacion es absurda (un panel solar generando varias veces su capacidad
# nominal) y no representa como España cubriria de verdad una exportacion.
#
# Se designa en su lugar el generador individual de mayor capacidad de España
# (G0031, hidraulica de embalse, 1.452 MW) - ademas de ser el mas grande, es una
# tecnologia genuinamente flexible/despachable en operacion real, a diferencia
# de nuclear (que corre en base).
SLACK_GEN = 'G0031'
assert SLACK_GEN in n.generators.index, f"{SLACK_GEN} no existe en la red"
assert n.generators.at[SLACK_GEN, 'carrier'] == 'Reservoir', \
    f"se esperaba Reservoir en {SLACK_GEN}, salio {n.generators.at[SLACK_GEN, 'carrier']}"
n.generators['control'] = 'PQ'
n.generators.loc[SLACK_GEN, 'control'] = 'Slack'
print(f"\nSlack designado: {SLACK_GEN} ({n.generators.at[SLACK_GEN, 'carrier']}, "
      f"{n.generators.at[SLACK_GEN, 'p_nom']:.0f} MW)")

# --- Ejecutar flujo ---
print(f"\nEjecutando flujo de potencia...")
n.lpf()
flows = n.lines_t.p0.iloc[0]
loading = (flows.abs() / n.lines.s_nom).fillna(0)

print(f"\n=== RESULTADO DEL FLUJO ===")
print(f"Flujo máximo: {flows.abs().max():.1f} MW")
print(f"Carga máxima: {loading.max()*100:.1f}%")
print(f"Carga media: {loading.mean()*100:.1f}%")
print(f"Líneas >100%: {(loading > 1.0).sum()}")

# --- Flujos transfronterizos ---
print(f"\n" + "="*70)
print("FLUJOS TRANSFRONTERIZOS")
print("="*70)

es_buses = set(n.buses[n.buses.index.str.startswith('ES')].index)
pt_buses_set = set(pt_buses)
fr_buses_set = set(fr_buses)

# ES-FR
cross_fr = n.lines[
    ((n.lines.bus0.isin(es_buses)) & (n.lines.bus1.isin(fr_buses_set))) |
    ((n.lines.bus0.isin(fr_buses_set)) & (n.lines.bus1.isin(es_buses)))
]
total_fr = 0
print(f"\nIntercambio ES ↔ FR:")
for _, line in cross_fr.iterrows():
    flow = flows[line.name]
    flow_es_to_fr = flow if line.bus0.startswith('ES') else -flow
    total_fr += flow_es_to_fr
    print(f"  {line.name}: {flow_es_to_fr:>8.1f} MW")
print(f"  TOTAL: {total_fr:>8.1f} MW")

# ES-PT
cross_pt = n.lines[
    ((n.lines.bus0.isin(es_buses)) & (n.lines.bus1.isin(pt_buses_set))) |
    ((n.lines.bus0.isin(pt_buses_set)) & (n.lines.bus1.isin(es_buses)))
]
total_pt = 0
print(f"\nIntercambio ES ↔ PT:")
for _, line in cross_pt.iterrows():
    flow = flows[line.name]
    flow_es_to_pt = flow if line.bus0.startswith('ES') else -flow
    total_pt += flow_es_to_pt
    print(f"  {line.name}: {flow_es_to_pt:>8.1f} MW")
print(f"  TOTAL: {total_pt:>8.1f} MW")

# --- Guardar ---
n.export_to_netcdf(config.red("iberia_complete_network.nc"))
print(f"\n✓ Red completa guardada")
print(f"  Buses: {len(n.buses)}")
print(f"  Líneas: {len(n.lines)}")
print(f"  Generadores: {len(n.generators)}")
print(f"  Cargas: {len(n.loads)}")
print(f"  Inercia total: {(n.generators.H * n.generators.p_nom).sum()/1000:.1f} GW·s")
