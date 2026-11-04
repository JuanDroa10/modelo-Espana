import pypsa
import pandas as pd
import numpy as np
from iberia import config

n = pypsa.Network(config.red("iberia_scenario.nc"))
n.set_snapshots(pd.DatetimeIndex(['2023-01-01']))

# Corregir cualquier s_nom negativo
mask_neg = n.lines.s_nom < 0
print(f"Líneas con s_nom negativo: {mask_neg.sum()}")
if mask_neg.sum() > 0:
    # El s_nom debe ser positivo (es la capacidad, no el flujo)
    n.lines.loc[mask_neg, 's_nom'] = n.lines.loc[mask_neg, 's_nom'].abs()
    print(f"  Corregidas: {list(n.lines[mask_neg].index)}")

# Re-ejecutar flujo
n.lpf()
flows = n.lines_t.p0.iloc[0]
loading = (flows.abs() / n.lines.s_nom).fillna(0)

print(f"\nDespués de corregir:")
print(f"  Carga máxima: {loading.max()*100:.1f}%")
print(f"  Líneas >100%: {(loading > 1.0).sum()}")

n.export_to_netcdf(config.red("iberia_scenario.nc"))
print("✓ Guardado")
