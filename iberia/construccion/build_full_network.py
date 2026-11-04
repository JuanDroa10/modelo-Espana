import pandas as pd
import pypsa
import numpy as np
from iberia import config

# --- Configuración ---
OUTPUT_NETWORK = config.red("iberia_full_network.nc")
FREQ_HZ = 50.0

# --- 1. Cargar CSV ---
print("Cargando archivos CSV...")
buses = pd.read_csv(config.dato("bus_data.csv"))
lines = pd.read_csv(config.dato("line_data.csv"))
generators = pd.read_csv(config.dato("generation_data.csv"))
load_dist = pd.read_csv(config.dato("load_distribution_data.csv"))
load_ts = pd.read_csv(config.dato("load_time_series_data.csv"))

# --- 2. Crear red PyPSA ---
print("Creando red PyPSA...")
n = pypsa.Network()
n.set_snapshots(pd.DatetimeIndex(["2023-01-01 00:00:00"], name="snapshot"))

# --- 3. Añadir buses ---
print(f"Añadiendo {len(buses)} buses...")
bus_ids_validos = set(buses["bus_id"].astype(str))
for _, bus in buses.iterrows():
    n.add(
        "Bus",
        name=str(bus["bus_id"]),
        v_nom=float(bus["voltage"]),
        x=float(bus["x"]),
        y=float(bus["y"]),
        carrier="AC",
    )

# --- 4. Añadir líneas AC ---
print(f"Añadiendo líneas...")
n_lines_added = 0
n_lines_skipped = 0
for _, line in lines.iterrows():
    # Saltar líneas HVDC
    if str(line["dc"]).lower() == "t":
        n_lines_skipped += 1
        continue
    # Saltar líneas con buses no definidos
    if str(line["bus0"]) not in bus_ids_validos or str(line["bus1"]) not in bus_ids_validos:
        n_lines_skipped += 1
        continue

    v = float(line["voltage"])
    length = float(line["length"])
    circuits = int(line["circuits"])
    r_per_km = float(line["r_per_length"])
    x_per_km = float(line["x_per_length"])
    c_per_km_nf = float(line["c_per_length"])
    imax = float(line["Imax"])

    # CADA FILA DE line_data.csv ES UN CIRCUITO, no un corredor.
    # Verificado: agrupando por line_id (quitando el sufijo a/b/c que
    # enumera los circuitos), 1.432 de 1.432 grupos tienen exactamente
    # tantas filas como declara su columna `circuits`, y `circuits` es
    # uniforme dentro de cada grupo. 100%, sin una sola excepcion.
    #
    # Por tanto NO se divide r/x entre circuits ni se multiplica b/s_nom
    # por circuits: esa es la convencion de PyPSA para UN objeto Line que
    # agrupa varios circuitos en paralelo, y aqui se crea un objeto POR
    # CIRCUITO. Hacer las dos cosas dejaba el corredor con la impedancia
    # dividida entre circuits^2 y la capacidad y susceptancia por
    # circuits^2.
    #
    # La prueba que lo zanja es fisica, no de regresion: la impedancia
    # caracteristica Zc = sqrt(x/b) de una linea aerea es una constante
    # conocida. Con el calculo anterior salia 119,1 ohm a 400 kV, 138,4 a
    # 220 y 181,3 a 132 - exactamente LA MITAD de la fisica real
    # (240-280 / 260-300 / 330-400). Lo comprueba verificar_parametros_linea.py.
    #
    # `circuits` se sigue leyendo para no perder el dato, pero ya no entra
    # en ningun calculo.
    r_total = r_per_km * length
    x_total = x_per_km * length
    c_total_f = c_per_km_nf * 1e-9 * length
    b_total = 2 * np.pi * FREQ_HZ * c_total_f
    s_nom = np.sqrt(3) * v * imax  # MVA de UN circuito

    n.add(
        "Line",
        name=str(line["line_id"]),
        bus0=str(line["bus0"]),
        bus1=str(line["bus1"]),
        r=r_total,
        x=x_total,
        b=b_total,
        s_nom=s_nom,
        length=length,
        # 1, no `circuits`: este objeto ES un circuito. Dejarlo en
        # `circuits` era una bomba de relojeria - hoy es inerte porque
        # `type` esta vacio en las 2.156 lineas, pero si alguien asignara
        # un tipo, PyPSA volveria a dividir la impedancia (apply_line_types).
        num_parallel=1,
    )
    n_lines_added += 1
print(f"  Líneas añadidas: {n_lines_added}, saltadas: {n_lines_skipped}")

# --- 5. Añadir generadores ---
print(f"Añadiendo {len(generators)} generadores...")
tech_params = {
    "Nuclear":        {"H": 6.0, "X_d": 1.8, "X_d_prime": 0.25},
    "Combined_cycle": {"H": 5.0, "X_d": 1.8, "X_d_prime": 0.20},
    "PV":             {"H": 0.0, "X_d": 0.0, "X_d_prime": 0.0},
    "Solar Thermal":  {"H": 0.0, "X_d": 0.0, "X_d_prime": 0.0},
    # Hotfix Task 6b (ampliacion no prevista en el brief original): estas categorias
    # existen en generation_data.csv desde el commit inicial b00b35e (verificado
    # identico) pero nunca tuvieron entrada en tech_params, asi que siempre cayeron
    # en el default H=0. Sin ellas, H>0 queda en 113/978 (no coincide con el
    # historico 240/978) porque solo Nuclear+Combined_cycle+Hydro estaban cubiertas.
    # Anadidas con los mismos valores ya usados para su familia sincrona equivalente:
    "Run_of_river":   {"H": 4.0, "X_d": 1.0, "X_d_prime": 0.30},  # familia Hydro
    "Reservoir":      {"H": 4.0, "X_d": 1.0, "X_d_prime": 0.30},  # familia Hydro
    "Pumped_storage": {"H": 4.0, "X_d": 1.0, "X_d_prime": 0.30},  # familia Hydro
    "Coal":           {"H": 6.0, "X_d": 1.8, "X_d_prime": 0.30},  # era 5.0/1.8/0.20 — corregido con el valor real de b00b35e
    "Gas_turbine":    {"H": 5.0, "X_d": 1.8, "X_d_prime": 0.20},  # familia termica
    "ICCC":           {"H": 5.0, "X_d": 1.8, "X_d_prime": 0.25},  # X_d_prime era 0.20 — corregido con el valor real de b00b35e
    "Steam_turbine":  {"H": 6.0, "X_d": 1.8, "X_d_prime": 0.30},  # era 5.0/1.8/0.20 — corregido con el valor real de b00b35e
    "Biomass":        {"H": 5.0, "X_d": 1.8, "X_d_prime": 0.25},  # X_d_prime era 0.20 — corregido con el valor real de b00b35e
}
n_gen_added = 0
for _, gen in generators.iterrows():
    if str(gen["bus_id"]) not in bus_ids_validos:
        continue
    tech = str(gen["technology"])
    params = tech_params.get(tech, {"H": 0.0, "X_d": 0.0, "X_d_prime": 0.0})
    n.add(
        "Generator",
        name=str(gen["unit_id"]),
        bus=str(gen["bus_id"]),
        p_nom=float(gen["capacity_mw"]),
        carrier=tech,
        H=params["H"],
        X_d=params["X_d"],
        X_d_prime=params["X_d_prime"],
    )
    n_gen_added += 1
print(f"  Generadores añadidos: {n_gen_added}")

# --- 6. Añadir demanda ---
print("Procesando demanda...")
# Convertir timestamps con utc=True para evitar el error de zonas horarias mezcladas
load_ts["timestamp"] = pd.to_datetime(load_ts["timestamp"], utc=True)
peak_demand = load_ts["consumption"].max()
mean_demand = load_ts["consumption"].mean()
print(f"  Demanda pico: {peak_demand} MW")
print(f"  Demanda media: {mean_demand:.1f} MW")

# Usar la demanda media para el snapshot único
demand_value = mean_demand

n_load_added = 0
for _, row in load_dist.iterrows():
    bus_id = str(row["bus_id"])
    if bus_id not in bus_ids_validos:
        continue
    demand_mw = demand_value * float(row["demand"])
    if demand_mw > 0:
        n.add(
            "Load",
            name=f"load_{bus_id}",
            bus=bus_id,
            p_set=demand_mw,
        )
        n_load_added += 1
print(f"  Cargas añadidas: {n_load_added}")

# --- 7. Guardar red ---
print(f"Guardando red en {OUTPUT_NETWORK}...")
n.export_to_netcdf(OUTPUT_NETWORK)
print("\n¡Red completa creada exitosamente!")
print(f"  Buses: {len(n.buses)}")
print(f"  Líneas: {len(n.lines)}")
print(f"  Generadores: {len(n.generators)}")
print(f"  Cargas: {len(n.loads)}")
