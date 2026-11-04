import pypsa
import pandas as pd
import numpy as np
from scipy.spatial import cKDTree
from iberia import config

n = pypsa.Network(config.red("iberia_fixed_network.nc"))
n.set_snapshots(pd.DatetimeIndex(['2023-01-01']))

# Árbol KD para buscar vecinos rápidamente
coords = n.buses[['x', 'y']].values
tree = cKDTree(coords)

# Distancia umbral (en grados): ~1 km ≈ 0.01°
DIST_THRESHOLD = 0.005

print("Buscando pares de buses cercanos con distinto voltaje...")
n_added = 0
for i, bus_i in enumerate(n.buses.itertuples()):
    # Buscar vecinos dentro del umbral
    idx_neighbors = tree.query_ball_point([bus_i.x, bus_i.y], DIST_THRESHOLD)
    for j in idx_neighbors:
        if i >= j:
            continue
        bus_j = n.buses.iloc[j]
        if bus_i.v_nom == bus_j.v_nom:
            continue
        
        # Verificar no duplicado
        bus0, bus1 = (bus_i.Index, bus_j.name) if bus_i.v_nom < bus_j.v_nom else (bus_j.name, bus_i.Index)
        existing = n.transformers[
            ((n.transformers.bus0 == bus0) & (n.transformers.bus1 == bus1)) |
            ((n.transformers.bus0 == bus1) & (n.transformers.bus1 == bus0))
        ]
        if len(existing) > 0:
            continue
        
        # s_nom PROVISIONAL: lo fija despues dimensionar_trafos.py, que
        # lo deriva del flujo real de los dos puntos de operacion. Aqui no
        # se puede: el flujo no se conoce hasta tener la red entera.
        # Dejarlo en 1.000 para los 179 era el defecto; queda como semilla.
        #
        # x = 0,10 p.u. es CORRECTO (va sobre s_nom como base; vsc de
        # 10-12 % es lo tipico en transmision). r = 0,0025 p.u. es el
        # vscr ~ 0,25 % de los tipos estandar de PyPSA: antes estaba en
        # 0,010, cuatro veces mas resistivo de lo real, lo que inflaba
        # las perdidas del modelo.
        n.add('Transformer', name=f'TR_{bus0}_{bus1}',
              bus0=bus0, bus1=bus1, s_nom=1000, x=0.1, r=0.0025)
        n_added += 1

print(f"  Añadidos: {n_added}")

n.determine_network_topology()
print(f"  Sub-redes: {n.buses.sub_network.nunique()}")
print(f"  Tamaños: {n.buses.sub_network.value_counts().head(10).to_dict()}")

n.export_to_netcdf(config.red("iberia_fixed_network.nc"))
print("✓ Guardada red corregida v2")
