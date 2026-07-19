"""predecir el pm2.5 medio del dia siguiente por estacion.

uso:
    python src/prediccion.py

construye un dataset diario a partir de combinado.parquet, compara una linea
base de persistencia (manhana = hoy) contra regresion lineal y random forest,
y reporta mae/rmse con validacion temporal (entrenar en el pasado, probar en
el futuro; nunca division aleatoria).
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, root_mean_squared_error

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_PROCESADOS = RAIZ / "datos" / "procesados"

# exigir al menos 12 horas medidas para que la media diaria sea representativa
HORAS_MINIMAS = 12

# frontera del split temporal: entrenar hasta 2022, probar en 2023-2024
FECHA_CORTE = "2023-01-01"

# columnas de clima que se agregan a escala diaria
COLUMNAS_CLIMA = ["temperatura_c", "humedad_rel_pct", "viento_vel_kmh", "precipitacion_mm"]


def cargar_combinado() -> pd.DataFrame:
    """cargar el parquet combinado de contaminantes y clima."""
    return pd.read_parquet(CARPETA_PROCESADOS / "combinado.parquet")


def construir_dataset_diario(combinado: pd.DataFrame, horas_minimas: int = HORAS_MINIMAS) -> pd.DataFrame:
    """agregar el combinado horario a un registro por estacion y dia.

    el pm2.5 diario solo se acepta con al menos `horas_minimas` mediciones en el
    dia; el clima de era5 no tiene huecos, asi que se promedia siempre.
    """
    tabla = combinado.copy()
    tabla["fecha"] = tabla["fecha_hora"].dt.normalize()

    agregaciones = {col: (col, "mean") for col in COLUMNAS_CLIMA}
    agregaciones["precipitacion_mm"] = ("precipitacion_mm", "sum")
    diaria = (
        tabla.groupby(["estacion", "fecha"])
        .agg(
            pm2_5=("pm2_5", "mean"),
            horas_pm2_5=("pm2_5", "count"),
            **agregaciones,
        )
        .reset_index()
    )

    # anular las medias diarias calculadas con muy pocas horas
    diaria.loc[diaria["horas_pm2_5"] < horas_minimas, "pm2_5"] = np.nan
    return diaria.drop(columns=["horas_pm2_5"])


def construir_features(diaria: pd.DataFrame) -> pd.DataFrame:
    """construir la tabla de modelado: un ejemplo por estacion y dia con objetivo manhana.

    cada fila usa solo informacion disponible hoy (pm2.5 de hoy y dias previos)
    mas el clima del dia siguiente, que en un uso real vendria del pronostico.
    """
    partes = []
    for estacion, grupo in diaria.groupby("estacion"):
        # reindexar a un calendario continuo para que los lags respeten los huecos
        grupo = (
            grupo.set_index("fecha")
            .reindex(pd.date_range(grupo["fecha"].min(), grupo["fecha"].max(), freq="D"))
            .rename_axis("fecha")
        )
        parte = pd.DataFrame(index=grupo.index)
        parte["estacion"] = estacion

        # historia reciente de pm2.5 conocida al momento de predecir
        parte["pm25_hoy"] = grupo["pm2_5"]
        parte["pm25_ayer"] = grupo["pm2_5"].shift(1)
        parte["pm25_hace_2"] = grupo["pm2_5"].shift(2)
        parte["pm25_media_7d"] = grupo["pm2_5"].rolling(7, min_periods=5).mean()

        # clima del dia a predecir (disponible como pronostico en la practica)
        for col in COLUMNAS_CLIMA:
            parte[f"{col}_manhana"] = grupo[col].shift(-1)

        # objetivo: pm2.5 medio de manhana
        parte["pm25_manhana"] = grupo["pm2_5"].shift(-1)
        partes.append(parte.reset_index())

    tabla = pd.concat(partes, ignore_index=True)

    # calendario del dia a predecir: mes (estacionalidad) y dia de semana (trafico)
    manhana = tabla["fecha"] + pd.Timedelta(days=1)
    tabla["mes"] = manhana.dt.month
    tabla["dia_semana"] = manhana.dt.dayofweek

    # conservar solo ejemplos completos (objetivo y todas las features presentes)
    return tabla.dropna().reset_index(drop=True)


def preparar_matrices(tabla: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """separar la matriz de features (con dummies) y el vector objetivo."""
    x = tabla.drop(columns=["fecha", "pm25_manhana"])
    x = pd.get_dummies(x, columns=["estacion", "mes", "dia_semana"])
    y = tabla["pm25_manhana"]
    return x, y


def dividir_por_fecha(tabla: pd.DataFrame, fecha_corte: str = FECHA_CORTE) -> tuple[pd.DataFrame, pd.DataFrame]:
    """dividir en entrenamiento (pasado) y prueba (futuro) segun la fecha de corte."""
    corte = pd.Timestamp(fecha_corte)
    return tabla[tabla["fecha"] < corte], tabla[tabla["fecha"] >= corte]


def evaluar(y_real: pd.Series, y_pred: np.ndarray) -> dict:
    """calcular mae y rmse de una prediccion."""
    return {
        "mae": mean_absolute_error(y_real, y_pred),
        "rmse": root_mean_squared_error(y_real, y_pred),
    }


def entrenar_y_evaluar(
    entrenamiento: pd.DataFrame, prueba: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """entrenar los modelos y devolver metricas, predicciones y modelos ajustados.

    devuelve (metricas, predicciones, modelos): las metricas globales por
    modelo, la tabla de prueba con una columna de prediccion por modelo, y los
    modelos ajustados con sus columnas de entrenamiento.
    """
    x_entrenamiento, y_entrenamiento = preparar_matrices(entrenamiento)
    x_prueba, y_prueba = preparar_matrices(prueba)
    x_prueba = x_prueba.reindex(columns=x_entrenamiento.columns, fill_value=False)

    predicciones = prueba.copy()

    # linea base de persistencia: manhana sera igual que hoy
    predicciones["pred_persistencia"] = prueba["pm25_hoy"]

    lineal = LinearRegression()
    lineal.fit(x_entrenamiento, y_entrenamiento)
    predicciones["pred_lineal"] = lineal.predict(x_prueba)

    # hiperparametros elegidos con validacion en 2022 (nunca sobre la prueba):
    # hojas grandes y submuestreo de features regularizan mejor esta serie
    bosque = RandomForestRegressor(
        n_estimators=300,
        min_samples_leaf=20,
        max_features=0.6,
        random_state=42,
        n_jobs=-1,
    )
    bosque.fit(x_entrenamiento, y_entrenamiento)
    predicciones["pred_bosque"] = bosque.predict(x_prueba)

    metricas = pd.DataFrame(
        {
            nombre: evaluar(y_prueba, predicciones[columna])
            for nombre, columna in [
                ("persistencia", "pred_persistencia"),
                ("regresion lineal", "pred_lineal"),
                ("random forest", "pred_bosque"),
            ]
        }
    ).T
    modelos = {"lineal": lineal, "bosque": bosque, "columnas": list(x_entrenamiento.columns)}
    return metricas, predicciones, modelos


def metricas_por_estacion(predicciones: pd.DataFrame) -> pd.DataFrame:
    """desglosar el mae de cada modelo por estacion."""
    filas = []
    for estacion, grupo in predicciones.groupby("estacion"):
        filas.append(
            {
                "estacion": estacion,
                "dias": len(grupo),
                "mae_persistencia": mean_absolute_error(grupo["pm25_manhana"], grupo["pred_persistencia"]),
                "mae_lineal": mean_absolute_error(grupo["pm25_manhana"], grupo["pred_lineal"]),
                "mae_bosque": mean_absolute_error(grupo["pm25_manhana"], grupo["pred_bosque"]),
            }
        )
    return pd.DataFrame(filas).set_index("estacion")


def guardar_predicciones(predicciones: pd.DataFrame) -> Path:
    """guardar las predicciones del periodo de prueba para que el dashboard las lea.

    asi el dashboard desplegado no entrena modelos en cada arranque: solo
    carga este parquet y calcula metricas sobre el, que es barato.
    """
    columnas = ["fecha", "estacion", "pm25_hoy", "pm25_manhana",
                "pred_persistencia", "pred_lineal", "pred_bosque"]
    ruta = CARPETA_PROCESADOS / "predicciones_pm25.parquet"
    predicciones[columnas].reset_index(drop=True).to_parquet(ruta, index=False)
    return ruta


def ejecutar_experimento() -> None:
    """correr el experimento completo, imprimir las metricas y guardar las predicciones."""
    print("construir dataset diario ...")
    diaria = construir_dataset_diario(cargar_combinado())
    tabla = construir_features(diaria)
    entrenamiento, prueba = dividir_por_fecha(tabla)
    print(
        f"  {len(tabla):,} ejemplos: {len(entrenamiento):,} de entrenamiento "
        f"(hasta {FECHA_CORTE}) y {len(prueba):,} de prueba"
    )

    print("entrenar y evaluar ...")
    metricas, predicciones, _ = entrenar_y_evaluar(entrenamiento, prueba)
    print("\nmetricas sobre el periodo de prueba (µg/m³):")
    print(metricas.round(2).to_string())
    print("\nmae por estacion (µg/m³):")
    print(metricas_por_estacion(predicciones).round(2).to_string())

    ruta = guardar_predicciones(predicciones)
    print(f"\npredicciones guardadas en {ruta.relative_to(RAIZ)}")


if __name__ == "__main__":
    ejecutar_experimento()
