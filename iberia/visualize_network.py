import os
import platform
import subprocess
from pathlib import Path

import pypsa
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import folium
from iberia import config

try:
    import contextily as cx
    CONTEXTILY_DISPONIBLE = True
except ImportError:
    CONTEXTILY_DISPONIBLE = False
    print("AVISO: contextily no esta instalado; los mapas se generaran sin capa de fondo.")


# --- Certificados tras un proxy que intercepta TLS -------------------
# En una maquina corporativa (aqui, Zscaler) el proxy re-firma CADA
# certificado HTTPS con su propia CA. El navegador y curl confian en ella
# porque esta en el llavero de macOS; Python NO, porque `requests` usa el
# bundle de `certifi`, que solo trae CAs publicas. El sintoma exacto es
#
#     SSLError: CERTIFICATE_VERIFY_FAILED: unable to get local issuer
#
# en contextily y en NADA mas del proyecto (el resto no sale a internet).
# Como el mapa interactivo lo descarga el navegador, ese nunca se ve
# afectado: esto solo arregla los mapas ESTATICOS.
#
# Diagnostico, por si reaparece con otro proxy:
#     openssl s_client -connect server.arcgisonline.com:443 | grep " i:"
# Si el emisor no es una CA publica, hay interceptacion TLS.
_BUNDLE = config.DIR_PROYECTO / '.ca_bundle.pem'


def _preparar_certificados():
    """Si certifi no basta, anade al bundle las CAs del llavero de macOS.

    Devuelve True si tras esto `requests` llega a internet. No lanza:
    cualquier fallo deja los mapas sin fondo, que es el comportamiento
    que ya habia."""
    try:
        import certifi
        import requests
    except ImportError:
        return False

    sonda = 'https://server.arcgisonline.com/ArcGIS/rest/services/' \
            'Canvas/World_Light_Gray_Base/MapServer/tile/6/24/31'
    try:
        requests.get(sonda, timeout=15)
        return True                      # certifi basta; no tocamos nada
    except Exception:
        pass

    if platform.system() != 'Darwin':
        print("AVISO: no se verifica el certificado del servidor de mapas y "
              "no es macOS; los mapas estaticos saldran sin fondo.")
        return False

    if not _BUNDLE.exists():
        llaveros = ['/System/Library/Keychains/SystemRootCertificates.keychain',
                    '/Library/Keychains/System.keychain',
                    str(Path.home() / 'Library/Keychains/login.keychain-db')]
        pem = [open(certifi.where(), encoding='utf-8').read()]
        for kc in llaveros:
            try:
                pem.append(subprocess.run(
                    ['security', 'find-certificate', '-a', '-p', kc],
                    capture_output=True, text=True, timeout=30).stdout)
            except Exception:
                continue
        _BUNDLE.write_text('\n'.join(pem), encoding='utf-8')

    # requests y pyOpenSSL leen estas dos variables; contextily usa requests
    os.environ['REQUESTS_CA_BUNDLE'] = str(_BUNDLE)
    os.environ['SSL_CERT_FILE'] = str(_BUNDLE)
    try:
        requests.get(sonda, timeout=15)
        print(f"  (certificados del llavero de macOS anadidos en {_BUNDLE.name})")
        return True
    except Exception as e:
        print(f"AVISO: el servidor de mapas sigue sin validar ({type(e).__name__}); "
              f"los mapas estaticos saldran sin fondo.")
        return False


if CONTEXTILY_DISPONIBLE:
    CONTEXTILY_DISPONIBLE = _preparar_certificados()

# --- Proveedor de mapa base ------------------------------------------
# NO usar CartoDB/Positron: desde 2025 CARTO exige API key y sus tiles
# devuelven un PNG de marca de agua diagonal ("API KEY REQUIRED") en vez
# del mapa. El sintoma es que el mapa "carga" pero sale ilegible, tapado
# por texto repetido. Verificado descargando un tile a mano: HTTP 200,
# 2.049 bytes, con la marca de agua dentro.
#
# Esri WorldGrayCanvas es gris claro y minimalista -misma estetica que
# Positron, que es lo que conviene para que las lineas de la red
# resalten- y NO pide API key (verificado: su URL no lleva {apikey} y el
# tile de prueba sobre Espana devuelve un mapa real).
#
# OJO con el orden de los ejes: Esri sirve /tile/{z}/{y}/{x}, con la Y
# ANTES que la X, al reves del esquema habitual {z}/{x}/{y}.
TILES_INTERACTIVO = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
                     "Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}")
ATRIBUCION_TILES = "Tiles © Esri — Esri, DeLorme, NAVTEQ"
if CONTEXTILY_DISPONIBLE:
    PROVEEDOR_ESTATICO = cx.providers.Esri.WorldGrayCanvas

# --- Configuración ---
NETWORK_PATH = config.red("iberia_full_network.nc")

print("Cargando red...")
n = pypsa.Network(NETWORK_PATH)

# ============================================================
# GRÁFICO 1: Mapa estático con fondo de mapa (contextily)
# ============================================================
print("Generando mapa estático con fondo...")
fig, ax = plt.subplots(figsize=(14, 12))

# Dibujar líneas por nivel de tensión
for v_nom, color, lw in [(400, 'red', 1.0), (220, 'blue', 0.5),
                          (132, 'green', 0.3), (225, 'orange', 0.5),
                          (320, 'purple', 0.5), (250, 'brown', 0.5)]:
    lineas_v = n.lines[n.lines.bus0.map(n.buses.v_nom) == v_nom]
    for _, line in lineas_v.iterrows():
        try:
            x0, y0 = n.buses.loc[line.bus0, ['x', 'y']]
            x1, y1 = n.buses.loc[line.bus1, ['x', 'y']]
            ax.plot([x0, x1], [y0, y1], color=color, linewidth=lw, alpha=0.7)
        except KeyError:
            continue

# Dibujar buses por nivel de tensión
for v_nom, color, size in [(400, 'red', 8), (220, 'blue', 3),
                            (132, 'green', 2), (225, 'orange', 3),
                            (320, 'purple', 3), (250, 'brown', 3)]:
    buses_v = n.buses[n.buses.v_nom == v_nom]
    ax.scatter(buses_v.x, buses_v.y, c=color, s=size, label=f'{v_nom} kV',
               zorder=5, alpha=0.8, edgecolors='black', linewidths=0.3)

ax.set_xlabel('Longitud')
ax.set_ylabel('Latitud')
ax.set_title('Red de Transporte Eléctrica - Península Ibérica\n(1.236 buses, 2.173 líneas)')
ax.legend(loc='lower right', framealpha=0.9)
ax.grid(True, alpha=0.3)

# Añadir fondo de mapa
if CONTEXTILY_DISPONIBLE:
    try:
        cx.add_basemap(ax, crs='EPSG:4326', source=PROVEEDOR_ESTATICO, zoom=6)
        print("  ✓ Mapa base añadido")
    except Exception as e:
        print(f"  ⚠ No se pudo añadir el mapa base: {e}")

plt.tight_layout()
output_png = config.visualizacion("mapa_red_iberia.png")
plt.savefig(output_png, dpi=150, bbox_inches='tight')
print(f"✓ Mapa estático guardado en: {output_png}")
plt.close()

# ============================================================
# GRÁFICO 2: Mapa interactivo (folium con Esri WorldGrayCanvas)
# ============================================================
print("Generando mapa interactivo...")

center = [40.0, -4.0]
m = folium.Map(location=center, zoom_start=6,
               tiles=TILES_INTERACTIVO, attr=ATRIBUCION_TILES)

# Capa de líneas por tensión
for v_nom, color in [(400, 'red'), (220, 'blue'), (132, 'green'),
                      (225, 'orange'), (320, 'purple'), (250, 'brown')]:
    fg = folium.FeatureGroup(name=f'Líneas {v_nom} kV')
    lineas_v = n.lines[n.lines.bus0.map(n.buses.v_nom) == v_nom]
    count = 0
    for _, line in lineas_v.iterrows():
        try:
            x0, y0 = n.buses.loc[line.bus0, ['x', 'y']]
            x1, y1 = n.buses.loc[line.bus1, ['x', 'y']]
            folium.PolyLine(
                locations=[[y0, x0], [y1, x1]],
                color=color, weight=1.5, opacity=0.6,
                popup=f"Línea: {line.name}<br>V: {v_nom} kV<br>Largo: {line.length:.1f} km"
            ).add_to(fg)
            count += 1
        except KeyError:
            continue
    fg.add_to(m)
    print(f"  Líneas {v_nom} kV: {count}")

# Capa de buses 400 kV
fg_buses = folium.FeatureGroup(name='Buses 400 kV')
for _, bus in n.buses[n.buses.v_nom == 400].iterrows():
    folium.CircleMarker(
        location=[bus.y, bus.x],
        radius=3,
        color='red', fill=True, fillColor='red', fillOpacity=0.7,
        popup=f"Bus: {bus.name}<br>V: {bus.v_nom} kV"
    ).add_to(fg_buses)
fg_buses.add_to(m)

# Capa de generadores síncronos
fg_gen = folium.FeatureGroup(name='Generadores síncronos')
sinc = n.generators[n.generators.H > 0]
for _, gen in sinc.iterrows():
    bus = n.buses.loc[gen.bus]
    color = 'green' if 'Nuclear' in str(gen.carrier) else 'orange'
    folium.CircleMarker(
        location=[bus.y, bus.x],
        radius=max(2, min(8, np.sqrt(gen.p_nom) / 3)),
        color=color, fill=True, fillColor=color, fillOpacity=0.6,
        popup=f"{gen.name}<br>Tec: {gen.carrier}<br>P: {gen.p_nom} MW<br>H: {gen.H} s"
    ).add_to(fg_gen)
fg_gen.add_to(m)

# Capa de generadores renovables
fg_ren = folium.FeatureGroup(name='Renovables (PV + Eólica)')
ren = n.generators[n.generators.carrier.isin(['PV', 'Onshore', 'Offshore_floating', 'Solar Thermal'])]
for _, gen in ren.iterrows():
    bus = n.buses.loc[gen.bus]
    color = 'yellow' if gen.carrier == 'PV' else 'cyan'
    folium.CircleMarker(
        location=[bus.y, bus.x],
        radius=max(1, min(5, np.sqrt(gen.p_nom) / 4)),
        color=color, fill=True, fillColor=color, fillOpacity=0.5,
        popup=f"{gen.name}<br>Tec: {gen.carrier}<br>P: {gen.p_nom} MW"
    ).add_to(fg_ren)
fg_ren.add_to(m)

folium.LayerControl().add_to(m)

output_html = config.visualizacion("mapa_red_iberia_interactivo.html")
m.save(output_html)
print(f"✓ Mapa interactivo guardado en: {output_html}")

# ============================================================
# GRÁFICO 3: Distribución por tecnología
# ============================================================
print("Generando gráfico de tecnologías...")
fig, axes = plt.subplots(1, 2, figsize=(15, 6))

tech_count = n.generators.carrier.value_counts()
axes[0].barh(tech_count.index, tech_count.values, color='steelblue')
axes[0].set_xlabel('Número de unidades')
axes[0].set_title('Generadores por tecnología (unidades)')
axes[0].grid(True, alpha=0.3, axis='x')

tech_cap = n.generators.groupby('carrier').p_nom.sum().sort_values(ascending=True)
axes[1].barh(tech_cap.index, tech_cap.values, color='coral')
axes[1].set_xlabel('Capacidad instalada (MW)')
axes[1].set_title('Capacidad por tecnología (MW)')
axes[1].grid(True, alpha=0.3, axis='x')

plt.tight_layout()
output_tech = config.visualizacion("generacion_por_tecnologia.png")
plt.savefig(output_tech, dpi=150, bbox_inches='tight')
print(f"✓ Gráfico de tecnologías guardado en: {output_tech}")
plt.close()

# ============================================================
# GRÁFICO 4: Mapa de inercia (generadores síncronos con tamaño por H·P)
# ============================================================
print("Generando mapa de inercia...")
fig, ax = plt.subplots(figsize=(14, 12))

# Todas las líneas en gris claro de fondo
for _, line in n.lines.iterrows():
    try:
        x0, y0 = n.buses.loc[line.bus0, ['x', 'y']]
        x1, y1 = n.buses.loc[line.bus1, ['x', 'y']]
        ax.plot([x0, x1], [y0, y1], color='lightgray', linewidth=0.3, alpha=0.5)
    except KeyError:
        continue

# Generadores síncronos con tamaño proporcional a H * P (inercia)
sinc = n.generators[n.generators.H > 0].copy()
sinc['inertia'] = sinc['H'] * sinc['p_nom']
for _, gen in sinc.iterrows():
    bus = n.buses.loc[gen.bus]
    size = np.sqrt(gen['inertia']) / 2
    color = 'darkred' if 'Nuclear' in str(gen.carrier) else \
            'darkblue' if 'Combined' in str(gen.carrier) else \
            'darkgreen' if 'Hydro' in str(gen.carrier) or 'Reservoir' in str(gen.carrier) or 'River' in str(gen.carrier) else \
            'purple' if 'Coal' in str(gen.carrier) else 'gray'
    ax.scatter(bus.x, bus.y, s=size, c=color, alpha=0.7, edgecolors='black', linewidths=0.5)

# Leyenda manual
from matplotlib.patches import Patch
legend_elements = [
    Patch(facecolor='darkred', edgecolor='black', label='Nuclear'),
    Patch(facecolor='darkblue', edgecolor='black', label='Ciclo Combinado'),
    Patch(facecolor='darkgreen', edgecolor='black', label='Hidroeléctrica'),
    Patch(facecolor='purple', edgecolor='black', label='Carbón'),
    Patch(facecolor='gray', edgecolor='black', label='Otras'),
]
ax.legend(handles=legend_elements, loc='lower right', framealpha=0.9)
ax.set_xlabel('Longitud')
ax.set_ylabel('Latitud')
ax.set_title('Mapa de Inercia - Generadores Síncronos\n(Tamaño ∝ H·P)')
ax.grid(True, alpha=0.3)

if CONTEXTILY_DISPONIBLE:
    try:
        cx.add_basemap(ax, crs='EPSG:4326', source=PROVEEDOR_ESTATICO, zoom=6)
    except Exception as e:
        print(f"  ⚠ No se pudo añadir el mapa base al mapa de inercia: {e}")

plt.tight_layout()
output_inertia = config.visualizacion("mapa_inercia.png")
plt.savefig(output_inertia, dpi=150, bbox_inches='tight')
print(f"✓ Mapa de inercia guardado en: {output_inertia}")
plt.close()

print()
print("=" * 60)
print("VISUALIZACIONES COMPLETADAS")
print("=" * 60)
print(f"Archivos generados en:")
print(f"  {config.DIR_VISUALIZACIONES}")
print()
print("Ábrelos desde Windows:")
print(f"  1. mapa_red_iberia.png          (mapa estático con fondo)")
print(f"  2. mapa_red_iberia_interactivo.html  (mapa interactivo)")
print(f"  3. generacion_por_tecnologia.png    (gráfico de barras)")
print(f"  4. mapa_inercia.png             (mapa de inercia)")
