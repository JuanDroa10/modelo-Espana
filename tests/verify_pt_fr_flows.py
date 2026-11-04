"""Verifica que Portugal se comporte como importador neto realista, que el
Slack de España sea el generador flexible designado (no uno arbitrario), y que
en la red FINAL España termine exportando a Francia (via create_scenario_v2.py),
no al reves."""
import sys

from iberia import config
import pypsa


def main():
    n = pypsa.Network(config.red("iberia_scenario.nc"))
    n.lpf()

    fallos = []

    # --- 1. Portugal es importador neto ---
    pt_buses = n.buses[n.buses.index.str.startswith("PT")].index
    pt_gen = n.generators[n.generators.bus.isin(pt_buses)].p_set.sum()
    pt_dem = n.loads[n.loads.bus.isin(pt_buses)].p_set.sum()
    print(f"Portugal: Gen={pt_gen:.1f} MW | Dem={pt_dem:.1f} MW | "
          f"Balance={pt_gen - pt_dem:+.1f} MW")
    if pt_gen >= pt_dem:
        fallos.append(f"Portugal no es importador neto: Gen={pt_gen:.1f} >= Dem={pt_dem:.1f}")

    # --- 2. El flujo neto ES->PT es positivo (España exporta a Portugal) ---
    es_buses = set(n.buses[n.buses.index.str.startswith("ES")].index)
    pt_buses_set = set(pt_buses)
    flows = n.lines_t.p0.iloc[0]
    cross_pt = n.lines[
        ((n.lines.bus0.isin(es_buses)) & (n.lines.bus1.isin(pt_buses_set))) |
        ((n.lines.bus0.isin(pt_buses_set)) & (n.lines.bus1.isin(es_buses)))
    ]
    total_es_a_pt = sum(
        flows[line.name] if line.bus0.startswith("ES") else -flows[line.name]
        for _, line in cross_pt.iterrows()
    )
    print(f"Flujo neto ES->PT: {total_es_a_pt:+.1f} MW")
    if total_es_a_pt <= 0:
        fallos.append(f"Flujo neto ES->PT no es positivo: {total_es_a_pt:.1f} MW")

    # --- 3. El Slack es el generador designado, no uno arbitrario ---
    slack = n.generators[n.generators.control == "Slack"]
    if len(slack) != 1:
        fallos.append(f"se esperaba exactamente 1 generador Slack, hay {len(slack)}")
    elif slack.index[0] != "G0031":
        fallos.append(f"el Slack es {slack.index[0]}, se esperaba G0031 (Reservoir, 1452 MW)")
    else:
        print(f"Slack: {slack.index[0]} ({slack.carrier.iloc[0]}, "
              f"{slack.p_nom.iloc[0]:.0f} MW) - OK")

    # --- 4. El flujo neto ES->FR es positivo en la red final (España exporta a
    # Francia via el escenario de create_scenario_v2.py, no via el ajuste de mezcla
    # de este script - ver nota en add_neighbors_v2.py) ---
    fr_buses = n.buses[n.buses.index.str.startswith("FR")].index
    fr_buses_set = set(fr_buses)
    cross_fr = n.lines[
        ((n.lines.bus0.isin(es_buses)) & (n.lines.bus1.isin(fr_buses_set))) |
        ((n.lines.bus0.isin(fr_buses_set)) & (n.lines.bus1.isin(es_buses)))
    ]
    total_es_a_fr = sum(
        flows[line.name] if line.bus0.startswith("ES") else -flows[line.name]
        for _, line in cross_fr.iterrows()
    )
    print(f"Flujo neto ES->FR: {total_es_a_fr:+.1f} MW")
    if total_es_a_fr <= 0:
        fallos.append(f"Flujo neto ES->FR no es positivo: {total_es_a_fr:.1f} MW")

    if fallos:
        print("\nVerificacion FALLO:")
        for f in fallos:
            print(f"  - {f}")
        return 1
    print("\nVerificacion OK: Portugal importa de España de forma realista, "
          "con un Slack fisicamente sensato, y España exporta a Francia en la "
          "red final.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
