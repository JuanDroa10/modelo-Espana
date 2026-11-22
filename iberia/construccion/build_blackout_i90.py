"""Variante I90 del apagon: 28-abr-2025, con la convencional central a central.

Lo llama build_blackout_snapshot.py, que despues aplica la calibracion de la
inercia con ENTSO-E. Ejecutado por separado (`main`), reescribe
data/redes/iberia_blackout.nc sobre el punto vigente; comprobado el
20-nov-2026 que el resultado es el mismo (Ek 119,47 GW.s, mismo despacho, mismas
H): no deshace la calibracion.

Parte del punto VIGENTE (totales medidos de ENTSO-E a las 12:15, balance ya
cerrado) y conserva sus totales por tecnologia. Lo unico que cambia es QUE
centrales estan en servicio y DONDE, segun el P48 del I90DIA de REE:
  - nuclear: 4 de 7 grupos (Almaraz I, Cofrentes y Trillo, parados);
  - ciclos combinados y carbon: cada central a su barra; los grupos de
    100 MW o mas que el I90 no programa quedan parados;
  - bombeo CONSUMIENDO: las siete centrales que el I90 identifica (La
    Muela, Duero, Sil, Aguayo, Sallente, Bolarque, Guillena) a su barra.
Limitacion: el P48 del 28-A solo llega al cuarto de 11:45 a 12:00 (despues
el fichero esta vacio). Se usa para el compromiso y la ubicacion; los
totales siguen siendo los medidos de las 12:15. El cierre del balance se
repite con el mismo criterio, sin tocar las centrales del I90.
"""
import pypsa

from iberia.construccion import build_punta_medida as bp
from iberia import config

ENTSOE_DEMANDA_ES_MW = 24944.0    # A65, 12:15 CEST (el dato de build_blackout_snapshot.py)


def main():
    # Sin variantes en esta copia: aplica el I90 sobre el apagon vigente.
    construir('iberia_blackout.nc', 'iberia_blackout.nc', None)


def construir(origen, salida, variante):
    """Aplica el I90 sobre `origen` (el apagon con los totales de ENTSO-E y
    el balance cerrado) y escribe `salida`. Desde el 19-nov-2026 lo llama
    build_blackout_snapshot.py con origen = salida = iberia_blackout.nc."""
    bp.fijar_variante(variante)
    n = pypsa.Network(str(config.DIR_REDES / origen))
    es_buses, es_gens = bp._es(n)
    tot = lambda cs: float(es_gens[es_gens.carrier.isin(cs)].p_set.sum())   # noqa: E731
    total_nuclear = tot(['Nuclear'])
    total_bombeo = tot(['Pumped_storage'])
    total_termico = tot(bp.TERMICA)
    print("=" * 70)
    print(" APAGON con el I90: 28-abr-2025 (P48 de 11:45; totales de las 12:15)")
    print("=" * 70)
    print(f"  totales del punto vigente: nuclear {total_nuclear:.0f}, bombeo "
          f"{total_bombeo:.0f}, termica {total_termico:.0f} MW")
    fijos, m = bp.asignar_i90(n, es_gens, 'p48_i90_20250428_1145.csv',
                              total_nuclear, total_bombeo)
    bp.resto_termico(n, es_gens, fijos, m, total_termico)
    # Solo España: en el punto vigente los agregados de Francia ya producen
    # un 0,9 % por encima de su placa equivalente (heredado, no de aqui).
    g = n.generators[n.generators.bus.isin(es_buses)]
    rotos = g[g.p_set > g.p_nom + 1e-6]
    assert not len(rotos), rotos[['carrier', 'p_nom', 'p_set']]
    n.export_to_netcdf(str(config.DIR_REDES / salida))
    es_loads = n.loads[n.loads.bus.isin(es_buses)].index
    bp.cerrar(salida, es_buses, es_loads, fijos, 'apagon', ENTSOE_DEMANDA_ES_MW)


if __name__ == '__main__':
    main()
