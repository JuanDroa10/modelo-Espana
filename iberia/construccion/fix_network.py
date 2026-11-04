import pypsa
import pandas as pd
import numpy as np
from collections import defaultdict
from iberia import config

print("Cargando red original...")
n = pypsa.Network(config.red("iberia_full_network.nc"))
n.set_snapshots(pd.DatetimeIndex(['2023-01-01']))

print(f"Antes: {len(n.buses)} buses, {len(n.lines)} líneas, {len(n.transformers)} trafos")

# --- 1. Encontrar buses que comparten la misma ubicación (x, y) ---
print("\nBuscando buses en la misma ubicación...")
buses_by_location = defaultdict(list)
for bus_name, bus in n.buses.iterrows():
    # Redondear a 5 decimales (~1 m de precisión)
    loc = (round(bus.x, 5), round(bus.y, 5))
    buses_by_location[loc].append((bus_name, bus.v_nom))

# --- 2. Añadir transformadores entre buses co-localizados de distinto voltaje ---
print("Añadiendo transformadores...")
n_trafos_added = 0
for loc, buses_list in buses_by_location.items():
    if len(buses_list) < 2:
        continue
    
    # Ordenar por voltaje
    buses_sorted = sorted(buses_list, key=lambda x: x[1])
    
    # Conectar cada par consecutivo (típicamente 132→220→400)
    for i in range(len(buses_sorted) - 1):
        bus_low, v_low = buses_sorted[i]
        bus_high, v_high = buses_sorted[i + 1]
        
        if v_low == v_high:
            continue
        
        # Verificar que no exista ya
        existing = n.transformers[
            ((n.transformers.bus0 == bus_low) & (n.transformers.bus1 == bus_high)) |
            ((n.transformers.bus0 == bus_high) & (n.transformers.bus1 == bus_low))
        ]
        if len(existing) > 0:
            continue
        
        # Añadir transformador con parámetros típicos
        trafo_name = f"TR_{bus_low}_{bus_high}"
        n.add(
            "Transformer",
            name=trafo_name,
            bus0=bus_low,
            bus1=bus_high,
            s_nom=1000,   # MVA
            x=0.1,        # Reactancia típica en pu
            r=0.01,       # Resistencia típica en pu
        )
        n_trafos_added += 1

print(f"  Transformadores añadidos: {n_trafos_added}")

# --- 3. Verificar conectividad ---
print("\nVerificando conectividad...")
n.determine_network_topology()
n_subredes = n.buses.sub_network.nunique()
print(f"  Sub-redes después: {n_subredes}")

if n_subredes > 1:
    # Mostrar las sub-redes más grandes
    sizes = n.buses.sub_network.value_counts()
    print(f"  Tamaños de sub-redes:")
    for sn, size in sizes.head(10).items():
        print(f"    Sub-red {sn}: {size} buses")

# --- 4. Guardar ---
n.export_to_netcdf(config.red("iberia_fixed_network.nc"))
print(f"\n✓ Red corregida guardada")
print(f"  Buses: {len(n.buses)}")
print(f"  Líneas: {len(n.lines)}")
print(f"  Transformadores: {len(n.transformers)}")
print(f"  Generadores: {len(n.generators)}")
print(f"  Cargas: {len(n.loads)}")
