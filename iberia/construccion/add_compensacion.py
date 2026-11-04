"""Compensacion reactiva: reactores shunt sobre iberia_scenario.nc.

Ultimo paso de la cadena del pipeline. La red de iDesignRES trae la
susceptancia shunt real de cada linea (columna `b`), que inyecta 21.228
MVAr nominales de carga capacitiva - pero NO trae ningun componente de
compensacion: cero ShuntImpedance en las 1.225 barras.

Criterio: en cada bus, un reactor que absorbe una fraccion f de la carga
capacitiva neta que le inyectan sus lineas,

    b_reactor(i) = -f * sum_{lineas en i} (b_linea / 2)

La mitad por extremo es el modelo pi estandar de linea. Solo se compensan
los buses con susceptancia neta POSITIVA (capacitiva).

QUE SIGNIFICA f, QUE NO ES LO QUE DECIA ANTES
----------------------------------------------
f = 0,10 es la fraccion de compensacion EN SERVICIO en este punto de
operacion, NO la compensacion instalada en la red espanola.

La distincion importa y es fisica: los reactores reales son MANIOBRABLES.
El operador los conecta con carga baja, cuando la carga capacitiva de las
lineas domina y la tension sube, y los desconecta con carga alta. El
escenario de este modelo -exportacion de 3.000 MW, red cargada- es
precisamente cuando un operador tiene la mayoria de su parque de
reactores fuera de servicio. Asi que un 10% conectado es plausible,
mientras que el 50-70% que cita la literatura para lineas EHV se refiere
al parque INSTALADO.

Versiones anteriores de este fichero justificaban f con ese 50-70%
instalado. Era citar un rango para un concepto distinto del que se estaba
midiendo. LIMITACION que esto deja en pie: el modelo sigue sin poder
representar la maniobra, porque es de un unico punto de operacion.

POR QUE 0,10: medido sobre la red con limites de Q y parametros de linea
corregidos. El criterio es el margen a los dos limites de tension:

    f      carga_max  sobrec  buses fuera   v_min (marg)   v_max (marg)
   0,00     102,4%       2         0       0,9298 (+,0298) 1,0972 (+,0028)
   0,10     102,0%       2         0       0,9197 (+,0197) 1,0793 (+,0207) <--
   0,15     101,9%       2         0       0,9151 (+,0151) 1,0722 (+,0278)
   0,20     101,8%       1         0       0,9114 (+,0114) 1,0659 (+,0341)
   0,30     101,6%       1         0       0,9027 (+,0027) 1,0536 (+,0464)
   0,50     101,3%       1         7       0,8865  FUERA   1,0338
   0,70     101,0%       1        11       0,8710  FUERA   1,0173

0,10 es donde los dos margenes se igualan (0,0197 abajo, 0,0207 arriba):
maximiza la distancia minima a ambos limites, con siete veces mas holgura
que 0,00 o 0,30. A partir de 0,50 los buses se van de rango POR ABAJO.

HISTORIA, porque el camino importa y este valor cambio TRES veces
------------------------------------------------------------------
 0,70 -> 0,30:  al ver una sobrecarga en el caso base (L1357 al 152%).
 0,30 -> 0,70:  esa sobrecarga parecia un artefacto de reactivo imposible.
 0,70 -> 0,10:  los parametros de linea estaban mal (ver abajo).

Los dos primeros cambios se decidieron comparando contra un caso base
que no era valido. El tercero es de otra naturaleza: el DATO DE PARTIDA
estaba mal. build_full_network.py dividia r/x entre `circuits` y
multiplicaba b/s_nom por `circuits` ADEMAS de crear un objeto Line por
fila, cuando cada fila de line_data.csv YA ES UN CIRCUITO. La
susceptancia salia inflada un 65%.

Corregido eso, LA PREMISA DE ESTE SUB-PROYECTO SE CAE: sin ningun reactor
(f=0,00) el caso base con limites da 0 buses fuera de rango, frente a los
1.010 (82%) que justificaron escribir este fichero. Aquel "deficit de
absorcion de reactivo" era en su mayor parte la susceptancia duplicada.

Lo que queda, y es lo unico que hoy justifica este paso: una red real
tiene reactores, y f=0,10 da mas margen de tension que f=0,00. Es una
mejora modesta y medida, no la correccion estructural que se creyo.

Leccion de metodo: las tres veces se eligio f comparando el modelo contra
cifras que el propio proyecto habia medido antes. Eso detecta
regresiones, no errores presentes desde el origen. El doble conteo lo
cazo verificar_parametros_linea.py, anclado en una constante fisica
externa (la impedancia caracteristica de una linea aerea).

NO se asigna cos phi a las cargas: se midio y empeora el resultado (los
buses radiales debiles sin generador local se hunden). Ver el diseno.

AVISO: las cifras de este docstring se midieron con el lazo PV->PQ de
limites_reactivos_espana.py, que NO converge (entra en ciclo limite por
un minihidraulico de 50 kW que regula un nudo de 400 kV). La comparacion
RELATIVA entre valores de f es valida -todos sufren lo mismo-, pero la
columna "violan curva" y los tiempos no lo son. Ver
06_documentacion/2026-10-03-auditoria-fisica-y-teorica.md."""
import pandas as pd

from iberia import config
import pypsa

FRACCION_COMPENSACION = 0.10
PREFIJO = 'reac_'


def susceptancia_por_bus(n):
    """Susceptancia shunt neta que las lineas inyectan en cada bus [S].

    Cada linea reparte su `b` a partes iguales entre sus dos extremos
    (modelo pi). Devuelve una Serie indexada por bus, solo con los
    valores positivos (capacitivos)."""
    b_bus = pd.Series(0.0, index=n.buses.index)
    for lado in ('bus0', 'bus1'):
        b_bus = b_bus.add(n.lines.groupby(lado).b.sum() / 2.0, fill_value=0.0)
    return b_bus[b_bus > 0]


def main():
    n = pypsa.Network(config.red('iberia_scenario.nc'))

    ya = [c for c in n.shunt_impedances.index if str(c).startswith(PREFIJO)]
    if ya:
        n.remove('ShuntImpedance', ya)
        print(f"  (se retiraron {len(ya)} reactores de una corrida anterior)")

    b_bus = susceptancia_por_bus(n)
    print(f"Buses con carga capacitiva neta: {len(b_bus)} de {len(n.buses)}")
    print(f"Susceptancia total: {b_bus.sum():.5f} S")

    for bus, b in b_bus.items():
        n.add('ShuntImpedance', f'{PREFIJO}{bus}', bus=bus,
              b=-FRACCION_COMPENSACION * float(b))

    v_nom = n.buses.v_nom.reindex(b_bus.index)
    mvar = FRACCION_COMPENSACION * b_bus * (v_nom ** 2)
    print(f"Reactores anadidos: {len(b_bus)} "
          f"({mvar.sum():.1f} MVAr nominales al {100*FRACCION_COMPENSACION:.0f}%)")
    por_nivel = pd.DataFrame({'mvar': mvar, 'v_nom': v_nom}).groupby('v_nom').mvar.sum()
    for v, m in por_nivel.sort_values(ascending=False).head(4).items():
        print(f"    {v:.0f} kV: {m:8.1f} MVAr")

    n.export_to_netcdf(config.red('iberia_scenario.nc'))
    print("✓ Guardado en data/redes/iberia_scenario.nc")


if __name__ == '__main__':
    main()
