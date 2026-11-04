"""Deslastre optimo por baja frecuencia con BTM para Espana.

Puerto de JUANCHO/deslastre_btm.py (STN colombiano) al sistema espanol,
usando el esquema real de deslastre de REE (P.O. 1.6, ver
dinamica_frecuencia.EDAC_UMBRALES_HZ_ESPANA) en vez del Acuerdo 2105
colombiano.

Diferencia deliberada frente a Colombia: SIN la capa de diagnostico de
ACE por area (bias_por_area/ace_por_area/diagnostico_ace). Espana no
tiene una estructura de areas operativas con intercambios propios - es
una unica zona sincrona en dinamica_frecuencia.Sistema. El MILP opera
directamente a nivel de BUS INDIVIDUAL, usando el BTM real por bus que ya
calcula btm_regional.capacidad_btm_por_bus() (D3) - de hecho una entrada
mas directa que la colombiana, que reparte un total por area proporcional
a la demanda porque PARATEC no da barra.

Ver 06_documentacion/2026-09-27-diseno-sub-proyecto-E-deslastre-btm.md
para el diseno completo y las fuentes regulatorias citadas."""
import numpy as np
import pandas as pd

from iberia import dinamica_frecuencia as din
from iberia.btm_regional import produccion_btm_por_bus, region_de_bus

# Split solar/cogeneracion del BTM nacional espanol, REE dic-2025 (mismas
# cifras citadas en el diseno del sub-proyecto D, seccion D3): 8.856 MW
# solar + 1.571 MW cogeneracion = 10.427 MW. NOTA: esta suma no coincide
# exactamente con el total de dic-2025 publicado por REE (10.915 MW) - un
# residuo de ~488 MW (4,5%) que ya estaba en la cita original y no se
# resuelve aqui. OJO: BTM_MW_TOTAL_ESPANA ya NO vale 10.915 sino 8.500,
# la placa de ABRIL (dato NERC); este split se usa solo para derivar la
# FRACCION inversor/sincrono, que es un cociente y no cambia al reescalar; no afecta de forma relevante
# la fraccion inversor/sincrono que se calcula a partir de el.
#
# Por que importa la fraccion: la cogeneracion es tipicamente una maquina
# SINCRONA (turbina de gas o vapor pequena), no electronica de potencia -
# no se desconecta en bloque ante un hueco de tension como la solar. Mismo
# criterio que aplico Colombia a su 55% de hidraulica pequeña dentro del
# pool BTM registrado (ver memoria stn-btm-pool-es-55pct-hidro).
FRACCION_INVERSOR_BTM_ESPANA = 8856.0 / (8856.0 + 1571.0)   # ~0,8493

# Error de estimacion del BTM: mismas cifras que Colombia, mismos papers.
# No hay razon fisica para que el error de un estimador cambie por pais -
# el error del BTM lo domina el error de irradiancia y el del registro de
# capacidad instalada, ninguno de los dos es especifico de Colombia.
ERROR_DESAGREGACION = 0.155   # Qu, Ge, Lu, Wang, Applied Energy 381 (2025)
ERROR_CAPACIDAD = 0.19        # Kabir et al., IEEE Trans. Sust. Energy 2021
FRACCION_ERROR_COMUN = 0.90   # ver JUANCHO/deslastre_btm.py para el
                               # argumento fisico completo (correlacion
                               # espacial de la irradiancia)


def estimar_btm_perdido(caido_real, error_estimacion_pct=None, semilla=0):
    """El BTM que se ha caido, TAL COMO LO ESTIMA el operador (con error).

    Portado sin cambios de JUANCHO/deslastre_btm.py::estimar_btm_perdido()
    - es matematica pura, no depende de ningun dato colombiano."""
    if error_estimacion_pct is None:
        error_estimacion_pct = 100.0 * (
            ERROR_DESAGREGACION**2 + ERROR_CAPACIDAD**2)**0.5
    rng = np.random.default_rng(semilla + 1)
    err = rng.normal(0.0, error_estimacion_pct / 100.0, len(caido_real))
    return (caido_real * (1.0 + err)).clip(lower=0.0)


def estimar_btm(btm_real, region_por_bus, error_estimacion_pct=None,
                capacidad=None, semilla=0):
    """El BTM instalado por bus TAL COMO LO VE EL OPERADOR (con error).

    Adaptado de JUANCHO/deslastre_btm.py::estimar_btm(). Misma logica del
    error (insesgado, correlacionado espacialmente, acotado por la fisica)
    - ver ese modulo para las tres propiedades completas y sus fuentes.

    `region_por_bus` (dict bus->nombre de region, de btm_regional.
    region_de_bus) reemplaza el `mapa_areas` colombiano: aqui NO hay ACE
    ni intercambios entre regiones (decision del sub-proyecto E) - las
    regiones de btm_regional.py se usan UNICAMENTE como la particion
    espacial que agrupa el componente comun del error de estimacion, no
    como areas operativas con AGC propio.
    """
    if error_estimacion_pct is None:
        error_estimacion_pct = 100.0 * (
            ERROR_DESAGREGACION**2 + ERROR_CAPACIDAD**2)**0.5
    rng = np.random.default_rng(semilla + 7)
    sigma = error_estimacion_pct / 100.0

    fc = FRACCION_ERROR_COMUN
    s_comun = sigma * np.sqrt(fc)
    s_idio = sigma * np.sqrt(1.0 - fc)

    unicas = sorted(set(region_por_bus.values())) or ['unica']
    comun = {r: rng.normal(0.0, s_comun) for r in unicas}

    err = np.array([comun.get(region_por_bus.get(b, 'unica'), 0.0)
                    for b in btm_real.index])
    err = err + rng.normal(0.0, s_idio, len(btm_real))

    est = btm_real * (1.0 + err)
    tope = capacidad if capacidad is not None else btm_real / 0.8
    return est.clip(lower=0.0).clip(
        upper=tope.reindex(est.index).fillna(np.inf)
        if hasattr(tope, 'reindex') else tope)


def aplicar_caida_btm(btm, caida_pct, fraccion_inversor=FRACCION_INVERSOR_BTM_ESPANA,
                      caida_sincrona_pct=0.0, semilla=0):
    """Devuelve (btm_caido, btm_resto) por bus.

    Adaptado de JUANCHO/deslastre_btm.py::aplicar_caida_btm(). Solo la
    parte conectada por inversor responde al modo de fallo que se estudia
    (desconexion en bloque por hueco de tension/excursion de frecuencia);
    `fraccion_inversor` es un escalar UNIFORME (no por bus) porque D3 solo
    tiene el desglose solar/cogeneracion a nivel NACIONAL, no por bus - a
    diferencia de Colombia, que tiene el detalle tecnologico por planta
    via PARATEC. Es un supuesto declarado, misma naturaleza que el reparto
    proporcional a la carga que ya usa btm_regional.py."""
    rng = np.random.default_rng(semilla)
    frac = np.clip(rng.normal(caida_pct / 100.0, 0.15, len(btm)), 0.0, 1.0)
    f_sinc = np.clip(
        rng.normal(caida_sincrona_pct / 100.0, 0.05, len(btm)), 0.0, 1.0)
    frac = frac * fraccion_inversor + f_sinc * (1.0 - fraccion_inversor)
    caido = btm * frac
    return caido, btm - caido


def escenarios_alivio(carga_por_bus, btm_estimado, caida_pct,
                      fraccion_inversor=FRACCION_INVERSOR_BTM_ESPANA,
                      error_estimacion_pct=None, n_escenarios=5, semilla=0):
    """Alivio de abrir cada bus, en varios escenarios, y el piso
    garantizado.

    Adaptado de JUANCHO/deslastre_btm.py::escenarios_alivio() - misma
    logica de DOS fuentes de incertidumbre (la fraccion de caida Y la
    propia estimacion de BTM) y la misma vara `piso` = carga MEDIDA (la
    garantia de Das et al.: el BTM que se caiga solo puede sumar, nunca
    puede dejar el corte corto).

    `carga_por_bus` es la carga MEDIDA (lo que el operador ve). `btm_
    estimado` debe ser el BTM ESTIMADO, no el real - estos escenarios son
    los que el operador se plantea, no la verdad.

    Devuelve (alivio, piso): `alivio` es un DataFrame bus x escenario;
    `piso` es una Serie con la carga medida de cada bus.
    """
    if error_estimacion_pct is None:
        error_estimacion_pct = 100.0 * (
            ERROR_DESAGREGACION**2 + ERROR_CAPACIDAD**2)**0.5
    piso = carga_por_bus.round(3)
    sigma = error_estimacion_pct / 100.0

    filas = {}
    for s in range(n_escenarios):
        semilla_s = semilla + 1000 + 100 * s
        rng = np.random.default_rng(semilla_s + 13)
        btm_s = (btm_estimado * (
            1.0 + rng.normal(0.0, sigma, len(btm_estimado)))).clip(lower=0.0)
        _, resto = aplicar_caida_btm(btm_s, caida_pct, fraccion_inversor,
                                     semilla=semilla_s)
        real = carga_por_bus + btm_s.reindex(carga_por_bus.index).fillna(0.0)
        filas[f's{s}'] = (
            real - resto.reindex(carga_por_bus.index).fillna(0.0)).round(3)
    return pd.DataFrame(filas), piso


def milp_asignacion(alivio, btm_resto, objetivos, lam, alivio_piso=None,
                    limite_s=30, verbose=False):
    """Asigna cada bus a un escalon del esquema de deslastre.

    Adaptado de JUANCHO/deslastre_btm.py::milp_asignacion() - SOLO el
    modelo SECUENCIAL de Arenas et al. (el que Colombia usa por defecto):
    resuelve un subproblema por escalon y va fijando lo ya asignado. El
    modelo completo (secuencial=False en el original) no se porta: con 4
    escalones (frente a los 8 de Colombia) no hace falta, y mantiene el
    puerto enfocado en lo que pide el diseno del sub-proyecto E.

    min  sum_j (up[j] + dn[j]) + lam * sum_b btm_resto[b] * x[b,j]
    s.a. la suficiencia se exige sobre `alivio_piso` si se da (la garantia
         de Das et al.), o sobre la MEDIANA de los escenarios si no
         (`estimado`, sin esa garantia) - el mismo tercer modo,
         `peor_escenario`, se logra pasando `alivio.min(axis=1)` como
         `alivio_piso`.

    `alivio`: DataFrame bus x escenario, el alivio esperado de abrir cada
    bus en cada escenario (de escenarios_alivio()).
    `alivio_piso`: Serie o None - la vara de suficiencia. None = 'estimado'
    (mediana de los escenarios); pasar `piso` (de escenarios_alivio) para
    'piso'; pasar `alivio.min(axis=1)` para 'peor_escenario'.
    `objetivos`: DataFrame escalon x escenario, el objetivo ACUMULADO de
    cada escalon.

    Devuelve un DataFrame bus x escalon con la asignacion binaria.
    """
    import contextlib
    import io
    import logging

    import linopy

    def _resolver(modelo):
        """Resuelve y DEVUELVE el estado. Antes se descartaba el valor de
        retorno de solve(), asi que un fallo del solver producia en
        silencio "no deslastrar nada" y la ejecucion seguia escribiendo
        resultados. Con la restriccion de suficiencia DURA el problema
        puede ser legitimamente infactible, asi que el estado deja de ser
        un detalle: es parte del resultado."""
        lg = logging.getLogger('linopy')
        antes = lg.level
        lg.setLevel(logging.ERROR)
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                estado, _ = modelo.solve(solver_name='highs',
                                         output_flag=False,
                                         time_limit=limite_s)
            return estado
        except Exception as e:
            return f'excepcion: {type(e).__name__}'
        finally:
            lg.setLevel(antes)

    buses = list(alivio.index)
    escen = list(alivio.columns)
    resto = btm_resto.reindex(buses).fillna(0.0)
    obj = objetivos.reindex(columns=escen)
    pasos = list(range(len(obj)))
    piso = (alivio_piso.reindex(buses).fillna(0.0)
            if alivio_piso is not None else None)
    vara = piso if piso is not None else alivio.median(axis=1)

    asign = pd.DataFrame(0, index=buses, columns=pasos)
    disponibles = list(buses)
    acumulado = 0.0
    if verbose:
        print(f"\n--- Plan del esquema (MILP): reparto de barras entre "
              f"los {len(pasos)} escalones del P.O. 1.6 ---")
    for j in pasos:
        incr = {sc: float(obj.at[j, sc]) - acumulado for sc in escen}
        if max(incr.values()) <= 0 or not disponibles:
            continue
        m = linopy.Model()
        y = m.add_variables(binary=True, coords=[disponibles], name='y')
        dn = m.add_variables(lower=0.0, coords=[escen], name='dn')
        e_min = (y * vara.reindex(disponibles).fillna(0.0).values).sum()

        # SUFICIENCIA: UNA restriccion, DURA. Es la garantia de Das.
        #
        # Antes habia una restriccion BLANDA por escenario:
        #     e_min >= incr[sc] - up[sc],  con up libre y peso 1
        # y eso rompia el metodo por dos sitios a la vez.
        #
        # (a) `up` libre convierte la suficiencia en NEGOCIABLE: al solver
        #     le sale a cuenta incumplir el piso siempre que lam*r > n_esc*p.
        #     Medido en la corrida real, el termino de BTM dominaba el 57-70%
        #     del objetivo y el piso quedaba incumplido un 13,6% EN CADA
        #     ESCALON, por diseno. Das existe precisamente para que el error
        #     de estimacion del BTM no pueda causar deslastre insuficiente;
        #     con la restriccion blanda esa garantia no existia.
        #
        # (b) `e_min` es la MISMA expresion para los 5 escenarios (usa
        #     `vara`, que es el piso medido, no alivio[sc]), asi que las 5
        #     restricciones solo se diferenciaban en el RHS y la que manda
        #     es la de incr mayor. Pero `up` se sumaba 5 VECES en el
        #     objetivo y la penalizacion de BTM una sola: el peso efectivo
        #     de lambda era lam/n_escenarios. La lambda "calibrada" de 25
        #     era en realidad 5,0 - el mismo valor colombiano, disfrazado
        #     por el conteo quintuple.
        #
        # Una sola restriccion dura sobre el requisito que liga arregla las
        # dos cosas: el piso deja de ser comprable y lambda vuelve a ser
        # conmensurable con el.
        requisito = max(incr.values())
        m.add_constraints(e_min >= requisito, name='suficiencia')

        # Cota superior: sigue BLANDA, y debe seguirlo. Abrir barras
        # enteras hace imposible clavar el objetivo exacto, asi que
        # pasarse es inevitable; lo que procede es penalizarlo, no
        # prohibirlo.
        for sc in escen:
            a = alivio[sc].reindex(disponibles).fillna(0.0).values
            m.add_constraints((y * a).sum() <= incr[sc] + dn.sel(dim_0=sc),
                              name=f'mx_{sc}')

        pen = (y * resto.reindex(disponibles).fillna(0.0).values).sum()
        m.add_objective(dn.sum() + lam * pen)
        estado = _resolver(m)

        if estado != 'ok' or y.solution is None:
            # Con la restriccion dura el problema PUEDE ser infactible: si
            # ni abriendo todas las barras disponibles se alcanza el
            # requisito, no hay solucion. Eso es informacion, no un error
            # que haya que tapar: significa que el esquema no da para lo
            # que la frecuencia pide.
            capacidad = float(vara.reindex(disponibles).fillna(0.0).sum())
            print(f"     escalon {j+1}: SIN SOLUCION ({estado}). Se piden "
                  f"{requisito:.0f} MW y las {len(disponibles)} barras "
                  f"disponibles solo suman {capacidad:.0f} MW. Se abren "
                  f"TODAS: el esquema no alcanza el objetivo de este "
                  f"escalon.")
            elegidas = list(disponibles)
            for b in elegidas:
                asign.loc[b, j] = 1
            acumulado += capacidad
            disponibles = []
            continue

        sel = y.solution.to_pandas().round(0).astype(int)
        elegidas = [b for b in disponibles if sel.get(b, 0) == 1]
        for b in elegidas:
            asign.loc[b, j] = 1
        logrado = float(vara.reindex(elegidas).fillna(0.0).sum())
        acumulado += logrado
        disponibles = [b for b in disponibles if b not in set(elegidas)]
        if verbose:
            print(f"     escalon {j+1}: {len(elegidas)} barras, objetivo "
                  f"{np.mean(list(incr.values())):.0f} MW, conseguido "
                  f"{logrado:.0f} MW")
    asign.index.name = 'bus'
    return asign


def deslastre_desde_asignacion(asignacion, alivio_real, escalones_disparados):
    """MW a botar en cada bus, segun los escalones que hayan disparado.

    Portado verbatim de JUANCHO/deslastre_btm.py - es generico, no
    depende de ningun dato colombiano. `escalones_disparados` es
    traza['escalones'] de dinamica_frecuencia.simular_frecuencia()."""
    activos = [j for j, e in enumerate(escalones_disparados) if e['disparado']]
    if not activos:
        return pd.Series(dtype=float)
    sel = asignacion[activos].sum(axis=1) > 0
    buses = asignacion.index[sel]
    return alivio_real.reindex(buses).dropna().clip(lower=0.0).round(3)


# Lambda elegido tras el barrido de calibrar_lambda_espana.py contra la
# penetracion BTM de iberia_blackout.nc.
#
# CIFRAS VIGENTES (1-nov-2026), con la placa de abril: 8.500 / 27.000 MW
# = 31,5% de PLACA, y 5.029 / 27.000 = 18,6% de BTM PRODUCIENDO, que es
# lo unico que puede caerse. El 40,4% que este bloque daba como
# "penetracion real" usaba la placa de dic-2025 (10.915 MW).
#
# Lo que sigue explica por que aquel 40,4% difería del ~34% del diseno.
# Se conserva porque la leccion -confundir la base ES con la base ES+PT-
# sigue siendo valida, aunque las dos cifras concretas esten superadas.
#
# Por que 40,4% y no el ~34% estimado en el diseno (seccion E3): NO es
# porque la carga de este snapshot sea menor que lo esperado - iberia_blackout.nc
# es un snapshot ESTATICO pre-evento (la cascada de escenario_real() solo se
# aplica de forma dinamica via `eventos` dentro de simular_frecuencia; nunca
# queda horneada en n.loads.p_set) y la demanda ES de este escenario fue
# escalada HACIA ARRIBA, a ~27.000 MW (desde una base de 25.326,2 MW, +6,6%,
# ver 06_documentacion/2026-09-27-diseno-sub-proyecto-D-btm.md linea ~55),
# no hacia abajo. La brecha 34%->40,4% es un error de etiquetado en la
# estimacion original del diseno: dividio 10.915 MW entre Sistema.P_carga
# (~31.800 MW, confirmado en dinamica_frecuencia.Sistema.__init__ linea 84 -
# la suma de cargas en `iberia_buses`, que en la linea 71 incluye buses ES
# Y PT), es decir demanda ES+PT COMBINADA, cuando el objetivo solo-Espana
# de este mismo escenario es ~27.000 MW (ver diseno D, tabla de la seccion
# de dispatch). No hay ninguna diferencia real en la demanda del sistema;
# no cambia la conclusion de esta seccion.
#
# NO es el 5,0 de Colombia sin comprobar: ese valor se calibro contra el
# 14-60% colombiano, y la penetracion espanola cae en la misma zona donde
# Colombia encontro que lambda=25 ya deja de deslastrar en regimen normal
# (ver el diseno, seccion E3) - pero ese barrido colombiano calibraba
# contra el regimen normal, no contra el evento; este barrido, igual que
# el criterio de eleccion pedido ("el que sobrevive con margen"), se hizo
# contra el evento real (CAIDA_PCT=80%) y los tres candidatos
# sobrevivieron con margen. Barrido del 2026-09-27, 3 semillas (0, 1, 2),
# sobre la placa de dic-2025 (penetracion 40,4%); re-medido el
# 1-nov-2026 sobre la de abril, ver la tabla de mas abajo:
#
#   lambda   % objetivo conseguido (medio)   BTM sano perdido (medio, MW)
#    0.5              96.1                           1683.6
#    5.0              96.1                           1500.8
#   25.0              95.3                           1410.8
#
# Elegido: 25.0, porque los tres candidatos superan el umbral del 90% en
# las 3 semillas (94.5-96.8% por semilla individual, ver
# resultados/calibracion_lambda_espana.csv) - a diferencia del regimen
# normal colombiano, aqui lambda=25 NO apaga el esquema contra el evento
# real espanol - y de los tres, 25.0 es el que menos BTM sano sacrifica
# (1410.8 MW de media, frente a 1683.6 con lambda=0.5), sin bajar del
# margen de seguridad. Seguir vigilando con verificar_guarda_lambda() en
# cada corrida real, no solo en la calibracion.

# RIESGO CERRADO (1-nov-2026). Este bloque declaraba un riesgo abierto:
# el barrido de calibracion solo valida lambda contra el EVENTO
# (CAIDA_PCT=80%), y faltaba el eje de REGIMEN NORMAL -demanda ordinaria,
# SIN evento, con el BTM simplemente conectado y sano-, que es el que en
# Colombia revelo el "precipicio" (ver stn-btm-lambda-precipicio): un
# lambda alto que parecia seguro contra el evento apagaba el esquema por
# completo en operacion normal a partir de cierta penetracion.
#
# Ya se ha corrido: barrido_lambda_normal.py, 24 puntos (lambda 0,5 / 5 /
# 25 / 100 x penetracion 0 / 10 / 18,6 / 30 / 40 / 60 %, 2 semillas).
#
#   NO HAY PRECIPICIO EN NINGUN PUNTO: los 24 dan el 100,0% del objetivo.
#
# Se probo hasta lambda=100 (CUATRO veces el adoptado) y hasta el 60% de
# penetracion (el TRIPLE de la real, y por encima del 40% donde aparecio
# el precipicio colombiano). Es lo que predecia la restriccion de
# suficiencia DURA: lambda solo elige ENTRE PLANES SUFICIENTES, asi que
# no puede dejar el esquema corto. El precipicio colombiano era un
# sintoma de la restriccion BLANDA, no una propiedad de lambda.
#
# OBSERVACION SECUNDARIA, que conviene no exagerar: el BTM sano tocado no
# es monotono en lambda. A toda penetracion, lambda=5 toca marginalmente
# MENOS que 25 y 100 (a 18,6%: 1.796,8 frente a 1.804,6 y 1.804,1 MW).
# La diferencia es del 0,4% y lambda>=25 da practicamente lo mismo: el
# efecto SATURA hacia lambda~5. Lo mas probable es que sean optimos
# casi-equivalentes separados por la tolerancia del solver, no una
# propiedad real. No es razon para cambiar el valor adoptado -en el eje
# del EVENTO, que es el que importa para el diseno, 25 si protege mas
# (604,5 frente a 640,1 MW)- pero si para no presentar el 25 como
# finamente optimizado: cualquier valor entre 5 y 100 se comporta igual.
#
# verificar_guarda_lambda() sigue en pie como red de seguridad en tiempo
# de ejecucion; ahora respaldada por el barrido, no en su lugar.
# Peso del BTM sano en el objetivo del MILP.
#
# QUE SIGNIFICA AHORA, QUE NO ES LO QUE SIGNIFICABA. Con la restriccion
# de suficiencia DURA, lambda solo elige ENTRE PLANES SUFICIENTES: no
# puede deslastrar de menos para proteger BTM. Antes si podia, y a
# lambda=25 el esquema planificaba el 3,58% de la demanda en vez del 50%
# en regimen normal - quedaba efectivamente apagado. Ese "precipicio"
# era un sintoma de la restriccion blanda, no una propiedad de lambda.
#
# Medido con la suficiencia dura (3 semillas, penetracion real 18,6%
# de BTM PRODUCIENDO sobre la demanda espanola):
#   lambda   % del objetivo   BTM sano perdido
#     0,5        100,4%            712,6 MW
#     5,0        100,4%            640,1 MW
#    25,0        100,4%            604,5 MW   <- adoptado
#
# Los tres cumplen el objetivo; 25 es el que mas BTM sano protege, y ese
# orden se ha mantenido en las tres mediciones sucesivas.
#
# HISTORIA DE ESTA TABLA, porque se ha re-medido dos veces en un dia y
# conviene no confundir las versiones:
#   970,2 / 879,7 / 831,3  con la placa de BTM de dic-2025 (10.915 MW)
#   482,9 / 451,3 / 441,3  con la placa de abril, pero con el desglose
#                          por comunidad sin reescalar (las 3 conocidas
#                          pesaban el 64,5% del total en vez del 50,2%)
#   712,6 / 640,1 / 604,5  VIGENTE: placa de abril y desglose reescalado
#                          proporcionalmente (1-nov-2026)
#
# El reescalado SUBE el BTM sano perdido porque reparte el BTM de forma
# mas homogenea: con el BTM concentrado en 3 comunidades, el MILP tenia
# mas heterogeneidad espacial que explotar para esquivarlo.
#
# Los tres cumplen el objetivo; 25 es el que mas BTM sano protege. Se
# mantiene el valor, pero por una razon distinta a la de antes.
#
# OJO al comparar con Colombia: alli lambda=5. La diferencia aparente se
# debia en parte a que este MILP contaba el deficit 5 veces (una por
# escenario) y la penalizacion una, asi que el peso efectivo era
# lambda/5. Corregido eso, los dos valores son ya conmensurables.
LAMBDA_BTM_ESPANA = 25.0


def verificar_guarda_lambda(asignacion, vara, objetivos, lam, umbral_pct=0.75):
    """Guarda contra un lambda demasiado alto que apaga el esquema sin
    avisar. Portada de JUANCHO/deslastre_btm.py:1114-1129 - la penalizacion
    por BTM sano puede hacer que al MILP le salga mas barato no deslastrar
    que tocar una barra con BTM sano, sin lanzar ningun error."""
    elegidas = asignacion.index[asignacion.sum(axis=1) > 0]
    plan = float(vara.reindex(elegidas).fillna(0.0).sum())
    meta = float(objetivos.iloc[-1].mean())
    if meta > 0 and plan < umbral_pct * meta:
        print(f"  AVISO: el plan del MILP solo cubre {100*plan/meta:.0f}% "
              f"del objetivo del ultimo escalon ({plan:.0f} de "
              f"{meta:.0f} MW). Con lambda={lam:g} la penalizacion por "
              f"BTM sano domina y al optimizador le sale mas barato no "
              f"cortar. Baja LAMBDA_BTM_ESPANA.")
        return False
    return True


def _proporcional(alivio, mw):
    """Reparto proporcional ciego: corta una fraccion de CADA bus
    proporcional a su alivio, sin saber donde queda BTM sano. Portado
    verbatim de JUANCHO/deslastre_btm.py::_proporcional() - es la
    referencia de comparacion contra el MILP BTM-aware en E4 (mismo
    --comparar que usa Colombia)."""
    pos = alivio[alivio > 0]
    if not len(pos) or mw <= 0:
        return pd.Series(dtype=float)
    return (pos / pos.sum() * min(mw, pos.sum())).round(3)


def ejecutar_espana(caida_pct=80.0, lam=None, verbose=True, red='apagon'):
    """Corre la cascada calibrada de D4 con el esquema de deslastre real
    espanol activo, decidiendo la asignacion bus->escalon POR ADELANTADO
    (como en la realidad: los reles se ajustan antes del evento, no se
    reprograman durante el)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import pypsa

    from iberia import config
    from iberia import dinamica_frecuencia as din
    from iberia.analisis_btm_cascada import escenario_real

    if lam is None:
        lam = LAMBDA_BTM_ESPANA
        assert lam is not None, (
            "LAMBDA_BTM_ESPANA no esta fijado - corre python -m iberia.calibrar_lambda_espana "
            "y rellena el valor en deslastre_btm_espana.py (Tarea E3)")

    n = pypsa.Network(config.red_de(red))
    sis = din.Sistema(n)
    # PRODUCCION, no placa: tanto el BTM que se cae como el BTM sano
    # que el MILP protege son generacion real, no capacidad instalada.
    btm = produccion_btm_por_bus(n)
    es_buses = n.buses[n.buses.index.str.startswith('ES')].index
    carga = n.loads.groupby('bus').p_set.sum()
    carga = carga.reindex(es_buses).fillna(0.0)
    carga = carga[carga > 0]
    region = {b: region_de_bus(n.buses.at[b, 'x'], n.buses.at[b, 'y'])
             for b in btm.index}

    if verbose:
        print(f"Penetracion BTM: {btm.sum():.1f} MW de "
              f"{carga.sum():.1f} MW de demanda "
              f"({100*btm.sum()/carga.sum():.1f}%)")

    # --- Plan del MILP, decidido ANTES del evento --------------------------
    btm_est = estimar_btm(btm, region, semilla=0)
    caido_real, resto_real = aplicar_caida_btm(btm, caida_pct, semilla=0)
    _, resto_est = aplicar_caida_btm(btm_est, caida_pct, semilla=0)
    alv, piso = escenarios_alivio(carga, btm_est, caida_pct, semilla=0)
    fraccion_acumulada = [0.15, 0.30, 0.40, 0.50]
    # OBJETIVO DE CADA ESCALON: sobre la demanda MEDIDA, no sobre el
    # alivio estimado.
    #
    # Antes era `alv[sc].sum() * f`, donde alv = carga + BTM caido
    # ESTIMADO. Dos consecuencias, las dos malas:
    #
    # (a) El tamano del plan escalaba con el ERROR DEL ESTIMADOR. Forzando
    #     el sesgo del estimador, el deslastre planificado se movia 11
    #     puntos de demanda (52,1% -> 63,1%). Eso es exactamente lo que el
    #     desacople de Das existe para impedir: el objetivo del esquema no
    #     puede depender de una cantidad que no se mide.
    # (b) La base estaba inflada: el P.O. 1.6 manda deslastrar el 15/30/
    #     40/50% de la DEMANDA, y usar carga+BTM daba un 59,35% efectivo
    #     en vez del 50%.
    #
    # Ahora el objetivo sale de la demanda medida -lo que el operador SI
    # conoce- y es el mismo para todos los escenarios, porque el esquema
    # se arma antes de saber que escenario ocurrira. La incertidumbre del
    # BTM sigue entrando donde le corresponde: en el ALIVIO que cada barra
    # entrega (columnas de `alv`), no en cuanto hay que deslastrar.
    demanda_medida = float(carga.sum())
    objetivos = pd.DataFrame({
        sc: [demanda_medida * f for f in fraccion_acumulada]
        for sc in alv.columns})
    asign_milp = milp_asignacion(alv, resto_est, objetivos, lam=lam,
                                 alivio_piso=piso, verbose=verbose)
    verificar_guarda_lambda(asign_milp, piso, objetivos, lam)

    # alivio real: lo que de verdad se consigue al abrir cada bus (con el
    # BTM VERDADERO, no el estimado - es lo que pasa al abrir el interruptor)
    alivio_real = carga + btm.reindex(carga.index).fillna(0.0) - \
        resto_real.reindex(carga.index).fillna(0.0)

    # --- Perturbacion: la cascada calibrada de D4, mas la caida de BTM -----
    eventos = escenario_real(n, sis)
    if float(caido_real.sum()) > 1e-9:
        eventos.append({'t': 0.5, 'dP_carga': float(caido_real.sum()),
                        'etiqueta': f'BTM invisible caido ({caida_pct:.0f}%)'})

    # --- Dinamica de frecuencia: UNA sola vez con el esquema activo, y una
    # vez sin el. El modelo de una sola masa no distingue QUE bus se
    # corta, solo CUANTO MW en total - por eso el reparto entre MILP y
    # proporcional se decide DESPUES, sobre la MISMA traza de escalones
    # disparados, no volviendo a simular la frecuencia por cada metodo. ----
    t, f, traza = din.simular_frecuencia(sis, list(eventos), con_deslastre=True)
    t_sin, f_sin, traza_sin = din.simular_frecuencia(sis, list(eventos))

    if verbose:
        disp = [e for e in traza['escalones'] if e['disparado']]
        print(f"\n--- Con deslastre activo (P.O. 1.6) ---")
        print(f"  {din.describir(traza)}  "
              f"colapso={traza['colapso']}")
        print(f"  escalones disparados: {len(disp)} de {len(traza['escalones'])}, "
              f"{traza['deslastre_total']:.1f} MW pedidos por la frecuencia")
        print(f"\n--- Sin deslastre (referencia D4) ---")
        print(f"  {din.describir(traza_sin)}  "
              f"colapso={traza_sin['colapso']}")

    # --- Reparto MILP BTM-aware, sobre los escalones que de verdad
    # dispararon en la traza de arriba ---------------------------------------
    deslastre_milp = deslastre_desde_asignacion(
        asign_milp, alivio_real, traza['escalones'])
    sano_milp = float(resto_real.reindex(deslastre_milp.index).fillna(0.0).sum())

    # --- Referencia: reparto proporcional ciego, mismos MW pedidos por la
    # frecuencia (mismo --comparar que usa Colombia) - corta una fraccion de
    # cada bus proporcional a su alivio, sin saber donde queda BTM sano. ---
    # A MW IGUALES, que es la unica comparacion que significa algo.
    #
    # Al proporcional se le dan los MW que el MILP DESLASTRA DE VERDAD, no
    # los que la frecuencia pide. El MILP abre barras ENTERAS, asi que se
    # pasa del objetivo (aqui 19.773,5 frente a 17.210,5 pedidos, un
    # +14,9%); si al proporcional se le dieran solo los 17.210,5, estaria
    # cortando menos carga y destruyendo menos BTM sano por esa razon y no
    # por ser mejor. La pregunta que responde esta comparacion es: con la
    # MISMA carga desconectada, quien protege mas BTM sano.
    #
    # El exceso del MILP se reporta aparte, porque es un resultado por si
    # mismo: la granularidad de barra tiene un coste.
    mw_entregado_milp = float(deslastre_milp.sum())
    deslastre_prop = _proporcional(alivio_real, mw_entregado_milp)
    # El BTM sano que destruye el reparto proporcional hay que PONDERARLO
    # por la fraccion que corta en cada bus.
    #
    # Antes se sumaba `resto_real` ENTERO sobre el indice de
    # deslastre_prop. Como _proporcional devuelve una entrada por cada bus
    # con alivio > 0 -o sea, todos-, esa suma degeneraba en
    # resto_real.sum(): "todo el BTM sano que existe". Y se comparaba
    # contra el BTM sano de los buses que el MILP abre ENTEROS. Binario
    # contra continuo: el proporcional salia penalizado por un factor
    # 1/fraccion, que con los MW de este escenario es ~1,75.
    #
    # Control independiente: elegir buses ENTEROS al azar hasta los mismos
    # MW destruye ~1.992 MW de BTM sano (200 sorteos), que coincide con la
    # cifra ponderada y no con la anterior. Mismo error que ya se habia
    # detectado y corregido en el modelo colombiano.
    frac_cortada = (deslastre_prop / alivio_real.reindex(deslastre_prop.index)
                    ).clip(upper=1.0).fillna(0.0)
    sano_prop = float((resto_real.reindex(deslastre_prop.index).fillna(0.0)
                       * frac_cortada).sum())

    if verbose:
        pedido = traza['deslastre_total']
        exceso = 100.0 * (mw_entregado_milp - pedido) / max(pedido, 1e-9)
        print(f"\n--- Comparacion del reparto, a MW IGUALES "
              f"({mw_entregado_milp:.1f} MW desconectados por ambos) ---")
        print(f"  MILP BTM-aware      : BTM sano perdido = {sano_milp:.1f} MW")
        print(f"  proporcional ciego  : BTM sano perdido = {sano_prop:.1f} MW "
              f"(ponderado por la fraccion cortada en cada barra)")
        if sano_prop > 0:
            print(f"  ventaja del MILP    : {100*(sano_prop-sano_milp)/sano_prop:.1f}% "
                  f"menos BTM sano destruido")
        print(f"  [la frecuencia pedia {pedido:.1f} MW; el MILP entrega "
              f"{exceso:+.1f}% por abrir barras enteras]")

    # --- Grafico: una sola trayectoria "con deslastre" (fisicamente igual
    # para los dos metodos de reparto - lo que cambia es el BTM sano
    # perdido, no la frecuencia) frente a "sin deslastre" (D4). ------------
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(t_sin, f_sin, color='crimson', linewidth=1.3,
           label=f'sin deslastre (cascada + {caida_pct:.0f}% BTM)')
    ax.plot(t, f, color='steelblue', linewidth=1.6,
           label='con deslastre (P.O. 1.6)')
    ax.axhline(50.0, color='gray', linestyle=':', label='50 Hz nominal')
    ax.axhline(din.F_COLAPSO, color='black', linestyle='--',
              label=f'{din.F_COLAPSO} Hz (colapso)')
    for u in din.EDAC_UMBRALES_HZ_ESPANA:
        ax.axhline(u, color='#bbb', linestyle=':', linewidth=0.7)
    ax.set_xlabel('Tiempo (s)')
    ax.set_ylabel('Frecuencia (Hz)')
    ax.set_title('Efecto del esquema de deslastre real (P.O. 1.6) sobre '
                'la cascada calibrada')
    ax.legend()
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(config.visualizacion(f'deslastre_btm_frecuencia_{red}.png'), dpi=150)

    # --- CSV de comparacion ---------------------------------------------
    filas = [
        {'metodo': f'sin deslastre (cascada + {caida_pct:.0f}% BTM)',
         'nadir_Hz': traza_sin['nadir'],
         'colapso': traza_sin['colapso'], 'MW_deslastrado': 0.0,
         'BTM_sano_perdido_MW': 0.0},
        {'metodo': 'MILP BTM-aware', 'nadir_Hz': traza['nadir'],
         'colapso': traza['colapso'],
         'MW_deslastrado': float(deslastre_milp.sum()),
         'BTM_sano_perdido_MW': sano_milp},
        {'metodo': 'proporcional ciego', 'nadir_Hz': traza['nadir'],
         'colapso': traza['colapso'],
         'MW_deslastrado': float(deslastre_prop.sum()),
         'BTM_sano_perdido_MW': sano_prop},
    ]
    pd.DataFrame(filas).to_csv(
        config.salida(f'comparacion_deslastre_{red}.csv'), index=False)
    print("\n✓ Grafico en resultados/visualizaciones/deslastre_btm_frecuencia.png")
    print(f"✓ Comparacion en resultados/comparacion_deslastre_{red}.csv")
    return {'sin_deslastre': traza_sin, 'con_deslastre': traza,
           'sano_milp': sano_milp, 'sano_prop': sano_prop}


def main():
    import argparse
    from iberia import config
    ap = argparse.ArgumentParser(description=__doc__)
    config.anadir_arg_red(ap)
    ap.add_argument('--caida', type=float, default=80.0,
                    help="porcentaje de caida del BTM")
    args = ap.parse_args()
    print(f"Punto de operacion: {args.red} "
          f"({config.describir_escenario(args.red)})")
    ejecutar_espana(caida_pct=args.caida, red=args.red)


if __name__ == '__main__':
    main()
