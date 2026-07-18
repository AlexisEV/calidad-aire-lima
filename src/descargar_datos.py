"""descargar los datos crudos del proyecto desde la plataforma nacional de datos abiertos.

uso:
    python src/descargar_datos.py
"""

from pathlib import Path

import requests

# definir la carpeta destino relativa a la raiz del proyecto
CARPETA_CRUDOS = Path(__file__).resolve().parent.parent / "datos" / "crudos"

# usar una cabecera de navegador porque el portal rechaza clientes http genericos
CABECERAS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

# definir las fuentes a descargar: nombre de archivo local -> url de descarga directa
FUENTES = {
    "contaminantes_lima.csv": (
        "https://www.datosabiertos.gob.pe/sites/default/files/"
        "Monitoreo%20de%20los%20contaminantes%20del%20aire%20en%20Lima%20Metropolitana"
        "%20-%20%5BServicio%20Nacional%20de%20Meteorolog%C3%ADa%20e%20Hidrolog%C3%ADa"
        "%20del%20Per%C3%BA%20-%20SENAMHI%5D_1.csv"
    ),
    "diccionario_contaminantes.xlsx": (
        "https://www.datosabiertos.gob.pe/sites/default/files/"
        "Diccionario_Datos_Monitoreo%20de%20los%20contaminantes%20del%20aire%20en%20Lima"
        "%20Metropolitana%20-%20%5BServicio%20Nacional%20de%20Meteorolog%C3%ADa%20e"
        "%20Hidrolog%C3%ADa%20del%20Per%C3%BA%20-%20SENAMHI%5D.xlsx"
    ),
}

# definir las estaciones de monitoreo de senamhi con sus coordenadas
# (extraidas del propio dataset de contaminantes)
ESTACIONES = {
    "CAMPO_DE_MARTE": (-12.0705, -77.0432),
    "CARABAYLLO": (-11.9022, -77.0336),
    "SANTA_ANITA": (-12.0430, -76.9714),
    "SAN_BORJA": (-12.1086, -77.0077),
    "SAN_JUAN_DE_LURIGANCHO": (-11.9816, -76.9992),
    "SAN_MARTIN_DE_PORRES": (-12.0089, -77.0845),
    "VILLA_MARIA_DEL_TRIUNFO": (-12.1664, -76.9200),
}

# definir el periodo a descargar (mismo rango que el dataset de contaminantes)
FECHA_INICIO = "2015-01-01"
FECHA_FIN = "2024-05-31"

# definir la api historica de open-meteo (reanalisis era5, sin clave, uso no comercial)
URL_OPEN_METEO = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES_CLIMA = [
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "wind_speed_10m",
    "wind_direction_10m",
]


def descargar_archivo(url: str, destino: Path) -> None:
    """descargar un archivo por http en bloques y guardarlo en la ruta destino."""
    respuesta = requests.get(url, stream=True, timeout=120, headers=CABECERAS)
    respuesta.raise_for_status()
    with open(destino, "wb") as archivo:
        for bloque in respuesta.iter_content(chunk_size=1024 * 1024):
            archivo.write(bloque)


def descargar_fuentes(forzar: bool = False) -> None:
    """descargar todas las fuentes definidas, omitiendo las que ya existen salvo que se fuerce."""
    CARPETA_CRUDOS.mkdir(parents=True, exist_ok=True)
    for nombre, url in FUENTES.items():
        destino = CARPETA_CRUDOS / nombre
        if destino.exists() and not forzar:
            print(f"ya existe, omitir: {nombre}")
            continue
        print(f"descargando: {nombre} ...")
        descargar_archivo(url, destino)
        tamano_mb = destino.stat().st_size / (1024 * 1024)
        print(f"  listo ({tamano_mb:.1f} MB)")


def descargar_clima_estacion(nombre: str, latitud: float, longitud: float, destino: Path) -> None:
    """descargar el clima horario historico de open-meteo para una coordenada y guardarlo como csv."""
    import pandas as pd

    parametros = {
        "latitude": latitud,
        "longitude": longitud,
        "start_date": FECHA_INICIO,
        "end_date": FECHA_FIN,
        "hourly": ",".join(VARIABLES_CLIMA),
        "timezone": "America/Lima",
    }
    respuesta = requests.get(URL_OPEN_METEO, params=parametros, timeout=300)
    respuesta.raise_for_status()
    datos = respuesta.json()["hourly"]
    tabla = pd.DataFrame(datos)
    tabla.insert(0, "estacion", nombre)
    tabla.to_csv(destino, index=False)


def descargar_clima(forzar: bool = False) -> None:
    """descargar el clima de open-meteo para todas las estaciones de monitoreo."""
    CARPETA_CRUDOS.mkdir(parents=True, exist_ok=True)
    for nombre, (lat, lon) in ESTACIONES.items():
        destino = CARPETA_CRUDOS / f"clima_{nombre.lower()}.csv"
        if destino.exists() and not forzar:
            print(f"ya existe, omitir: {destino.name}")
            continue
        print(f"descargando clima: {nombre} ...")
        descargar_clima_estacion(nombre, lat, lon, destino)
        tamano_mb = destino.stat().st_size / (1024 * 1024)
        print(f"  listo ({tamano_mb:.1f} MB)")


if __name__ == "__main__":
    descargar_fuentes()
    descargar_clima()
    print("descarga completa")
