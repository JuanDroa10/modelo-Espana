"""Construye el punto de operacion de PUNTA INVERNAL NOCTURNA (iberia_punta.nc).

Para que existe
---------------
Es el CONTRASTE del apagon del 28 de abril: la punta de demanda invernal,
de noche. Sin sol no hay BTM fotovoltaico produciendo, asi que el evento que
estudia esta tesis no puede plantearse a esa hora; el riesgo del BTM depende
de la hora. Es ademas el caso de inercia alta. Es el mismo contraste
punta/diurno que usa el modelo del STN colombiano.

El punto de operacion: MEDIDO desde el 19-nov-2026
--------------------------------------------------
15 de enero de 2025, cuarto de hora de 20:45 a 21:00 CET, el de la punta
anual de demanda (REE: 40.070 MW instantaneos a las 20:57).

  - Totales por tecnologia, demanda, intercambios con Francia y Portugal y
    demanda y mezcla de Portugal: MEDIDOS por ENTSO-E y contrastados con el
    tiempo real de ESIOS (diferencias por debajo del 1,5 %).
  - Nuclear, ciclos combinados, carbon y parte del bombeo: CENTRAL A CENTRAL
    con el P48 del I90DIA de REE (ESIOS), con la tabla unidad -> barra de
    02_datos_originales/up_barra_i90.csv.
  - Eolica, hidraulica y demanda: el reparto entre barras sigue siendo
    proporcional y por comunidad autonoma; el I90 no ubica las renovables.

Toda la construccion esta en build_punta_medida.py (paso 2), que este script
llama sin variante. Supuestos declarados: la cogeneracion que el modelo no
representa (870 MW) va a las termicas del I90 en servicio, y la placa
equivalente de los agregados de Portugal se sube a despacho / 0,70.

Hasta el 19-nov-2026 el punto era DERIVADO: la demanda era la punta de REE
pero la mezcla eran las cuotas MEDIAS de enero, Espana exportaba 1.000 MW en
total y Portugal tenia 4.800 MW de demanda. Lo medido es otra cosa: 2.184 MW
de exportacion a Francia, 106 a Portugal y 9.285 MW de demanda portuguesa.
La version anterior se conserva en
04_resultados/puntos_previos_i90_2026-11-19/build_punta_snapshot.py.
"""
from iberia.construccion import build_punta_medida as bp

SALIDA = 'iberia_punta.nc'


def main():
    bp.construir(2, SALIDA, None)


if __name__ == '__main__':
    main()
