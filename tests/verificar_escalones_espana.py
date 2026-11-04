"""Verifica el mecanismo de escalones de deslastre (P.O. 1.6) en
dinamica_frecuencia.py, con un Sistema sintetico (sin construir la red
PyPSA real) para aislar el mecanismo. Ver el diseno del sub-proyecto E,
seccion E1."""
from iberia import dinamica_frecuencia as din


class SistemaSintetico:
    """Un Sistema minimo para probar el mecanismo de escalones aislado."""
    def __init__(self):
        self.P_gen = 10000.0
        self.P_carga = 9000.0
        # Base del EDAC: carga ESPANOLA sola. Aqui se pone deliberadamente
        # DISTINTA de P_carga (que es ES+PT) para que los tests ejerciten
        # la separacion: si alguien volviera a calcular los escalones
        # sobre P_carga, el test de la fraccion fallaria en vez de pasar
        # por casualidad.
        self.P_carga_es = 7500.0
        self.H = 1.5
        self.S_base = 30000.0
        self.R_eq = 0.05
        self.reserva = 500.0
        self.reserva_baja = 500.0
        self.exportacion = 1000.0   # P_gen - P_carga


def test_sin_deslastre_no_cambia_comportamiento():
    sis = SistemaSintetico()
    eventos = [{'t': 0.5, 'dP_gen': 3000.0, 'etiqueta': 'perdida grande'}]
    t, f, traza = din.simular_frecuencia(sis, eventos)
    assert traza['escalones'] == []
    assert traza['deslastre_total'] == 0.0
    print(f"OK: sin deslastre, nadir={traza['nadir']:.3f} Hz, "
          f"deslastre_total={traza['deslastre_total']:.1f} MW")


def test_escalon_dispara_al_cruzar_el_umbral():
    sis = SistemaSintetico()
    eventos = [{'t': 0.5, 'dP_gen': 3000.0, 'etiqueta': 'perdida grande'}]
    t, f, traza = din.simular_frecuencia(sis, eventos, con_deslastre=True)
    disparados = [e for e in traza['escalones'] if e['disparado']]
    assert len(disparados) >= 1, "deberia disparar al menos el primer escalon"
    e0 = traza['escalones'][0]
    assert e0['disparado']
    k_cruce = int(round(e0['t_disparo'] / din.DT))
    assert f[k_cruce] <= 49.0
    assert f[k_cruce - 1] > 49.0, (
        "el escalon deberia disparar en el PRIMER paso bajo el umbral")
    print(f"OK: escalon 1 (49,0 Hz) disparo en t={e0['t_disparo']:.3f} s, "
          f"{e0['mw']:.1f} MW ({100*e0['fraccion']:.0f}% de la carga "
          f"vigente)")


def test_deslastre_arresta_la_caida_de_frecuencia():
    sis = SistemaSintetico()
    eventos = [{'t': 0.5, 'dP_gen': 3000.0, 'etiqueta': 'perdida grande'}]
    _, _, sin = din.simular_frecuencia(sis, eventos, con_deslastre=False)
    _, _, con = din.simular_frecuencia(sis, eventos, con_deslastre=True)

    # Comparar nadires directamente NO vale: cuando un caso colapsa su
    # nadir es NaN (no hay minimo, la integracion se corta al cruzar
    # F_COLAPSO) y `nan > x` es siempre False, asi que el test fallaba
    # justo en el escenario donde el deslastre funciona MEJOR - evita el
    # colapso del todo. Hay tres desenlaces y cada uno se compara con lo
    # que corresponde.
    if sin['colapso'] and not con['colapso']:
        veredicto = (f"evita el colapso (sin deslastre colapsa en "
                     f"t={sin['t_colapso']:.2f} s; con deslastre sobrevive "
                     f"con nadir={con['nadir']:.3f} Hz)")
    elif sin['colapso'] and con['colapso']:
        assert con['t_colapso'] > sin['t_colapso'], (
            f"ambos casos colapsan y el deslastre deberia al menos "
            f"RETRASARLO: con deslastre t={con['t_colapso']:.2f} s, sin el "
            f"t={sin['t_colapso']:.2f} s")
        veredicto = (f"retrasa el colapso de t={sin['t_colapso']:.2f} s a "
                     f"t={con['t_colapso']:.2f} s")
    else:
        assert not con['colapso'], (
            "el deslastre ha PROVOCADO un colapso que no ocurria sin el: "
            "es un fallo grave del esquema, no una tolerancia numerica")
        assert con['nadir'] > sin['nadir'], (
            f"ninguno colapsa, asi que el nadir con deslastre "
            f"({con['nadir']:.3f} Hz) deberia ser mayor que sin el "
            f"({sin['nadir']:.3f} Hz)")
        veredicto = (f"eleva el nadir de {sin['nadir']:.3f} a "
                     f"{con['nadir']:.3f} Hz")
    print(f"OK: el deslastre {veredicto}")


def test_fraccion_correcta_por_escalon():
    """Con una perdida lo bastante grande, deben disparar los 4 escalones
    con las fracciones reales de P.O. 1.6 (15/15/10/10%), no las
    colombianas (5% uniforme). Si con 9000 MW no disparan los 4 (el
    gobernador/primaria podria frenar la caida antes), sube la magnitud de
    dP_gen hasta que disparen los 4 - lo que importa es la fraccion, no
    esta cifra concreta."""
    sis = SistemaSintetico()
    eventos = [{'t': 0.5, 'dP_gen': 9000.0, 'etiqueta': 'perdida masiva'}]
    t, f, traza = din.simular_frecuencia(sis, eventos, con_deslastre=True)
    disparados = [e for e in traza['escalones'] if e['disparado']]
    assert len(disparados) == 4, (
        f"deberian disparar los 4 escalones, dispararon {len(disparados)} "
        f"- si esto falla, sube dP_gen en el evento sintetico de este test")
    fracciones_esperadas = [0.15, 0.15, 0.10, 0.10]
    for e, frac in zip(disparados, fracciones_esperadas):
        assert abs(e['fraccion'] - frac) < 1e-9
    print(f"OK: 4 escalones dispararon con fracciones "
          f"{[e['fraccion'] for e in disparados]}, "
          f"total deslastrado {traza['deslastre_total']:.1f} MW")





def test_los_escalones_de_bombeo_deciden_el_desenlace():
    """Los dos escalones de bombeo del P.O. 1.6 (49,5 y 49,3 Hz) no son
    un detalle: son la diferencia entre colapsar y sobrevivir.

    HISTORIA. El modelo los ignoraba, con el argumento escrito de que
    "iberia_blackout.nc no tiene carga de bombeo activa en este punto de
    operacion". Era consecuencia de un ERROR DE DATOS: el bombeo estaba
    despachado como generacion (+3.000 MW) cuando la lamina 4 del informe
    de NERC documenta "Pumped Storage 3GW consume". Corregido el signo,
    aparecen 3.000 MW de deslastre indoloro que el esquema real habria
    usado ANTES de tocar a ningun cliente.

    Medido sobre el escenario calibrado:
      sin deslastre                 COLAPSA en 1,81 s
      solo los 4 generales          COLAPSA en 6,03 s
      generales + los 2 de bombeo   SOBREVIVE, nadir 48,000 Hz

    Que un deslastre indoloro de 3.000 MW cambie el desenlace es
    justamente el argumento de por que el P.O. 1.6 los pone primero."""
    import pypsa
    from iberia import config
    from iberia import dinamica_frecuencia as din
    from iberia.analisis_btm_cascada import escenario_real

    n = pypsa.Network(config.red('iberia_blackout.nc'))
    sis = din.Sistema(n)
    ev = escenario_real(n, sis)

    assert sis.P_bombeo_es > 100.0, (
        f"el escenario del apagon deberia tener bombeo EN CONSUMO y tiene "
        f"{sis.P_bombeo_es:.1f} MW. Si vale 0, el signo del bombeo ha vuelto "
        f"a estar invertido en build_blackout_snapshot.py (NERC documenta "
        f"3 GW consumiendo).")

    _, _, sin_bombeo = din.simular_frecuencia(
        sis, ev, con_deslastre=True, fracciones_bombeo=(0.0, 0.0))
    _, _, con_bombeo = din.simular_frecuencia(sis, ev, con_deslastre=True)

    assert sin_bombeo['colapso'], (
        "sin los escalones de bombeo el escenario deberia COLAPSAR; si ya "
        "no lo hace, algo ha cambiado en la inercia o en la reserva y hay "
        "que re-derivar la conclusion antes de citarla")
    assert not con_bombeo['colapso'], (
        f"con los escalones de bombeo el escenario deberia SOBREVIVIR y "
        f"colapsa en t={con_bombeo['t_colapso']}. Revisar que los 3.000 MW "
        f"de bombeo se esten soltando: bombeo_deslastrado="
        f"{con_bombeo.get('bombeo_deslastrado', 0):.1f} MW")
    assert abs(con_bombeo['bombeo_deslastrado'] - sis.P_bombeo_es) < 1.0, (
        f"deberian soltarse los {sis.P_bombeo_es:.0f} MW de bombeo (2 "
        f"escalones del 50%) y se soltaron "
        f"{con_bombeo['bombeo_deslastrado']:.1f}")

    print(f"OK: sin bombeo COLAPSA en {sin_bombeo['t_colapso']:.2f} s; con "
          f"los 2 escalones de bombeo ({con_bombeo['bombeo_deslastrado']:.0f} "
          f"MW) SOBREVIVE con nadir {con_bombeo['nadir']:.3f} Hz")


if __name__ == '__main__':
    test_sin_deslastre_no_cambia_comportamiento()
    test_escalon_dispara_al_cruzar_el_umbral()
    test_deslastre_arresta_la_caida_de_frecuencia()
    test_fraccion_correcta_por_escalon()
    print("\nTodas las verificaciones de escalones pasaron.")
    test_los_escalones_de_bombeo_deciden_el_desenlace()
