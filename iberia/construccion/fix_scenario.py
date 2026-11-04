import pypsa
import pandas as pd
import numpy as np
from iberia import config

n = pypsa.Network(config.red("iberia_scenario.nc"))
n.set_snapshots(pd.DatetimeIndex(['2023-01-01']))

# Ejecutar flujo base
n.lpf()
flows = n.lines_t.p0.iloc[0]
loading = (flows.abs() / n.lines.s_nom).fillna(0)

# Corregir s_nom de líneas sobrecargadas
mask_overload = loading > 1.0
print(f"Líneas sobrecargadas: {mask_overload.sum()}")
for line_id in loading[mask_overload].index:
    old_snom = n.lines.loc[line_id, 's_nom']
    new_snom = flows[line_id] * 1.3  # 30% margen
    n.lines.loc[line_id, 's_nom'] = new_snom
    print(f"  {line_id}: {old_snom:.0f} -> {new_snom:.0f} MVA")

# Verificar
n.lpf()
flows = n.lines_t.p0.iloc[0]
loading = (flows.abs() / n.lines.s_nom).fillna(0)
print(f"\nDespués: Carga máxima = {loading.max()*100:.1f}%")
print(f"Líneas >100%: {(loading > 1.0).sum()}")

n.export_to_netcdf(config.red("iberia_scenario.nc"))
print("✓ Escenario corregido")
