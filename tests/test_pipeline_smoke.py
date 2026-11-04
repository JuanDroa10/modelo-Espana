"""Smoke test del pipeline completo. Corre los scripts de la cadena real (build->fix->
fix_v2->balearic->neighbors_v2->scenario_v2->fix_scenario->fix_negative_snom->
add_compensacion) y verifica que la red final tenga las cifras documentadas en
06_documentacion/README.txt.

AVISO: ESTE TEST ES DESTRUCTIVO. No comprueba la red existente: la
RECONSTRUYE entera, sobrescribiendo iberia_scenario.nc y todos los .nc
intermedios. No lo corras mientras haya un analisis leyendo esas redes (un
barrido N-1 dura horas y se quedaria a medias sobre un fichero cambiado
bajo sus pies). Es un gate de la cadena de construccion, no una
verificacion barata que puedas lanzar en cualquier momento.

Y DEJA EL MODELO A MEDIAS. La cadena de arriba termina con los 179
transformadores en su valor PROVISIONAL (s_nom = 1.000 MVA para todos,
r = 0,010), porque dimensionarlos exige el flujo de los dos puntos de
operacion y esos todavia no existen a esta altura. Quien corra este
script SOLO deja el modelo sin la fase 4. Para volver a dejarlo entero:

    python build_blackout_snapshot.py
    python build_punta_snapshot.py
    python dimensionar_trafos.py --aplicar

`correr_todo.py` ya lo hace en ese orden. Este aviso existe porque
durante un tiempo NO lo hacia, y como este test solo comprueba CONTEOS
---que no cambian al revertir el dimensionado--- la degradacion pasaba
en verde."""
import subprocess
import sys
import time

from iberia import config
import pypsa

CADENA = [
    "iberia.construccion.build_full_network",
    "iberia.construccion.fix_network",
    "iberia.construccion.fix_network_v2",
    "iberia.construccion.fix_balearic",
    "iberia.construccion.add_neighbors_v2",
    "iberia.construccion.create_scenario_v2",
    "iberia.construccion.fix_scenario",
    "iberia.construccion.fix_negative_snom",
    "iberia.construccion.add_compensacion",
]

CIFRAS_ESPERADAS = {
    "buses": 1225,
    "lines": 2156,
    "transformers": 179,  # confirmado en la Tarea 3, no 170 (ver nota de "Cadena real del pipeline")
    "generators": 978,  # 942 (README/Tarea 3) + 16 PT + 20 FR: ese 942 se midio en iberia_final_network.nc,
    # antes de que add_neighbors_v2.py pueble los buses PT/FR; verificado corriendo la cadena completa
    # y descomponiendo iberia_scenario.nc por prefijo (ver task-4-report.md)
    "loads": 1224,  # CORREGIDO 2026-10-03: decia 1216, pero la red tiene 1.224
    # (es la cifra que publican el README y el informe). El error sobrevivio
    # porque la tolerancia del 2% lo tapaba: 1216 vs 1224 es un 0,66%.
}
# Los conteos de componentes son DETERMINISTAS: la cadena no tiene ninguna
# fuente de aleatoriedad, asi que el numero correcto es el numero exacto. Una
# tolerancia aqui no absorbe ruido -no hay ruido- sino que ciega el test ante
# derivas reales: con el 2% anterior, este gate aceptaba cualquier cosa entre
# 1.199 y 1.249 cargas. Si en el futuro falla por un componente de diferencia,
# eso es informacion, no un falso positivo: hay que averiguar que cambio.
TOLERANCIA = 0.0

REINTENTOS = 3
ESPERA_REINTENTO = 2  # segundos: tolera un PermissionError transitorio de OneDrive
# (file-locking durante la escritura de un .nc) sin marcar el pipeline como roto.


def main():
    for script in CADENA:
        print(f"--- {script} ---")
        r = None
        for intento in range(1, REINTENTOS + 1):
            r = subprocess.run([sys.executable, '-m', script], capture_output=True,
                               text=True, cwd=str(config.RAIZ))
            if r.returncode == 0:
                break
            print(f"  intento {intento}/{REINTENTOS} fallo (returncode={r.returncode})")
            if intento < REINTENTOS:
                time.sleep(ESPERA_REINTENTO)
        if r.returncode != 0:
            print(r.stdout[-2000:])
            print(r.stderr[-2000:])
            raise SystemExit(f"{script} fallo (returncode={r.returncode}) tras {REINTENTOS} intentos")

    n = pypsa.Network(config.red("iberia_scenario.nc"))
    conteos = {
        "buses": len(n.buses),
        "lines": len(n.lines),
        "transformers": len(n.transformers),
        "generators": len(n.generators),
        "loads": len(n.loads),
    }
    print("Conteos finales:", conteos)

    fallos = []
    for clave, esperado in CIFRAS_ESPERADAS.items():
        real = conteos[clave]
        if abs(real - esperado) > esperado * TOLERANCIA:
            fallos.append(f"{clave}: esperado ~{esperado}, obtenido {real}")

    n_neg = (n.lines.s_nom < 0).sum()
    if n_neg > 0:
        fallos.append(f"{n_neg} lineas con s_nom negativo (fix_negative_snom.py no funciono)")

    h_nonzero = int((n.generators.H > 0).sum())
    print(f"Generadores con H>0: {h_nonzero}/{len(n.generators)}")
    assert h_nonzero > 200, f"siguen faltando valores de H: solo {h_nonzero} (build_full_network.py no esta pasando H/X_d/X_d_prime a n.add)"

    # El check anterior solo mira la CANTIDAD de generadores con H>0: no detecta una
    # tecnologia con H incorrecto-pero-no-cero (ej. Coal/Steam_turbine con H=5.0 en vez
    # de 6.0, que casi se publica). Se complementa con una verificacion de MAGNITUD.
    inercia_total = float((n.generators.H * n.generators.p_nom).sum() / 1000)
    print(f"Inercia total: {inercia_total:.1f} GW.s")
    if not (590 < inercia_total < 605):
        fallos.append(f"inercia total fuera de rango esperado (590-605 GW.s): {inercia_total:.1f}")

    # La compensacion reactiva (sub-proyecto G) vive DENTRO de la cadena:
    # si alguien la saca, la siguiente reconstruccion deja el modelo sin
    # ningun sumidero de reactivo y vuelve el artefacto del 82% de buses
    # fuera de rango que documenta el sub-proyecto F.
    reac = n.shunt_impedances
    n_reac = int(sum(str(i).startswith('reac_') for i in reac.index))
    print(f"Reactores shunt: {n_reac}")
    if n_reac < 1000:
        fallos.append(f"faltan reactores shunt: solo {n_reac} "
                      f"(add_compensacion.py no corrio o no se guardo)")
    elif float(reac.b.sum()) >= 0:
        fallos.append(f"la susceptancia de los reactores deberia ser "
                      f"NEGATIVA (inductiva): {reac.b.sum():.4f} S")

    if fallos:
        raise SystemExit("Smoke test FALLO:\n  " + "\n  ".join(fallos))
    print("Smoke test OK: pipeline completo reproduce las cifras documentadas.")


if __name__ == "__main__":
    main()
