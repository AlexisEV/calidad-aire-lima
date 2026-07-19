"""dashboard interactivo de calidad del aire en lima metropolitana.

uso:
    streamlit run dashboard/app.py
"""

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_PROCESADOS = RAIZ / "datos" / "procesados"

# definir umbrales de referencia por contaminante (µg/m³)
UMBRALES = {
    "pm2_5": {"nombre": "PM2.5", "oms": ("guía OMS 24h", 15), "eca": ("ECA Perú 24h", 50)},
    "pm10": {"nombre": "PM10", "oms": ("guía OMS 24h", 45), "eca": ("ECA Perú 24h", 100)},
    "no2": {"nombre": "NO2", "oms": ("guía OMS 24h", 25), "eca": ("ECA Perú anual", 100)},
}

st.set_page_config(page_title="Calidad del aire en Lima", page_icon="🌫️", layout="wide")


@st.cache_data
def cargar_contaminantes() -> pd.DataFrame:
    """cargar el parquet procesado de contaminantes."""
    return pd.read_parquet(CARPETA_PROCESADOS / "contaminantes.parquet")


@st.cache_data
def cargar_combinado() -> pd.DataFrame:
    """cargar el parquet combinado con clima para la pestanha de patrones."""
    return pd.read_parquet(CARPETA_PROCESADOS / "combinado.parquet")


@st.cache_data
def cargar_predicciones() -> pd.DataFrame:
    """cargar las predicciones del periodo de prueba generadas por src/prediccion.py."""
    return pd.read_parquet(CARPETA_PROCESADOS / "predicciones_pm25.parquet")


def serie_diaria(datos: pd.DataFrame, contaminante: str) -> pd.DataFrame:
    """calcular la media diaria del contaminante por estacion."""
    return (
        datos.set_index("fecha_hora")
        .groupby("estacion")[contaminante]
        .resample("D")
        .mean()
        .reset_index()
    )


datos = cargar_contaminantes()

# ---------- barra lateral: filtros ----------
st.sidebar.title("Filtros")
clave = st.sidebar.radio(
    "Contaminante",
    options=list(UMBRALES),
    format_func=lambda c: UMBRALES[c]["nombre"],
)
nombre_contaminante = UMBRALES[clave]["nombre"]

estaciones_todas = sorted(datos["estacion"].unique())
estaciones = st.sidebar.multiselect("Estaciones", estaciones_todas, default=estaciones_todas)

anio_min, anio_max = int(datos.fecha_hora.dt.year.min()), int(datos.fecha_hora.dt.year.max())
rango = st.sidebar.slider("Rango de años", anio_min, anio_max, (anio_min, anio_max))

st.sidebar.markdown("---")
st.sidebar.caption(
    "Datos: SENAMHI vía la Plataforma Nacional de Datos Abiertos (contaminantes) "
    "y Open-Meteo/ERA5 (clima). 2015–2024, 7 estaciones."
)

# aplicar los filtros seleccionados
filtro = (
    datos["estacion"].isin(estaciones)
    & datos.fecha_hora.dt.year.between(rango[0], rango[1])
)
seleccion = datos[filtro]

# ---------- encabezado y metricas ----------
st.title("🌫️ Calidad del aire en Lima Metropolitana")
st.caption("577 mil mediciones horarias de SENAMHI (2015–2024) cruzadas con clima de ERA5")

if seleccion.empty:
    st.warning("no hay datos para la selección actual; ajustar los filtros")
    st.stop()

diaria = serie_diaria(seleccion, clave)
umbral_oms = UMBRALES[clave]["oms"]
umbral_eca = UMBRALES[clave]["eca"]

col1, col2, col3 = st.columns(3)
col1.metric(f"{nombre_contaminante} medio del periodo", f"{seleccion[clave].mean():.1f} µg/m³")
pct_oms = 100 * (diaria[clave].dropna() > umbral_oms[1]).mean()
col2.metric(f"días sobre la {umbral_oms[0]}", f"{pct_oms:.0f} %")
peor = seleccion.groupby("estacion")[clave].mean().idxmax()
col3.metric("estación más contaminada", peor.replace("_", " ").title())

# ---------- pestanhas ----------
tab_serie, tab_comparar, tab_patrones, tab_mapa, tab_prediccion, tab_hallazgos = st.tabs(
    ["📈 Serie de tiempo", "📊 Comparar estaciones", "🕐 Patrones", "🗺️ Mapa", "🔮 Predicción", "💡 Hallazgos"]
)

with tab_serie:
    frecuencia = st.radio("Agregación", ["Diaria", "Mensual"], horizontal=True)
    base = diaria.copy()
    if frecuencia == "Mensual":
        base = (
            base.set_index("fecha_hora")
            .groupby("estacion")[clave]
            .resample("ME")
            .mean()
            .reset_index()
        )
    figura = px.line(
        base,
        x="fecha_hora",
        y=clave,
        color="estacion",
        labels={"fecha_hora": "", clave: f"{nombre_contaminante} (µg/m³)", "estacion": "estación"},
    )
    # dibujar los umbrales como trazas para que aparezcan en la leyenda
    # (las anotaciones sobre la linea quedaban tapadas por los datos)
    x_inicio, x_fin = base["fecha_hora"].min(), base["fecha_hora"].max()
    figura.add_scatter(
        x=[x_inicio, x_fin],
        y=[umbral_oms[1], umbral_oms[1]],
        mode="lines",
        line=dict(dash="dash", color="crimson", width=2),
        name=f"{umbral_oms[0]} ({umbral_oms[1]} µg/m³)",
    )
    figura.add_scatter(
        x=[x_inicio, x_fin],
        y=[umbral_eca[1], umbral_eca[1]],
        mode="lines",
        line=dict(dash="dash", color="orange", width=2),
        name=f"{umbral_eca[0]} ({umbral_eca[1]} µg/m³)",
    )
    figura.update_layout(height=480, legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(figura, width="stretch")

with tab_comparar:
    col_izq, col_der = st.columns(2)

    medias = seleccion.groupby("estacion")[clave].mean().sort_values()
    figura_medias = px.bar(
        medias,
        orientation="h",
        labels={"value": f"{nombre_contaminante} medio (µg/m³)", "estacion": ""},
    )
    figura_medias.add_vline(x=umbral_oms[1], line_dash="dash", line_color="crimson", annotation_text=umbral_oms[0])
    figura_medias.update_layout(height=420, showlegend=False, title="promedio del periodo")
    col_izq.plotly_chart(figura_medias, width="stretch")

    pct_por_estacion = (
        diaria.groupby("estacion")[clave]
        .apply(lambda s: 100 * (s.dropna() > umbral_oms[1]).mean())
        .sort_values()
    )
    figura_pct = px.bar(
        pct_por_estacion,
        orientation="h",
        labels={"value": "% de días", "estacion": ""},
    )
    figura_pct.update_layout(
        height=420, showlegend=False, title=f"% de días sobre la {umbral_oms[0]} ({umbral_oms[1]} µg/m³)"
    )
    figura_pct.update_traces(marker_color="firebrick")
    col_der.plotly_chart(figura_pct, width="stretch")

with tab_patrones:
    col_hora, col_mes = st.columns(2)

    por_hora = seleccion.groupby(seleccion.fecha_hora.dt.hour)[clave].median()
    figura_hora = px.line(
        por_hora,
        markers=True,
        labels={"fecha_hora": "hora local", "value": f"{nombre_contaminante} (µg/m³)"},
    )
    figura_hora.update_layout(height=380, showlegend=False, title="ciclo horario (mediana)")
    col_hora.plotly_chart(figura_hora, width="stretch")

    por_mes = seleccion.groupby(seleccion.fecha_hora.dt.month)[clave].mean()
    figura_mes = px.bar(
        por_mes,
        labels={"fecha_hora": "mes", "value": f"{nombre_contaminante} (µg/m³)"},
    )
    figura_mes.update_layout(height=380, showlegend=False, title="estacionalidad (media por mes)")
    col_mes.plotly_chart(figura_mes, width="stretch")

    # mostrar la relacion con el clima a escala diaria
    st.markdown("#### clima y contaminación (medias diarias)")
    combinado = cargar_combinado()
    combinado = combinado[
        combinado["estacion"].isin(estaciones)
        & combinado.fecha_hora.dt.year.between(rango[0], rango[1])
    ]
    diaria_clima = (
        combinado.set_index("fecha_hora")
        .groupby("estacion")[[clave, "temperatura_c", "viento_vel_kmh"]]
        .resample("D")
        .mean()
        .reset_index()
        .dropna()
    )
    variable_clima = st.selectbox(
        "Variable de clima", ["temperatura_c", "viento_vel_kmh"],
        format_func=lambda v: {"temperatura_c": "temperatura (°C)", "viento_vel_kmh": "viento (km/h)"}[v],
    )
    figura_clima = px.scatter(
        diaria_clima,
        x=variable_clima,
        y=clave,
        color="estacion",
        opacity=0.25,
        trendline="ols",
        labels={clave: f"{nombre_contaminante} (µg/m³)"},
    )
    figura_clima.update_layout(height=450, legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(figura_clima, width="stretch")

with tab_mapa:
    resumen_mapa = (
        seleccion.groupby(["estacion", "distrito"])
        .agg(valor=(clave, "mean"), lat=("latitud", "first"), lon=("longitud", "first"))
        .reset_index()
    )
    # excluir estaciones sin mediciones en el periodo filtrado
    # (el promedio nan no se puede dibujar como tamanho de burbuja)
    sin_datos = resumen_mapa[resumen_mapa["valor"].isna()]["estacion"].tolist()
    resumen_mapa = resumen_mapa.dropna(subset=["valor"])
    if sin_datos:
        nombres = ", ".join(e.replace("_", " ").title() for e in sin_datos)
        st.info(f"sin mediciones de {nombre_contaminante} en el periodo filtrado: {nombres}")
    if resumen_mapa.empty:
        st.warning("ninguna estación tiene mediciones en el periodo filtrado")
        st.stop()
    figura_mapa = px.scatter_map(
        resumen_mapa,
        lat="lat",
        lon="lon",
        size="valor",
        color="valor",
        color_continuous_scale="YlOrRd",
        hover_name="estacion",
        hover_data={"distrito": True, "valor": ":.1f", "lat": False, "lon": False},
        zoom=9.5,
        height=560,
    )
    figura_mapa.update_layout(
        map_style="open-street-map",
        coloraxis_colorbar_title=f"{nombre_contaminante} (µg/m³)",
    )
    st.plotly_chart(figura_mapa, width="stretch")
    st.caption("tamaño y color según el promedio del contaminante en el periodo filtrado")

with tab_prediccion:
    st.markdown("#### ¿Se puede predecir el PM2.5 de mañana?")
    st.markdown(
        "Un random forest entrenado con 2015–2022 (historia reciente de PM2.5, clima del día "
        "siguiente y calendario) predice la media diaria del día siguiente por estación. "
        "Se evalúa sobre 2023–2024, un periodo que el modelo nunca vio, y se compara contra "
        "la línea base de persistencia (*mañana estará igual que hoy*): en series con tanta "
        "inercia, superar esa referencia es lo único que cuenta. Detalles y decisiones en el "
        "notebook 03 del repositorio."
    )
    predicciones = cargar_predicciones()

    # calcular las metricas del periodo de prueba completo
    error_persistencia = (predicciones["pm25_manhana"] - predicciones["pred_persistencia"]).abs().mean()
    error_lineal = (predicciones["pm25_manhana"] - predicciones["pred_lineal"]).abs().mean()
    error_bosque = (predicciones["pm25_manhana"] - predicciones["pred_bosque"]).abs().mean()
    mejora_pct = 100 * (error_persistencia - error_bosque) / error_persistencia

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("MAE persistencia (línea base)", f"{error_persistencia:.2f} µg/m³")
    col_b.metric("MAE regresión lineal", f"{error_lineal:.2f} µg/m³")
    col_c.metric(
        "MAE random forest",
        f"{error_bosque:.2f} µg/m³",
        delta=f"-{mejora_pct:.1f} % vs línea base",
        delta_color="inverse",
    )
    st.caption(
        f"{len(predicciones):,} días de prueba (2023–2024) en las 7 estaciones. La pestaña no "
        "responde a los filtros laterales: el periodo de evaluación es fijo por diseño."
    )

    # comparar prediccion y realidad en la estacion elegida
    estacion_pred = st.selectbox(
        "Estación",
        sorted(predicciones["estacion"].unique()),
        format_func=lambda e: e.replace("_", " ").title(),
    )
    serie_pred = predicciones[predicciones["estacion"] == estacion_pred].sort_values("fecha")
    mae_estacion_base = (serie_pred["pm25_manhana"] - serie_pred["pred_persistencia"]).abs().mean()
    mae_estacion_bosque = (serie_pred["pm25_manhana"] - serie_pred["pred_bosque"]).abs().mean()

    figura_pred = go.Figure()
    figura_pred.add_scatter(
        x=serie_pred["fecha"], y=serie_pred["pm25_manhana"],
        mode="lines", name="PM2.5 real", line=dict(color="gray", width=1.5),
    )
    figura_pred.add_scatter(
        x=serie_pred["fecha"], y=serie_pred["pred_bosque"],
        mode="lines", name="predicción (random forest)", line=dict(color="crimson", width=1.5),
    )
    figura_pred.update_layout(
        height=440,
        legend=dict(orientation="h", y=-0.15),
        yaxis_title="PM2.5 medio diario (µg/m³)",
        title=(
            f"predicción del día siguiente vs realidad — MAE {mae_estacion_bosque:.2f} µg/m³ "
            f"(línea base: {mae_estacion_base:.2f})"
        ),
    )
    st.plotly_chart(figura_pred, width="stretch")

    # desglosar el error por estacion para ver donde ayuda el modelo
    mae_por_estacion = (
        predicciones.assign(
            abs_persistencia=(predicciones["pm25_manhana"] - predicciones["pred_persistencia"]).abs(),
            abs_bosque=(predicciones["pm25_manhana"] - predicciones["pred_bosque"]).abs(),
        )
        .groupby("estacion")[["abs_persistencia", "abs_bosque"]]
        .mean()
        .sort_values("abs_bosque")
    )
    figura_mae = go.Figure()
    figura_mae.add_bar(
        y=[e.replace("_", " ").title() for e in mae_por_estacion.index],
        x=mae_por_estacion["abs_persistencia"],
        orientation="h", name="persistencia (mañana = hoy)", marker_color="lightgray",
    )
    figura_mae.add_bar(
        y=[e.replace("_", " ").title() for e in mae_por_estacion.index],
        x=mae_por_estacion["abs_bosque"],
        orientation="h", name="random forest", marker_color="steelblue",
    )
    figura_mae.update_layout(
        height=380, barmode="group",
        legend=dict(orientation="h", y=-0.2),
        xaxis_title="MAE en el periodo de prueba (µg/m³)",
        title="error por estación: modelo vs línea base",
    )
    st.plotly_chart(figura_mae, width="stretch")
    st.caption(
        "la mejora es modesta (el PM2.5 diario tiene mucha inercia) pero consistente: el modelo "
        "ayuda más en las estaciones volátiles como Carabayllo y San Juan de Lurigancho. La serie "
        "termina en mayo de 2024, así que es un ejercicio retrospectivo, no un pronóstico en vivo."
    )

with tab_hallazgos:
    st.markdown(
        """
### Qué dice el análisis

La OMS recomienda no pasar de 15 µg/m³ de PM2.5 como promedio diario. En cuatro de las siete
estaciones eso se incumple más del 90% de los días. Hasta en Campo de Marte, la más limpia,
ocurre uno de cada dos días. La norma peruana (ECA) casi nunca se excede, pero no porque el
aire esté bien: su límite es tres veces más alto que el de la OMS.

No todos los distritos respiran lo mismo. San Juan de Lurigancho promedia 31 µg/m³ de PM2.5
y Campo de Marte 17. La periferia del este y del norte sale peor parada que el centro.

El invierno concentra la contaminación: 32% más PM2.5 que el verano. No es que en julio se
emita más. El aire frío y quieto, con la inversión térmica encima, deja lo de siempre atrapado
cerca del suelo. A los distritos del interior les pega más fuerte; a los costeros los ventila
la brisa del mar.

En 2020 la cuarentena sacó los autos de la calle y el PM2.5 cayó 25% respecto a 2019. Fue el
año más limpio de la serie. Difícil pedir mejor evidencia del peso del tráfico.

Un dato curioso para cerrar: la madrugada de Año Nuevo tiene en promedio cuatro veces el PM2.5
de una madrugada normal, con picos horarios de 720 µg/m³ por los fuegos artificiales. Esos
picos sirvieron además para descubrir que las horas del dataset oficial venían en UTC, algo
que su documentación no menciona.

La metodología completa y las decisiones de limpieza están en los notebooks del repositorio.
"""
    )
