"""Visualizaciones del analisis N-1: elementos mas criticos y distribucion de
severidad. Lee el CSV que produce analisis_n1.py, no vuelve a correr el flujo
de potencia (solo reconstruye la topologia, sin flujo AC, para la
clasificacion domestico/agregado de abajo).

Clasifica cada contingencia que aisla carga en "domestica" o "cruza a un bus
agregado de pais" (Portugal/Francia se modelan como 4 buses por pais con toda
la demanda del pais concentrada ahi - ver hallazgo del revisor en el plan).
Sin esto, el maximo de MW desconectados sale dominado por artefactos del
modelo (cortar la unica linea a un bus de 14.500 MW "desconecta" ese bus
entero) en vez de reflejar fragilidad real de la red iberica.

IMPORTANTE - desviacion respecto al plan original: clasificar mirando solo si
bus0/bus1 DEL ELEMENTO QUITADO empiezan por "PT"/"FR" (la propuesta inicial)
da un resultado incorrecto: 174 eventos "domesticos" con maximo 14.565,8 MW
-- identico al artefacto que se queria excluir. La razon es que hay
transformadores y lineas con nombre 100% espanol (ej. TR_ES00743_ES00744,
entre ES00743 y ES00744) que son el UNICO camino hacia un bus agregado un
salto mas alla del elemento quitado: cortar ese trafo aisla a ES00744 +
FR00742 juntos, aunque el trafo en si no toca ningun bus PT/FR por nombre.
Se detecto por 8 casos asi (5 lineas + 3 trafos) al re-derivar la topologia
igual que separar_islas() en analisis_n1.py. La clasificacion correcta
revisa que bus queda en la isla NO principal (la de menor generacion) tras
quitar el elemento, no solo los dos buses del elemento en si. Con esa
correccion el resultado es 166 domesticos (max 311,4 MW) / 14 agregados
(max 14.565,8 MW, 97,7% del total de MW) -- coincide con las cifras del
revisor de la Tarea 2.

ESAS CIFRAS SON DEL BARRIDO DE SEPTIEMBRE. Sobre el barrido vigente del
apagon (1-nov-2026) la misma clasificacion da 167 domesticos (max
332,0 MW) / 14 agregados (max 14.570,1 MW, 97,6%). La logica no ha
cambiado: ha cambiado el barrido de entrada, que es justo lo que este
modulo no estaba haciendo antes de que se le pudiera pedir el escenario
(ver `analisis_n1.fuente_n1`)."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

from iberia import config
import pypsa

from iberia import analisis_n1 as _a

# El escenario del barrido que se dibuja. Sin bandera se coge el barrido
# por escenario mas reciente; con ella, el que se pida. Antes no habia
# forma de decirlo y se dibujaba lo que `fuente_n1` encontrase primero,
# que resulto ser un fichero de seis semanas antes.
import argparse as _ap
_p = _ap.ArgumentParser(description=__doc__)
config.anadir_arg_red(_p, por_defecto=None)
_args, _ = _p.parse_known_args()

_ruta, _etiqueta = _a.fuente_n1(red=_args.red)
d = pd.read_csv(_ruta, encoding='utf-8-sig')

# --- Clasificar cada contingencia que aisla carga por si la isla separada
#     contiene un bus agregado PT/FR (ver nota arriba: no basta con mirar
#     los buses del elemento quitado) ---
n = pypsa.Network(config.red('iberia_scenario.nc'))
bus0 = pd.concat([n.lines.bus0, n.transformers.bus0])
bus1 = pd.concat([n.lines.bus1, n.transformers.bus1])

grafo_base = nx.Graph()
grafo_base.add_nodes_from(n.buses.index)
grafo_base.add_edges_from(zip(n.lines.bus0, n.lines.bus1))
grafo_base.add_edges_from(zip(n.transformers.bus0, n.transformers.bus1))


def es_domestico(row):
    """True si la isla que se separa al quitar `row.elemento` NO contiene
    ningun bus agregado PT/FR (buses FR00742/FR00859/FR00981/FR01126 y
    PT00277/PT00817/PT00818/PT01092)."""
    if row.tipo == 'Generator':
        return True  # los agregados PT/FR ya estan excluidos del barrido
    b0, b1 = bus0.get(row.elemento), bus1.get(row.elemento)
    if pd.isna(b0) or pd.isna(b1) or not grafo_base.has_edge(b0, b1):
        return True
    g = grafo_base.copy()
    g.remove_edge(b0, b1)
    comps = list(nx.connected_components(g))
    if len(comps) <= 1:
        return True
    gen_por_isla = [float(n.generators[n.generators.bus.isin(c)].p_set.sum()) for c in comps]
    principal = comps[int(np.argmax(gen_por_isla))]
    fuera = [b for c in comps if c is not principal for b in c]
    return not any(str(b).startswith(('PT', 'FR')) for b in fuera)


islas = d[d.MW_desconectados > 0.1].copy()
islas['domestico'] = islas.apply(es_domestico, axis=1)
dom = islas[islas.domestico]
agregado = islas[~islas.domestico]
print(f"Aislamiento domestico: {len(dom)} eventos, max {dom.MW_desconectados.max():.1f} MW"
      if len(dom) else "Aislamiento domestico: 0 eventos")
print(f"Severamiento de bus agregado PT/FR: {len(agregado)} eventos, "
      f"max {agregado.MW_desconectados.max():.1f} MW, "
      f"{agregado.MW_desconectados.sum()/islas.MW_desconectados.sum()*100:.1f}% del total de MW"
      if len(agregado) else "Severamiento de bus agregado PT/FR: 0 eventos")

# Propaga la clasificacion domestico/agregado a TODO el dataframe: por
# defecto True (domestico / no-artefacto) para las contingencias que no
# aislan carga (sobrecarga o tension pura, o generadores) -- el artefacto de
# bus agregado solo puede ocurrir en un evento de aislamiento -- y se
# sobreescribe con la clasificacion real donde corresponde (subset `islas`).
d['domestico'] = True
d.loc[islas.index, 'domestico'] = islas['domestico']

# --- Grafico 1: top 20 elementos mas severos ---
# Coloreado por `domestico` en vez de `convergio`: en este dataset las 3.277
# contingencias convergen todas (0 no convergen), asi que el coloreado por
# convergio del codigo original era vacuo (siempre steelblue). Lo que si
# distingue el ranking de severidad es si el evento es un aislamiento
# domestico real o el artefacto de severar un bus agregado de pais (ver
# docstring del modulo) -- esa es la distincion que de verdad importa para
# no confundir severidad "real" con severidad "artefactual".
fig, ax = plt.subplots(figsize=(10, 8))
top = d.head(20).iloc[::-1]
colores = ['steelblue' if dom else 'crimson' for dom in top.domestico]
ax.barh(top.elemento, top.severidad, color=colores)
ax.set_xlabel('Severidad')
ax.set_title('Las 20 contingencias N-1 mas severas\n'
             '(rojo = severamiento de bus agregado PT/FR, artefacto de modelado; '
             'azul = domestico/real)')
plt.tight_layout()
plt.savefig(config.visualizacion('n1_top_severidad.png'), dpi=150)
plt.close()

# --- Grafico 2: distribucion de cargabilidad maxima por tipo de elemento ---
fig, ax = plt.subplots(figsize=(10, 6))
convergen = d[d.convergio]
for tipo, color in [('Line', 'steelblue'), ('Transformer', 'darkorange'),
                     ('Generator', 'seagreen')]:
    sub = convergen[convergen.tipo == tipo]
    if len(sub):
        ax.hist(sub.carga_max_pct, bins=30, alpha=0.6, label=tipo, color=color)
ax.axvline(100, color='red', linestyle='--', label='100% (limite)')
ax.set_xlabel('Cargabilidad maxima tras la contingencia (%)')
ax.set_ylabel('Numero de contingencias')
ax.set_title('Distribucion de cargabilidad maxima post-contingencia, por tipo')
ax.legend()
plt.tight_layout()
plt.savefig(config.visualizacion('n1_distribucion_cargabilidad.png'), dpi=150)
plt.close()

print("Graficos guardados en resultados/visualizaciones/: n1_top_severidad.png, "
      "n1_distribucion_cargabilidad.png")

# --- Persistir la clasificacion domestico/agregado junto al resto de columnas
#     en una copia del CSV, para que se pueda filtrar por ella sin depender
#     del grafico. No se sobreescribe el CSV original de analisis_n1.py. ---
d.to_csv(config.salida('contingencias_n1_clasificado.csv'), index=False, encoding='utf-8-sig')
print("CSV clasificado guardado en resultados/contingencias_n1_clasificado.csv")
