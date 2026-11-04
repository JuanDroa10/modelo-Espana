"""Limites de potencia reactiva y conmutacion PV->PQ sobre el modelo
espanol.

Puerto de JUANCHO/limites_reactivos.py (STN colombiano). Ver
06_documentacion/2026-10-02-diseno-sub-proyecto-F-limites-reactivos.md
para el diseno completo y la justificacion fisica de cada constante.

Por que hace falta un modulo aparte
------------------------------------
PyPSA Network.pf() NO impone limites de reactivo: un bus PV sostiene su
consigna de tension con los MVAr que hagan falta, aunque sean fisicamente
imposibles. Mientras eso sea cierto, el colapso de tension -el modo de
fallo dominante de un N-1 real, y el mecanismo del apagon iberico del 28
de abril de 2025 que esta tesis estudia- es estructuralmente imposible de
observar en el modelo.

Este modulo no modifica la red que recibe: trabaja sobre una copia."""
import numpy as np
import pandas as pd

# Limite de subexcitacion como fraccion de la potencia aparente nominal.
# Lo fija la estabilidad del angulo y el calentamiento de la cabeza del
# estator; en maquinas reales cae entre 0,2 y 0,4. Mismo valor conservador
# que adopto Colombia (JUANCHO/limites_reactivos.py).
K_SUBEXCITACION = 0.35

# Factor de potencia nominal, para pasar de MW de placa a MVA de placa:
# S = P / cos(phi). Turbogeneradores e hidraulicos grandes se disenan
# entre 0,85 y 0,95; 0,90 es el valor central habitual - mismo valor que
# Colombia. Ninguno de los dos es un dato medido espanol: Espana no tiene
# un registro equivalente a los reportes "Detalle de unidad X" de PARATEC
# que le dieron a Colombia curvas reales por maquina - esta curva
# parametrica es el estado final de este modulo, no un paso intermedio.
FP_NOMINAL = 0.90

MAX_ITER = 60   # antes 12 (valor de Colombia) - con lotes adaptativos,
                # cada ronda puede tener que reintentarse con un lote mas
                # pequeno, asi que hacen falta mas rondas externas. Si el
                # lazo llega a 60 sin converger, investigar antes de subir
                # el numero a ciegas - puede ser una senal real de que el
                # caso no tiene una solucion PV/PQ estable, no solo que
                # falta paciencia.
TOL_MVAR = 0.5          # holgura antes de declarar violacion
TOL_V = 1e-4            # holgura de tension para la vuelta a PV


def capacidad(network, verbose=True):
    """Curva de capacidad de cada generador: (Q_min, Q_max) en MVAr.

    S = max(p_nom, p_set) / FP_NOMINAL. El `max` es la red de seguridad
    frente a un bug de datos encontrado en la revision critica de esta
    sesion: 96 generadores fotovoltaicos reales (no agregados PT/FR)
    tienen p_nom (~1,0-1,1 MW) muy por debajo de su propio p_set (hasta
    4,7 MW) - un defecto de asignacion del sub-proyecto A, no corregido en
    su origen por decision explicita del usuario (ver el diseno). Sin el
    `max`, su curva de capacidad saldria menor que su propio despacho
    activo, dando Q_max negativo bajo la raiz - fisica y numericamente
    absurdo. Con el `max`, la curva se dimensiona sobre el despacho real,
    mismo criterio que usa Colombia cuando falta capacidad declarada
    (alli: max(p/0,8, ...)).

    Los agregados de pais Portugal/Francia reciben la MISMA formula, sin
    caso especial - es tan aproximado aplicarles una curva de maquina
    sincrona individual como ya lo es tratarlos como centrales reales en
    cualquier otro analisis (limitacion ya documentada, no una nueva).

    `verbose` controla el AVISO de los 96 generadores con p_set > p_nom:
    por defecto True para uso standalone/diagnostico, pero `aplicar()` lo
    llama con verbose=False porque es el camino caliente del barrido N-1
    con --con-limites (se llama una vez por cada una de las 3.277
    contingencias, y el AVISO repetido ahoga el contador de progreso `\r`
    sin anadir informacion nueva).
    """
    g = network.generators
    p = g.p_set.astype(float)
    p_nom = g.p_nom.astype(float)

    n_piso = int((p > p_nom + 1e-6).sum())
    if n_piso and verbose:
        print(f"  AVISO: {n_piso} generadores despachan por encima de su "
              f"p_nom declarado - su curva de capacidad se dimensiona "
              f"sobre p_set, no sobre el p_nom roto (ver diseno del "
              f"sub-proyecto F).")

    base_mw = np.maximum(p_nom, p)
    s = base_mw / FP_NOMINAL
    s = np.maximum(s, p / FP_NOMINAL)
    s = s.clip(lower=1e-3)
    q_max = np.sqrt(np.maximum(s * s - p * p, 0.0))
    q_min = -K_SUBEXCITACION * s
    return pd.DataFrame({'P': p, 'S_nom': s, 'Q_min': q_min, 'Q_max': q_max},
                        index=g.index)


def diagnostico(network, cap=None):
    """Quien excede su curva de capacidad en la solucion actual."""
    if cap is None:
        cap = capacidad(network)
    q = network.generators_t.q.iloc[0]
    out = []
    for g in cap.index:
        if g not in q.index:
            continue
        qq = float(q[g])
        exceso = max(qq - cap.at[g, 'Q_max'], cap.at[g, 'Q_min'] - qq, 0.0)
        if exceso > TOL_MVAR:
            out.append({'gen': g, 'Q': qq, 'Q_min': cap.at[g, 'Q_min'],
                        'Q_max': cap.at[g, 'Q_max'], 'exceso_MVAr': exceso,
                        'sentido': 'sobreexcitado' if qq > cap.at[g, 'Q_max']
                                   else 'subexcitado'})
    return pd.DataFrame(out)


def aplicar(network, k=None, max_iter=MAX_ITER, vuelta_a_pv=True, verbose=True,
            fijados_iniciales=None):
    """Resuelve imponiendo los limites de reactivo. Devuelve (red, info).

    La red original NO se modifica: se trabaja sobre una copia.

    El metodo es la conmutacion PV->PQ de Newton-Raphson, con una
    adaptacion frente a JUANCHO/limites_reactivos.py (ver el hallazgo
    arriba): en vez de fijar TODOS los violadores de una ronda a la vez,
    se fija un LOTE de tamano adaptativo (los `tam` peores primero,
    reduciendo `tam` a la mitad si el intento no converge, minimo 1).
    Fijar todos a la vez es correcto cuando son pocos (Colombia: 9 de 29)
    pero puede dejar la red sin suficiente regulacion de tension cuando
    son muchos (Espana: 84 de 240) - exactamente lo que se midio al
    intentarlo.

      1. Resolver con todas las barras de generacion en PV.
      2. Ordenar los generadores que exceden su curva por exceso
         descendente (el peor primero).
      3. Intentar fijar a PQ los `tam` peores, SOBRE UNA COPIA - si el
         flujo AC converge, adoptar ese resultado; si no, descartar el
         intento y reducir `tam` a la mitad (minimo 1), reintentando.
      4. El `tam` que convergio se conserva para la siguiente iteracion.
      5. Un generador ya conmutado puede volver a PV si la nueva solucion
         indica que ya no necesita el limite.
      6. Repetir hasta que una ronda no produzca cambios.

    El Slack nunca se conmuta (cerraria el balance del flujo).
    """
    global K_SUBEXCITACION
    if k is not None:
        K_SUBEXCITACION = float(k)

    n = network.copy()
    cap = capacidad(n, verbose=False)
    # tension que cada barra PV deberia sostener (PyPSA la lee de
    # buses.v_mag_pu_set, no de un atributo del generador - verificado
    # contra el modelo real antes de escribir este modulo)
    consigna = {g: float(n.buses.at[n.generators.at[g, 'bus'], 'v_mag_pu_set'])
               for g in n.generators.index}
    # ARRANQUE EN CALIENTE (opcional).
    #
    # El lazo descubre desde cero, iteracion a iteracion, que generadores
    # hay que llevar a PQ. En un barrido N-1 eso se repite para CADA
    # contingencia, y el caso base ya sabe la respuesta casi entera: una
    # contingencia cambia el estado alrededor del elemento que sale, no
    # en los 978 generadores. Medido: 14 flujos AC por contingencia, que
    # son el 98% de sus 42,3 s.
    #
    # `fijados_iniciales` (el dict `info['conmutados']` del caso base)
    # siembra el lazo con ese reparto. NO cambia el punto fijo al que se
    # llega: `vuelta_a_pv` libera en la primera ronda a cualquier
    # generador que ya no necesite su limite, asi que el criterio de
    # parada es el mismo. Lo que cambia es cuantas rondas cuesta
    # llegar. Esa equivalencia NO se da por supuesta: la comprueba
    # verificar_arranque_caliente.py elemento a elemento.
    # Generadores que, a solas, no dejan converger el flujo. Se anotan
    # para poder informarlos: son la diferencia entre "el lazo acabo" y
    # "el lazo acabo del todo".
    tercos = set()
    fijados = {}
    if fijados_iniciales:
        for g, lim in fijados_iniciales.items():
            if g not in n.generators.index:
                continue
            if n.generators.at[g, 'control'] == 'Slack':
                continue
            n.generators.loc[g, 'control'] = 'PQ'
            n.generators.loc[g, 'q_set'] = float(lim)
            fijados[g] = float(lim)
    historia = []
    lote = None   # tamano de lote que funciono la ultima vez; None = "todos"
    estados_vistos = set()   # firmas del conjunto fijado, para cazar ciclos
    estabilizo = False       # el LAZO llego a un punto fijo
    ciclo = False            # el lazo se repitio: ni converge ni lo hara

    for it in range(1, max_iter + 1):
        resultado = n.pf()
        ok = bool(resultado['converged'].iloc[0, 0])
        if not ok:
            historia.append({'iter': it, 'convergio': False})
            break

        q = n.generators_t.q.iloc[0]
        v = n.buses_t.v_mag_pu.iloc[0]
        cambios = 0

        candidatos = []
        for g in cap.index:
            if g in fijados or g not in q.index:
                continue
            if n.generators.at[g, 'control'] == 'Slack':
                continue
            qq = float(q[g])
            if qq > cap.at[g, 'Q_max'] + TOL_MVAR:
                candidatos.append((g, cap.at[g, 'Q_max'], qq - cap.at[g, 'Q_max']))
            elif qq < cap.at[g, 'Q_min'] - TOL_MVAR:
                candidatos.append((g, cap.at[g, 'Q_min'], cap.at[g, 'Q_min'] - qq))
        candidatos.sort(key=lambda x: x[2], reverse=True)

        if candidatos:
            tam = lote if lote is not None else len(candidatos)
            tam = min(tam, len(candidatos))
            exito = False
            while tam >= 1:
                intento = n.copy()
                elegidos = candidatos[:tam]
                for g, lim, _ in elegidos:
                    intento.generators.loc[g, 'control'] = 'PQ'
                    intento.generators.loc[g, 'q_set'] = lim
                r2 = intento.pf()
                if bool(r2['converged'].iloc[0, 0]):
                    n = intento
                    for g, lim, _ in elegidos:
                        fijados[g] = lim
                    cambios = len(elegidos)
                    lote = tam
                    exito = True
                    break
                tam //= 2

            if not exito:
                # EL PEOR VIOLADOR, A SOLAS, NO DEJA CONVERGER. PROBAR CON
                # LOS DEMAS (corregido el 2-nov-2026).
                #
                # `candidatos[:tam]` coge SIEMPRE desde el peor, asi que
                # cuando `tam` baja a 1 el unico intento es candidatos[0].
                # Si ese generador es patologico -su bus se queda sin
                # ningun otro soporte de tension al fijarlo- el lazo
                # ENTERO se rendia, sin haber probado los otros quince.
                #
                # Medido en la punta: el lazo paraba en la ITERACION 2 de
                # 60, con estabilizo=False y ciclo=False, dejando 16
                # generadores fuera de curva y 4.747 MVAr de reactivo que
                # ninguna maquina puede entregar. No era falta de
                # iteraciones: era rendirse ante UN caso.
                #
                # Un generador que a solas no deja converger no es razon
                # para no fijar a los demas: se salta, se anota, y se
                # sigue. En la ronda siguiente volvera a aparecer como
                # candidato y se le volvera a intentar, porque la red ya
                # no sera la misma.
                for idx in range(1, len(candidatos)):
                    g, lim, _ = candidatos[idx]
                    intento = n.copy()
                    intento.generators.loc[g, 'control'] = 'PQ'
                    intento.generators.loc[g, 'q_set'] = lim
                    r2 = intento.pf()
                    if bool(r2['converged'].iloc[0, 0]):
                        n = intento
                        fijados[g] = lim
                        cambios = 1
                        lote = 1
                        exito = True
                        tercos.update(c[0] for c in candidatos[:idx])
                        break

            if not exito:
                # Ahora si: NINGUNO de los violadores se puede fijar sin
                # romper la convergencia. Eso ya no es un caso terco sino
                # un estado del que el lazo no sabe salir.
                tercos.update(c[0] for c in candidatos)
                historia.append({'iter': it, 'convergio': True,
                                 'fijados': len(fijados), 'cambios': 0,
                                 'lote': 0})
                break
            # v quedo desactualizada (es del solve de ANTES del intento);
            # recalcularla sobre la red ya adoptada para la vuelta a PV
            v = n.buses_t.v_mag_pu.iloc[0]

        if vuelta_a_pv:
            for g in list(fijados):
                bus = n.generators.at[g, 'bus']
                vv, vref = float(v[bus]), consigna[g]
                sube = fijados[g] >= cap.at[g, 'Q_max'] - TOL_MVAR
                if (sube and vv > vref + TOL_V) or (not sube and vv < vref - TOL_V):
                    n.generators.loc[g, 'control'] = 'PV'
                    n.generators.loc[g, 'q_set'] = 0.0
                    del fijados[g]
                    cambios += 1

        historia.append({'iter': it, 'convergio': True,
                         'fijados': len(fijados), 'cambios': cambios,
                         'lote': lote})
        if cambios == 0:
            estabilizo = True
            break

        # DETECCION DE CICLO. El lazo puede quedarse oscilando entre dos
        # configuraciones: un generador se fija a PQ en su limite, la
        # tension de su bus se va al otro lado de la consigna, la regla de
        # vuelta a PV lo devuelve, y se repite. Antes eso solo se
        # manifestaba como "agoto max_iter", y como `convergio` miraba
        # unicamente el ultimo n.pf(), salia True: la no-convergencia del
        # LAZO quedaba invisible.
        #
        # Caso real: G0946, de 0,050 MW, regulando un bus de 400 kV. Se
        # corrigio en origen (P_NOM_MIN_PV en analisis_n1.py), pero una
        # contingencia puede crear una situacion equivalente en cualquier
        # momento, asi que la deteccion se queda como red de seguridad.
        firma = frozenset(fijados)
        if firma in estados_vistos:
            ciclo = True
            break
        estados_vistos.add(firma)

    resultado = n.pf()
    ok = bool(resultado['converged'].iloc[0, 0])
    v = n.buses_t.v_mag_pu.iloc[0].astype(float)
    info = {
        # `convergio` = el flujo final resuelve. `estabilizo` = ademas el
        # LAZO llego a un punto fijo. Son cosas distintas y confundirlas
        # fue lo que oculto el ciclo durante todo el sub-proyecto F.
        'convergio': bool(ok),
        'estabilizo': bool(estabilizo),
        'ciclo': bool(ciclo),
        'iteraciones': len(historia),
        'conmutados': dict(fijados),
        'tercos': sorted(tercos),
        'historia': pd.DataFrame(historia),
        'v_min': float(v.min()), 'v_max': float(v.max()),
        'v_fuera': int(((v < 0.9) | (v > 1.1)).sum()),
        'restantes': diagnostico(n, cap),
    }

    if verbose:
        print(f"\nLimites de reactivo (k = {K_SUBEXCITACION:.2f})")
        print(f"  iteraciones            : {info['iteraciones']}")
        print(f"  generadores conmutados : {len(fijados)} de {len(n.generators)}")
        print(f"  flujo final convergio  : {info['convergio']}")
        print(f"  el lazo se estabilizo  : {info['estabilizo']}")
        print(f"  tension                : [{info['v_min']:.4f}, "
              f"{info['v_max']:.4f}] pu   fuera de [0,9-1,1]: {info['v_fuera']}")
        if info['ciclo']:
            print(f"\n  AVISO: el lazo entro en CICLO (el conjunto de "
                  f"generadores fijados se repitio). Los resultados de "
                  f"abajo son los de un estado arbitrario del ciclo, no de "
                  f"una solucion. Busca en info['historia'] el generador "
                  f"que se devuelve a PV en todas las iteraciones: casi "
                  f"siempre es una maquina demasiado pequena para regular "
                  f"la tension de su bus (ver P_NOM_MIN_PV).")
        elif not info['estabilizo']:
            print(f"\n  AVISO: el lazo agoto sus {MAX_ITER} iteraciones sin "
                  f"estabilizarse ni repetir estado. Puede estar avanzando "
                  f"muy despacio: sube MAX_ITER y vuelve a mirar.")
        if len(info['restantes']):
            print(f"\n  AVISO: {len(info['restantes'])} siguen fuera de "
                  f"curva tras el lazo")
    return n, info


def comparar(network, k=None, verbose=True):
    """Contrasta el caso sin limites con el caso con limites."""
    v0 = network.buses_t.v_mag_pu.iloc[0].astype(float)
    d0 = diagnostico(network)

    n, info = aplicar(network, k=k, verbose=False)
    v1 = n.buses_t.v_mag_pu.iloc[0].astype(float)

    if verbose:
        print("\nEfecto de imponer los limites de reactivo")
        print(f"  {'':28s} {'SIN limites':>14s} {'CON limites':>14s}")
        print(f"  {'generadores fuera de curva':28s} {len(d0):14d} "
              f"{len(info['restantes']):14d}")
        print(f"  {'tension minima':28s} {v0.min():14.4f} {v1.min():14.4f}")
        print(f"  {'tension maxima':28s} {v0.max():14.4f} {v1.max():14.4f}")
        print(f"  {'barras fuera de rango':28s} "
              f"{int(((v0<0.9)|(v0>1.1)).sum()):14d} {info['v_fuera']:14d}")
    return n, info
