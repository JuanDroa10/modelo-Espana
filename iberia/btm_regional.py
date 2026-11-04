"""Capacidad de autoconsumo (BTM) de España, repartida por bus real.

Dato que el modulo USA: 8.500 MW (NERC, lamina 3, "~8.5 GW" de FV de
autoconsumo en el instante del apagon, abril de 2025). Ver la nota de
BTM_MW_TOTAL_ESPANA sobre por que NO son los 10.915 MW de dic-2025.

El desglose por comunidad solo existe para 3 (Andalucia 2.006 MW,
Cataluna 1.947 MW, C. Valenciana 1.530 MW = 5.483 MW), y es de
DICIEMBRE. El resto NO tiene tabla completa publica en texto plano - se reparte
proporcional a la carga que el modelo ya tiene en cada zona, mismo tipo de
supuesto declarado que usa JUANCHO/zonas.py para Colombia (solo el total de
area es dato real, la distribucion interna es un supuesto).

Los limites geograficos de cada comunidad son aproximados (bounding boxes),
no una fuente GIS oficial - suficiente para asignar buses a region de forma
razonable, no para uso legal/catastral.

Limitacion residual conocida (verificada, no corregida - ver el informe de
revision de la Tarea D2, rondas 1-3): quedan ~10,4 MW (0,68% de la bolsa de
C. Valenciana, 0,095% del total nacional) mal atribuidos por el mismo motivo
- 4 buses reales de Murcia justo fuera de la exclusion de Murcia, ~9 buses de
Teruel (Aragon) y 1 de Castilla-La Mancha dentro de la caja amplia de
C. Valenciana desde la version original. No se persigue una cuarta ronda de
rectangulos: el patron de "corregir un borde, romper otro" ya se dio una vez
(ver ronda 2). Si en algun momento hace falta precision real, la solucion
correcta es reemplazar las cajas por poligonos GIS oficiales de las
comunidades autonomas, como tarea aparte - no otro rectangulo a mano."""
import pandas as pd

# MW reales, comunidades con cifra explicita de REE (dic-2025). Se
# conservan tal cual los publica REE; el reescalado a la placa de abril
# se hace abajo, explicito, para que el dato de origen siga visible.
BTM_MW_CONOCIDO_DIC2025 = {
    'Andalucia': 2006.0,
    'Cataluna': 1947.0,
    'C. Valenciana': 1530.0,
}
BTM_MW_TOTAL_DIC2025 = 10915.0
# PLACA DE AUTOCONSUMO EN EL INSTANTE DEL APAGON (abril de 2025).
#
# Fuente: NERC, "Iberian Peninsula Blackout" (FERC Open Meeting,
# 26-jun-2025), lamina 3: "Total rooftop PV for self-consumption: ~8.5 GW".
#
# Versiones anteriores usaban 10.915 MW, que es la placa a DICIEMBRE de
# 2025 publicada por REE. El apagon fue en ABRIL, y el autoconsumo
# espanol crecio durante el ano: aplicar la placa de diciembre a un
# evento de abril sobreestima el BTM un 28%. El desglose por comunidad
# (BTM_MW_CONOCIDO) sigue siendo el de diciembre.
#
# EL DESGLOSE SE REESCALA PROPORCIONALMENTE (decidido el 1-nov-2026).
#
# BTM_MW_CONOCIDO_DIC2025 es de DICIEMBRE y el total es de ABRIL, asi que
# no se pueden mezclar: hay que llevar el desglose a la misma fecha que el
# total. Se aplica la misma escala a las tres comunidades, lo que equivale
# a suponer crecimiento UNIFORME entre abril y diciembre.
#
# Durante un tiempo el codigo hizo otra cosa -conservar los MW ABSOLUTOS
# de diciembre y dejar que 'Otras' absorbiera el recorte entero- mientras
# este comentario afirmaba que reescalaba. Eso metia las 3 comunidades
# conocidas del 50,2% al 64,5% del total nacional, es decir suponia que
# TODO el crecimiento abr->dic ocurrio FUERA de ellas. Nadie lo habia
# declarado ni justificado.
#
#                     ANTES (absolutos)     AHORA (reescalado)
#   Andalucia         2.006,0  23,6%        1.562,2  18,4%
#   Cataluna          1.947,0  22,9%        1.516,2  17,8%
#   C. Valenciana     1.530,0  18,0%        1.191,5  14,0%
#   Otras             3.017,0  35,5%        4.230,1  49,8%
#
# El reparto relativo vuelve a ser el de diciembre, que es el unico que
# esta publicado. El supuesto de crecimiento uniforme es mas debil que el
# anterior y, a diferencia de aquel, esta declarado.
BTM_MW_TOTAL_ESPANA = 8500.0
ESCALA_ABRIL = BTM_MW_TOTAL_ESPANA / BTM_MW_TOTAL_DIC2025
BTM_MW_CONOCIDO = {k: v * ESCALA_ABRIL
                   for k, v in BTM_MW_CONOCIDO_DIC2025.items()}
BTM_MW_RESTO = BTM_MW_TOTAL_ESPANA - sum(BTM_MW_CONOCIDO.values())

# Bounding boxes aproximados (lon_min, lon_max, lat_min, lat_max) de las 3
# regiones con dato explicito. El resto de España cae en 'Otras'.
REGIONES_CONOCIDAS = {
    'Andalucia': (-7.5, -1.6, 36.0, 38.7),
    'Cataluna': (0.15, 3.4, 40.5, 42.9),
    'C. Valenciana': (-1.5, 0.7, 37.8, 40.8),
}


def factor_produccion(network, carrier='PV'):
    """Factor de carga de la FV del modelo: produccion / placa.

    POR QUE HACE FALTA. `capacidad_btm_por_bus` devuelve POTENCIA
    INSTALADA (8.500 MW de placa de autoconsumo). Tirar esa cifra entera
    como si fuera generacion equivale a suponer que TODO el autoconsumo
    de Espana estaba produciendo a placa a las 12:33, que es imposible: a
    esa hora la FV va a ~60% de su capacidad.

    El factor se deriva del PROPIO snapshot -la FV de gran escala del
    modelo, en el mismo instante y bajo el mismo cielo- en vez de tomarlo
    de una fuente externa. Asi no se introduce ningun dato nuevo y el
    factor es coherente por construccion con el resto del escenario.

    LIMITACION DECLARADA: se aplica el factor de la FV a TODO el BTM,
    cuando ~15% es cogeneracion (ver FRACCION_INVERSOR_BTM_ESPANA en
    deslastre_btm_espana.py), que opera a factor de carga mas alto y mas
    constante. Usar un factor propio para esa parte moveria el total
    ~2%, por debajo de la incertidumbre de la propia cifra de 8.500 MW,
    asi que no se introduce un segundo parametro."""
    # SOLO ESPANA. El BTM que este factor escala es espanol
    # (BTM_MW_TOTAL_ESPANA), asi que el factor de carga tiene que salir
    # de la FV espanola, no de la de toda la red.
    #
    # Antes promediaba sobre TODA la FV, incluidas las agregadas de
    # Portugal y Francia. En el punto del apagon la contaminacion era
    # pequena -la FV espanola domina- pero el escenario de punta nocturna
    # la destapo entera: con la FV espanola a CERO, el factor global
    # seguia dando 0,0578 por los 677 MW portugueses y 1.189 MW franceses,
    # y el BTM "produciendo" salia 630,9 MW en vez de cero. Un escenario
    # nocturno con BTM solar produciendo no tiene sentido fisico.
    buses_es = network.buses[network.buses.index.str.startswith('ES')].index
    g = network.generators[(network.generators.carrier == carrier)
                           & (network.generators.bus.isin(buses_es))]
    placa = float(g.p_nom.sum())
    if placa <= 0:
        raise ValueError(f"no hay generadores '{carrier}' espanoles con "
                         f"placa > 0 para derivar el factor de produccion")
    return float(g.p_set.sum()) / placa


def produccion_btm_por_bus(network, carrier='PV'):
    """BTM que de verdad esta PRODUCIENDO en este punto de operacion [MW].

    Es `capacidad_btm_por_bus` multiplicado por el factor de carga. Esta
    es la cifra que debe usar cualquier escenario de perdida de BTM: lo
    que se puede caer es lo que se estaba generando, no lo instalado."""
    return capacidad_btm_por_bus(network) * factor_produccion(network, carrier)


def region_de_bus(x, y):
    for nombre, (lon_min, lon_max, lat_min, lat_max) in REGIONES_CONOCIDAS.items():
        if lon_min <= x <= lon_max and lat_min <= y <= lat_max:
            if nombre == 'C. Valenciana' and _en_exclusion_valenciana(x, y):
                return 'Otras'
            return nombre
    return 'Otras'


def _en_exclusion_valenciana(lon, lat):
    """Dos rectangulos pequenos dentro de la caja amplia de C. Valenciana que
    en realidad son de otra region: el borde con Murcia (mismo rango de
    latitud que pueblos reales de Valencia como Pilar de la Horadada, pero
    a una longitud claramente mas al oeste) y el solape puntual con Cataluna
    (una franja estrecha en el extremo norte). Verificado contra 7 puntos de
    referencia reales antes de aplicarse - ver el informe de la Tarea D2."""
    en_zona_murcia = -1.3 <= lon <= -1.0 and 37.8 <= lat <= 38.1
    en_zona_catalana = 0.15 <= lon <= 0.7 and lat > 40.5
    return en_zona_murcia or en_zona_catalana


def capacidad_btm_por_bus(network):
    """MW de autoconsumo asignados a cada bus de España, indexado por nombre
    de bus. Suma total = BTM_MW_TOTAL_ESPANA (8.500 MW)."""
    es_buses = network.buses[network.buses.index.str.startswith('ES')]
    region = pd.Series(
        {b: region_de_bus(row.x, row.y) for b, row in es_buses.iterrows()})

    carga_por_bus = network.loads.groupby('bus').p_set.sum()
    carga_por_bus = carga_por_bus.reindex(es_buses.index).fillna(0.0)

    resultado = pd.Series(0.0, index=es_buses.index)
    for nombre_region, mw_region in BTM_MW_CONOCIDO.items():
        buses_region = region[region == nombre_region].index
        carga_region = carga_por_bus.loc[buses_region].sum()
        if carga_region > 0:
            resultado.loc[buses_region] = (
                carga_por_bus.loc[buses_region] / carga_region * mw_region)

    buses_resto = region[region == 'Otras'].index
    carga_resto = carga_por_bus.loc[buses_resto].sum()
    if carga_resto > 0:
        resultado.loc[buses_resto] = (
            carga_por_bus.loc[buses_resto] / carga_resto * BTM_MW_RESTO)

    assert abs(resultado.sum() - BTM_MW_TOTAL_ESPANA) < 1.0, (
        f"BTM total asignado ({resultado.sum():.1f} MW) no coincide con "
        f"BTM_MW_TOTAL_ESPANA ({BTM_MW_TOTAL_ESPANA:.1f} MW): alguna region "
        f"conocida probablemente tiene carga_region == 0 y su MW no se "
        f"repartió a ningun bus.")

    return resultado


if __name__ == '__main__':
    from iberia import config
    import pypsa

    n = pypsa.Network(config.red('iberia_blackout.nc'))
    btm = capacidad_btm_por_bus(n)
    print(f"BTM total asignado: {btm.sum():.1f} MW "
          f"(objetivo: {BTM_MW_TOTAL_ESPANA:.1f})")
    print(f"Buses con BTM > 0: {(btm > 0).sum()} de {len(btm)}")
    print("\nTop 10 buses por capacidad BTM:")
    print(btm.sort_values(ascending=False).head(10).to_string())
