"""Verifica limites_reactivos_espana.py contra el caso base real. Ver
06_documentacion/2026-10-02-diseno-sub-proyecto-F-limites-reactivos.md."""
from iberia import analisis_n1 as A
from iberia import limites_reactivos_espana as L


def test_capacidad_sin_nan_ni_negativos():
    base, _ = A.caso_base(verbose=False, con_limites=False)
    cap = L.capacidad(base)
    assert not cap.isna().any().any(), "la curva de capacidad no debe tener NaN"
    assert (cap.S_nom > 0).all(), "S_nom debe ser positivo para todo generador"
    assert (cap.Q_max >= 0).all(), "Q_max no puede ser negativo"
    print(f"OK: curva de capacidad valida para los {len(cap)} generadores, "
          f"sin NaN ni valores negativos imposibles")


def test_ningun_generador_despacha_por_encima_de_su_placa():
    """NINGUN generador puede tener p_set > p_nom. Es fisica, no un
    objetivo de calidad: una central no entrega mas de lo que tiene.

    HISTORIA, porque este test cambio de sentido. Antes exigia
    EXACTAMENTE 96 generadores en esa situacion, tratandolos como un bug
    de datos conocido que el sub-proyecto F absorbia con una red de
    seguridad -dimensionar la curva de capacidad sobre p_set en vez de
    sobre el p_nom 'roto'-.

    No eran un bug de los datos de origen. Los creaba create_scenario_v2,
    que repartia los 3.000 MW del escenario A PARTES IGUALES entre los
    668 renovables espanoles: 4,4910 MW a cada uno, tuviera 1 MW o 1.401
    de placa. 82 generadores recibian mas MW que toda su capacidad.
    Corregido el reparto a proporcional al margen libre, quedan CERO.

    El test se invierte en consecuencia: de 'deben ser exactamente 96' a
    'no debe haber ninguno'. La red de seguridad de capacidad() se queda
    por si acaso, pero ya no deberia activarse nunca."""
    base, _ = A.caso_base(verbose=False, con_limites=False)
    g = base.generators
    rotos = g[g.p_set > g.p_nom + 1e-6]
    assert len(rotos) == 0, (
        f"{len(rotos)} generadores despachan por encima de su placa, que es "
        f"fisicamente imposible. El reparto del escenario "
        f"(create_scenario_v2.py) deberia ser proporcional al margen libre "
        f"y topado en p_nom; si han reaparecido, probablemente ha vuelto el "
        f"reparto plano.\n"
        f"{rotos[['p_nom', 'p_set', 'carrier']].head(10).to_string()}")
    print(f"OK: ninguno de los {len(g)} generadores despacha por encima de "
          f"su placa (antes eran 96, hasta 4,7x)")


def test_el_lazo_se_estabiliza():
    """EL LAZO DEBE CONVERGER, no agotar las iteraciones.

    Antes no lo hacia: entraba en ciclo limite de periodo 1 y salia por
    agotamiento de max_iter, en silencio. El culpable era G0946, un
    Run_of_river de 0,050 MW (50 kW) que es el UNICO sincrono de un bus
    de 400 kV y al que preparar_para_flujo_ac promovia a regular la
    tension de ese nudo. PyPSA le asignaba el reactivo entero del bus
    (-67 MVAr) contra una curva de +-0,05 MVAr; se le fijaba en Q_min, la
    tension caia, la regla de retorno lo devolvia a PV, y vuelta a
    empezar. Observado: devuelto a PV en las 8 primeras iteraciones sin
    excepcion, con el estado repitiendose en la 8.

    Que esto se detecte importa mas que el numero concreto: un lazo que
    cicla cuesta 60 iteraciones (~180 s) en vez de 7 (~21 s), y ese coste
    inflado fue lo que hizo descartar el barrido N-1 completo con limites
    por "inviable, 162 h" cuando en realidad son ~14 h."""
    base, _ = A.caso_base(verbose=False, con_limites=False)
    _, info = L.aplicar(base, verbose=False)
    assert info['iteraciones'] < L.MAX_ITER, (
        f"el lazo agoto las {L.MAX_ITER} iteraciones sin estabilizarse. "
        f"Casi siempre significa que algun generador oscila entre PV y PQ: "
        f"mira info['historia'], busca el que aparezca devuelto a PV en "
        f"todas las iteraciones, y comprueba si es una maquina demasiado "
        f"pequena para regular la tension de su bus (ver P_NOM_MIN_PV en "
        f"analisis_n1.py).")
    assert info['convergio'], "el flujo final no converge"
    print(f"OK: el lazo se estabiliza en {info['iteraciones']} iteraciones "
          f"(limite {L.MAX_ITER}), {len(info['conmutados'])} conmutados")


def test_diagnostico_sobre_el_caso_base():
    base, _ = A.caso_base(verbose=False, con_limites=False)
    d = L.diagnostico(base)
    n_sinc = int((base.generators.H > 0).sum())
    assert len(d) <= n_sinc, (
        f"{len(d)} generadores fuera de curva de {n_sinc} sincronos: "
        f"imposible, revisar diagnostico()")
    print(f"Sin limites de reactivo: {len(d)} de {n_sinc} generadores "
          f"sincronos exceden su curva de capacidad en el caso base")
    if len(d):
        print(d.round(1).head(10).to_string(index=False))


def test_aplicar_no_excede_a_quien_fijo():
    """Tras aplicar(), todo generador conmutado a PQ debe tener su q_set
    exactamente en el limite que motivo la conmutacion."""
    base, _ = A.caso_base(verbose=False, con_limites=False)
    n, info = L.aplicar(base, verbose=False)
    assert info['convergio'], "el flujo con limites deberia converger sobre el caso base"
    for g, lim in info['conmutados'].items():
        assert abs(float(n.generators.at[g, 'q_set']) - lim) < 1e-6
    print(f"OK: aplicar() convergio, {len(info['conmutados'])} generadores "
          f"conmutados a PQ, todos con su Q fijada en el limite correcto")


def test_comparar_no_empeora_la_tension_minima():
    """Comprobacion de cordura (no una garantia matematica): imponer
    limites de reactivo en el caso base, sin ninguna contingencia, no
    deberia hundir la tension minima de forma absurda."""
    base, _ = A.caso_base(verbose=False, con_limites=False)
    n, info = L.comparar(base, verbose=True)
    assert info['v_min'] > 0.85, (
        f"tension minima con limites ({info['v_min']:.4f}) sospechosamente "
        f"baja para el caso base sin contingencias - revisar antes de "
        f"aceptar el resultado")
    print(f"OK: tension minima con limites = {info['v_min']:.4f} pu, "
          f"dentro de lo esperable para el caso base")


if __name__ == '__main__':
    test_capacidad_sin_nan_ni_negativos()
    test_ningun_generador_despacha_por_encima_de_su_placa()
    test_el_lazo_se_estabiliza()
    test_diagnostico_sobre_el_caso_base()
    test_aplicar_no_excede_a_quien_fijo()
    test_comparar_no_empeora_la_tension_minima()
    print("\nTodas las verificaciones de limites_reactivos_espana.py pasaron.")
