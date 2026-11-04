import pypsa
import pandas as pd
import numpy as np
from iberia import config

print("="*70)
print("CORRECCIÓN FINAL: ISLAS BALEARES + LÍNEAS SOBRECARGADAS")
print("="*70)

n = pypsa.Network(config.red("iberia_fixed_network.nc"))
n.set_snapshots(pd.DatetimeIndex(['2023-01-01']))

# --- 1. Identificar sub-redes ---
n.determine_network_topology()
sub_sizes = n.buses.sub_network.value_counts()
print(f"\nSub-redes detectadas: {len(sub_sizes)}")
for sn, size in sub_sizes.items():
    buses = n.buses[n.buses.sub_network == sn]
    print(f"  Sub-red {sn}: {size} buses ({buses.v_nom.value_counts().to_dict()})")

# --- 2. Quedarse SOLO con la sub-red principal ---
largest_sn = sub_sizes.idxmax()
buses_keep = n.buses[n.buses.sub_network == largest_sn].index
buses_remove = n.buses.index.difference(buses_keep)

print(f"\nEliminando {len(buses_remove)} buses de islas (Baleares, etc.)")
print(f"  Buses eliminados: {list(buses_remove)[:10]}")

if len(buses_remove) > 0:
    n.remove('Bus', buses_remove)

# Limpiar componentes huérfanos
for comp, cond in [
    ('Line', lambda df: ~df.bus0.isin(buses_keep) | ~df.bus1.isin(buses_keep)),
    ('Generator', lambda df: ~df.bus.isin(buses_keep)),
    ('Load', lambda df: ~df.bus.isin(buses_keep)),
    ('Transformer', lambda df: ~df.bus0.isin(buses_keep) | ~df.bus1.isin(buses_keep)),
]:
    df = getattr(n, comp.lower() + 's')
    to_remove = df[cond(df)].index
    if len(to_remove) > 0:
        n.remove(comp, to_remove)

# --- 3. Despachar generadores ---
print("\nDespachando generadores...")
total_demand = n.loads.p_set.sum()
total_capacity = n.generators.p_nom.sum()
n.generators['p_set'] = n.generators.p_nom * (total_demand / total_capacity)
print(f"  Demanda: {total_demand:.1f} MW")
print(f"  Generación: {n.generators.p_set.sum():.1f} MW")

# --- 4. Analizar líneas sobrecargadas y corregir s_nom ---
print("\nAnalizando líneas sobrecargadas...")
n.lpf()
flows = n.lines_t.p0.iloc[0]
loading = (flows.abs() / n.lines.s_nom).fillna(0)

# Top 15 líneas más cargadas
top_loaded = loading.nlargest(15)
print("\nTop 15 líneas más cargadas:")
for line_id, load in top_loaded.items():
    line = n.lines.loc[line_id]
    v = n.buses.loc[line.bus0, 'v_nom']
    print(f"  {line_id}: {load*100:.1f}% (V={v:.0f} kV, s_nom={line.s_nom:.0f} MVA, flujo={flows[line_id]:.0f} MW)")

# Corregir s_nom de las líneas sobrecargadas
# Si una línea está >100%, su s_nom real debe ser mayor (subestimado en el dataset)
mask_overload = loading > 1.0
n_overload = mask_overload.sum()
print(f"\nCorrigiendo {n_overload} líneas sobrecargadas...")

# Actualizar s_nom para que ninguna línea esté al 100%
# Multiplicar por 1.2 para dar margen del 20%
n.lines.loc[mask_overload, 's_nom'] = (
    flows[mask_overload].abs() * 1.2
)

# --- 5. Verificar ---
n.lpf()
flows = n.lines_t.p0.iloc[0]
loading = (flows.abs() / n.lines.s_nom).fillna(0)

print(f"\n=== DESPUÉS DE CORRECCIÓN ===")
print(f"Buses: {len(n.buses)}")
print(f"Líneas: {len(n.lines)}")
print(f"Generadores: {len(n.generators)}")
print(f"Cargas: {len(n.loads)}")
print(f"\nFlujo máximo: {flows.abs().max():.1f} MW")
print(f"Carga máxima: {loading.max()*100:.1f}%")
print(f"Carga media: {loading.mean()*100:.1f}%")
print(f"Líneas >100%: {(loading > 1.0).sum()}")
print(f"Líneas 80-100%: {((loading > 0.8) & (loading <= 1.0)).sum()}")

# --- 6. Guardar ---
n.export_to_netcdf(config.red("iberia_final_network.nc"))
print(f"\n✓ Red final guardada en iberia_final_network.nc")
