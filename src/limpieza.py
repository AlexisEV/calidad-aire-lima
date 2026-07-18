"""limpiar los datos crudos y producir los datasets procesados del proyecto.

uso:
    python src/limpieza.py

produce en datos/procesados/:
    contaminantes.parquet  mediciones horarias limpias de pm10, pm2.5 y no2
    clima.parquet          clima horario de open-meteo por estacion
    combinado.parquet      union de ambos por estacion y fecha_hora
"""

from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_CRUDOS = RAIZ / "datos" / "crudos"
CARPETA_PROCESADOS = RAIZ / "datos" / "procesados"

# tolerar hasta 10% de exceso de pm2.5 sobre pm10 como ruido de sensor;
# por encima de eso anular ambos valores por inconsistencia fisica
TOLERANCIA_PM = 1.10


def leer_contaminantes(ruta: Path) -> pd.DataFrame:
    """leer el csv crudo de contaminantes y normalizar tipos, nombres y zona horaria."""
    tabla = pd.read_csv(ruta)

    # construir el timestamp: fecha y hora vienen en utc (verificado contra
    # los picos de trafico de no2 y los fuegos artificiales de anho nuevo)
    fecha_hora_utc = pd.to_datetime(
        tabla["FECHA"].astype(str) + tabla["HORA"].astype(str).str.zfill(6),
        format="%Y%m%d%H%M%S",
        utc=True,
    )
    tabla["fecha_hora"] = fecha_hora_utc.dt.tz_convert("America/Lima").dt.tz_localize(None)

    # descartar columnas sin informacion util para el analisis
    tabla = tabla.drop(columns=["ID", "FECHA", "HORA", "FECHA_CORTE", "DEPARTAMENTO", "PROVINCIA"])

    # renombrar a nombres consistentes en minusculas
    tabla = tabla.rename(
        columns={
            "ESTACION": "estacion",
            "LONGITUD": "longitud",
            "LATITUD": "latitud",
            "ALTITUD": "altitud",
            "PM10": "pm10",
            "PM2_5": "pm2_5",
            "NO2": "no2",
            "DISTRITO": "distrito",
            "UBIGEO": "ubigeo",
        }
    )
    return tabla


def limpiar_contaminantes(tabla: pd.DataFrame) -> pd.DataFrame:
    """aplicar las reglas de limpieza documentadas en docs/5_decisiones.md."""
    # eliminar duplicados exactos de (estacion, fecha_hora) conservando el primero
    tabla = tabla.drop_duplicates(subset=["estacion", "fecha_hora"], keep="first")

    # convertir a nulo los ceros exactos de no2 (bajo el limite de deteccion o centinela)
    tabla.loc[tabla["no2"] == 0, "no2"] = pd.NA

    # anular pares fisicamente inconsistentes: pm2.5 no puede superar a pm10
    # (se tolera un pequenho exceso por ruido de sensor)
    ambos = tabla["pm10"].notna() & tabla["pm2_5"].notna()
    inconsistente = ambos & (tabla["pm2_5"] > tabla["pm10"] * TOLERANCIA_PM)
    tabla.loc[inconsistente, ["pm10", "pm2_5"]] = pd.NA

    # nota: no eliminar valores extremos altos; los picos de anho nuevo
    # (fuegos artificiales) son eventos reales y parte del analisis

    return tabla.sort_values(["estacion", "fecha_hora"]).reset_index(drop=True)


def leer_clima(carpeta: Path) -> pd.DataFrame:
    """leer y concatenar los csv de clima de open-meteo (ya vienen en hora local de lima)."""
    archivos = sorted(carpeta.glob("clima_*.csv"))
    if not archivos:
        raise FileNotFoundError("no hay archivos clima_*.csv; correr antes src/descargar_datos.py")
    partes = [pd.read_csv(ruta) for ruta in archivos]
    tabla = pd.concat(partes, ignore_index=True)

    tabla["fecha_hora"] = pd.to_datetime(tabla["time"])
    tabla = tabla.drop(columns=["time"])
    tabla = tabla.rename(
        columns={
            "temperature_2m": "temperatura_c",
            "relative_humidity_2m": "humedad_rel_pct",
            "precipitation": "precipitacion_mm",
            "wind_speed_10m": "viento_vel_kmh",
            "wind_direction_10m": "viento_dir_grados",
        }
    )
    columnas = ["estacion", "fecha_hora"] + [c for c in tabla.columns if c not in ("estacion", "fecha_hora")]
    return tabla[columnas].sort_values(["estacion", "fecha_hora"]).reset_index(drop=True)


def unir_contaminantes_clima(contaminantes: pd.DataFrame, clima: pd.DataFrame) -> pd.DataFrame:
    """unir contaminantes y clima por estacion y fecha_hora."""
    return contaminantes.merge(clima, on=["estacion", "fecha_hora"], how="inner")


def ejecutar_pipeline() -> None:
    """correr la limpieza completa y guardar los parquet procesados."""
    CARPETA_PROCESADOS.mkdir(parents=True, exist_ok=True)

    print("leer y limpiar contaminantes ...")
    contaminantes = limpiar_contaminantes(leer_contaminantes(CARPETA_CRUDOS / "contaminantes_lima.csv"))
    contaminantes.to_parquet(CARPETA_PROCESADOS / "contaminantes.parquet", index=False)
    print(f"  contaminantes.parquet: {len(contaminantes):,} filas")

    print("leer clima ...")
    clima = leer_clima(CARPETA_CRUDOS)
    clima.to_parquet(CARPETA_PROCESADOS / "clima.parquet", index=False)
    print(f"  clima.parquet: {len(clima):,} filas")

    print("unir datasets ...")
    combinado = unir_contaminantes_clima(contaminantes, clima)
    combinado.to_parquet(CARPETA_PROCESADOS / "combinado.parquet", index=False)
    print(f"  combinado.parquet: {len(combinado):,} filas")


if __name__ == "__main__":
    ejecutar_pipeline()
    print("limpieza completa")
