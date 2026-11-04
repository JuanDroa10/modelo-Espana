"""Los mapas del modelo: la red, el BTM y la cargabilidad de cada punto.

    python -m iberia.mapas red                  la red por nivel de tension
    python -m iberia.mapas btm                  donde esta el autoconsumo
    python -m iberia.mapas carga --red apagon   cargabilidad del caso base
    python -m iberia.mapas todos                los cuatro

Se escriben en resultados/mapas/ como PNG. El contorno de la peninsula sale
de data/fuentes/contorno_iberia.geojson (Natural Earth, dominio publico), de
modo que los mapas se dibujan SIN internet y sin dependencias cartograficas.

El de cargabilidad resuelve antes el caso base del punto con los limites de
reactivo: ~1 min en el apagon, varios en la punta.
"""
import argparse
import os
import sys
import warnings
import logging

warnings.filterwarnings('ignore')
logging.disable(logging.INFO)

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from iberia import config

AZUL = '#1f4e79'
NARANJA = '#c55a11'
VERDE = '#2e7d4f'
ROJO = '#9e2a2b'
GRIS = '#595959'
GRIS_SUAVE = '#dcdcdc'
MORADO = '#6a3d9a'

plt.rcParams.update({
    'font.family': 'serif',
    'font.serif': ['STIXGeneral', 'DejaVu Serif'],
    'mathtext.fontset': 'stix',
    'font.size': 8, 'axes.titlesize': 8, 'axes.labelsize': 8,
    'legend.fontsize': 7.5, 'xtick.labelsize': 7.5, 'ytick.labelsize': 7.5,
    'axes.spines.top': False, 'axes.spines.right': False,
    'axes.edgecolor': '#333333', 'axes.linewidth': 0.6,
    'axes.grid': True, 'grid.color': GRIS_SUAVE, 'grid.linewidth': 0.4,
    'axes.axisbelow': True,
    'xtick.direction': 'in', 'ytick.direction': 'in',
    'xtick.major.width': 0.6, 'ytick.major.width': 0.6,
    'xtick.major.size': 3, 'ytick.major.size': 3,
    'legend.frameon': False, 'legend.handlelength': 1.8,
    'legend.handletextpad': 0.6, 'legend.labelspacing': 0.35,
    'figure.dpi': 120,
    # NO se usa savefig.bbox='tight': recorta el lienzo al contenido, el
    # fichero sale mas estrecho que el figsize, y el width=\textwidth lo
    # estira en esa proporcion. Cada figura acabaria con un cuerpo de
    # letra distinto. Con constrained el lienzo mide lo que dice figsize.
    'figure.constrained_layout.use': True,
    'figure.constrained_layout.h_pad': 0.02,
    'figure.constrained_layout.w_pad': 0.02,
})

def guardar(fig, nombre):
    ruta = config.mapa(nombre + '.png')
    fig.savefig(ruta, dpi=200)
    plt.close(fig)
    print('  %-24s -> %s' % (nombre, os.path.relpath(ruta, config.RAIZ)))


def coma(x, dec=1):
    """Coma decimal."""
    return ('%.*f' % (dec, x)).replace('.', ',')


_CACHE_RED = {}
_CACHE_BASE = {}


def _red(cual):
    """La red de un punto de operacion, leida una sola vez por corrida."""
    if cual not in _CACHE_RED:
        import pypsa
        _CACHE_RED[cual] = pypsa.Network(config.red_de(cual))
    return _CACHE_RED[cual]


def _caso_base(red):
    """Caso base resuelto CON los limites de reactivo aplicados (cacheado)."""
    if red not in _CACHE_BASE:
        from iberia import analisis_n1 as an
        from iberia import limites_reactivos_espana as L
        base, _ = an.caso_base(verbose=False, con_limites=True, red=red)
        _CACHE_BASE[red] = L.aplicar(base, verbose=False)
    return _CACHE_BASE[red]


def _contorno():
    """Siluetas de Iberia y vecinos. data/fuentes/contorno_iberia.geojson

    Natural Earth 110m, dominio publico, 7 KB. No se usa cartopy ni
    contextily a proposito: el primero es una dependencia pesada y el
    segundo descarga teselas (y produce un mapa raster, no vectorial).
    """
    import json
    ruta = config.dato('contorno_iberia.geojson')
    if not os.path.exists(ruta):
        return []
    geo = json.load(open(ruta, encoding='utf-8'))

    def anillos(g):
        if g.get('type') == 'Polygon':
            return [g['coordinates'][0]]
        if g.get('type') == 'MultiPolygon':
            return [p[0] for p in g['coordinates']]
        return []

    out = []
    for feat in geo.get('features', []):
        nom = feat.get('properties', {}).get('name')
        for a in anillos(feat.get('geometry', {})):
            out.append((nom, [p[0] for p in a], [p[1] for p in a]))
    return out


def _fondo(ax, xlim, ylim):
    """Contorno de Iberia y vecinos, con el mar por debajo."""
    ax.set_facecolor('#eaf0f5')          # el mar
    for nom, xs, ys in _contorno():
        es_ib = nom in ('Spain', 'Portugal')
        ax.fill(xs, ys, facecolor='#fbfbf9' if es_ib else '#f0efec',
                edgecolor='#9aa5b1' if es_ib else '#c8c8c8',
                linewidth=0.7 if es_ib else 0.4, zorder=0)
    ax.set_aspect('equal')
    ax.set_xlim(*xlim); ax.set_ylim(*ylim)
    ax.set_axis_off()


ENCUADRE_X = (-10.0, 4.4)
ENCUADRE_Y = (35.8, 44.2)


def fig_mapa_red():
    """Trazado de la red iberica sobre el contorno de la peninsula.

    Se dibuja desde la red del escenario del apagon, no desde el CSV de
    lineas: asi lo que aparece es exactamente lo que el modelo tiene
    -1.225 barras, 2.156 lineas y 179 transformadores- y no el registro
    del que se partio.

    Los buses de Francia y Portugal se dibujan como cuadrados huecos y
    se rotulan como AGREGADO DE PAIS, no como barras del sistema: son
    cuatro nudos ficticios por pais, y confundirlos con nudos reales es
    el origen de media docena de artefactos de este proyecto (los
    \SI{14570}{MW} de carga aislada, el Slack que saltaba a Francia, las
    perdidas infladas).

    La leyenda va FUERA del area del mapa. Dentro tapaba Portugal, y la
    regla 2 del generador prohibe cargar el area de datos con cosas que
    no son datos.
    """
    n = _red('apagon')
    b = n.buses
    fig, ax = plt.subplots(figsize=(6.30, 4.05))
    _fondo(ax, ENCUADRE_X, ENCUADRE_Y)

    # Lineas por nivel de tension. El 400 kV va encima y mas grueso
    # porque es el que estructura el sistema; el 220 es la malla.
    niveles = [(132.0, '#aebcc9', 0.30, 'linea de 132 kV'),
               (220.0, '#7d97b0', 0.42, 'linea de 220 kV'),
               (400.0, AZUL, 0.85, 'linea de 400 kV')]
    v0 = b.v_nom.reindex(n.lines.bus0).values
    p0 = n.lines.bus0.str[:2]; p1 = n.lines.bus1.str[:2]
    interna = (p0 == p1).values
    for v, color, lw, etq in niveles:
        sel = n.lines[np.isclose(v0, v) & interna]
        segs = [[(b.at[l.bus0, 'x'], b.at[l.bus0, 'y']),
                 (b.at[l.bus1, 'x'], b.at[l.bus1, 'y'])]
                for _, l in sel.iterrows()]
        from matplotlib.collections import LineCollection
        ax.add_collection(LineCollection(
            segs, colors=color, linewidths=lw, zorder=2 if v < 400 else 3,
            capstyle='round', label='%s (%d)' % (etq, len(sel))))

    cruz = n.lines[~interna]
    segs = [[(b.at[l.bus0, 'x'], b.at[l.bus0, 'y']),
             (b.at[l.bus1, 'x'], b.at[l.bus1, 'y'])]
            for _, l in cruz.iterrows()]
    from matplotlib.collections import LineCollection
    ax.add_collection(LineCollection(
        segs, colors=NARANJA, linewidths=1.5, zorder=4, capstyle='round',
        label='interconexion (%d)' % len(cruz)))

    es = b[b.index.str.startswith('ES')]
    pt = b[b.index.str.startswith('PT')]
    fr = b[b.index.str.startswith('FR')]
    ax.scatter(es.x, es.y, s=1.4, color='#2f4256', zorder=5, linewidths=0,
               label='barra espanola (%d)' % len(es))
    ax.scatter(pt.x, pt.y, s=30, marker='s', facecolor='white',
               edgecolor=VERDE, lw=1.1, zorder=6,
               label='agregado de Portugal (%d)' % len(pt))
    ax.scatter(fr.x, fr.y, s=30, marker='s', facecolor='white',
               edgecolor=ROJO, lw=1.1, zorder=6,
               label='agregado de Francia (%d)' % len(fr))

    ax.legend(loc='upper left', bbox_to_anchor=(1.01, 1.0), fontsize=7,
              labelspacing=0.55, borderpad=0.0)
    guardar(fig, 'mapa_red')


def fig_mapa_btm():
    """Donde esta el autoconsumo, sobre el mapa.

    Fuente: btm_regional.capacidad_btm_por_bus() sobre iberia_blackout.nc.
    El area del circulo es proporcional a los MW del bus, no el radio:
    con el radio, un bus de 250 MW parece 25 veces uno de 10 cuando solo
    es 25 veces en area.
    """
    from iberia.btm_regional import capacidad_btm_por_bus
    n = _red('apagon')
    cap = capacidad_btm_por_bus(n)
    cap = cap[cap > 0]
    b = n.buses.loc[cap.index]

    fig, ax = plt.subplots(figsize=(6.30, 4.05))
    _fondo(ax, ENCUADRE_X, ENCUADRE_Y)
    for _, l in n.lines.iterrows():
        ax.plot([n.buses.at[l.bus0, 'x'], n.buses.at[l.bus1, 'x']],
                [n.buses.at[l.bus0, 'y'], n.buses.at[l.bus1, 'y']],
                color='#d7dde3', lw=0.25, zorder=1)

    ax.scatter(b.x, b.y, s=cap.values * 0.9, color=NARANJA, alpha=0.55,
               linewidths=0.2, edgecolor='white', zorder=4)
    for mw in (50, 150, 250):
        ax.scatter([], [], s=mw * 0.9, color=NARANJA, alpha=0.55,
                   linewidths=0.2, edgecolor='white',
                   label='%s MW' % coma(mw, 0))
    ax.legend(loc='upper left', bbox_to_anchor=(1.01, 1.0), fontsize=7,
              labelspacing=1.3, borderpad=0.0, title='BTM por barra',
              title_fontsize=7.5)
    guardar(fig, 'mapa_btm')


BANDAS_CARGA = [
    (0.0, 50.0, '#157f33', 0.30, 'menos del 50 %'),
    (50.0, 75.0, '#d9a406', 0.60, 'del 50 al 75 %'),
    (75.0, 100.0, '#dd5f0a', 1.00, 'del 75 al 100 %'),
    (100.0, float('inf'), '#b01717', 1.70, 'mas del 100 %'),
]


def _mapa_cargabilidad(red):
    """Trazado de la red con las ramas coloreadas por banda de carga.

    Gemela de `mapa_carga_{punto}` del STN. Se dibuja de la banda mas
    baja a la mas alta para que los corredores exigidos queden encima y
    no los tape una linea descargada.
    """
    from matplotlib.collections import LineCollection
    from iberia import analisis_n1 as an
    nl, _ = _caso_base(red)
    b = nl.buses
    pct = an.cargabilidad(nl)

    fig, ax = plt.subplots(figsize=(6.30, 4.05))
    _fondo(ax, ENCUADRE_X, ENCUADRE_Y)
    for lo, hi, color, lw, etq in BANDAS_CARGA:
        sel = [k for k in nl.lines.index
               if lo <= float(pct.get(k, 0.0)) < hi]
        if not sel:
            continue
        segs = [[(b.at[nl.lines.at[k, 'bus0'], 'x'],
                  b.at[nl.lines.at[k, 'bus0'], 'y']),
                 (b.at[nl.lines.at[k, 'bus1'], 'x'],
                  b.at[nl.lines.at[k, 'bus1'], 'y'])] for k in sel]
        ax.add_collection(LineCollection(
            segs, colors=color, linewidths=lw, capstyle='round',
            zorder=2 + BANDAS_CARGA.index((lo, hi, color, lw, etq)),
            label='%s (%d)' % (etq, len(sel))))
    ax.legend(loc='upper left', bbox_to_anchor=(1.01, 1.0), fontsize=7,
              labelspacing=0.55, borderpad=0.0,
              title='cargabilidad', title_fontsize=7.5)
    guardar(fig, 'mapa_carga_%s' % red)


MAPAS = {
    'red': lambda red: fig_mapa_red(),
    'btm': lambda red: fig_mapa_btm(),
    'carga': lambda red: _mapa_cargabilidad(red),
}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('mapa', choices=list(MAPAS) + ['todos'])
    config.anadir_arg_red(ap)
    args = ap.parse_args()
    if args.mapa == 'carga' and args.red not in ('apagon', 'punta'):
        raise SystemExit("el mapa de carga existe para 'apagon' y 'punta'")
    elegidos = ['red', 'btm', 'carga'] if args.mapa == 'todos' else [args.mapa]
    for m in elegidos:
        MAPAS[m](args.red)
    return 0


if __name__ == '__main__':
    sys.exit(main())
