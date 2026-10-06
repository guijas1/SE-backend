"""Consistent time series for the SmartAir dashboard."""

import pandas as pd
import plotly.graph_objects as go


REFERENCIAS_MQ = (
    ("baseline_mq135", "Baseline", "#64748b"),
    ("limite_mq_normal", "Retorno ao normal", "#d49a16"),
    ("limite_mq_alerta", "Limite de alerta", "#dc2626"),
)


def preparar_historico(leituras: list[dict], fuso: str) -> pd.DataFrame:
    dados = pd.DataFrame(leituras)
    if dados.empty or "criado_em" not in dados:
        return pd.DataFrame()
    dados["criado_em"] = pd.to_datetime(
        dados["criado_em"], utc=True, errors="coerce", format="mixed"
    ).dt.tz_convert(fuso).dt.tz_localize(None)
    dados = dados.dropna(subset=["criado_em"]).sort_values("criado_em")
    for campo in ("temperatura", "umidade", "mq135_adc", *(r[0] for r in REFERENCIAS_MQ)):
        if campo not in dados:
            dados[campo] = float("nan")
        dados[campo] = pd.to_numeric(dados[campo], errors="coerce")
    return dados


def criar_grafico(
    dados: pd.DataFrame,
    campo: str,
    nome: str,
    unidade: str,
    cor: str,
    horas: int,
) -> go.Figure:
    figura = go.Figure()
    # Keep missing samples as gaps instead of connecting failed sensor readings.
    figura.add_trace(
        go.Scatter(
            x=dados["criado_em"],
            y=dados[campo],
            name=nome,
            mode="lines+markers" if dados[campo].count() <= 30 else "lines",
            line={"color": cor, "width": 2.5},
            marker={"size": 5},
            connectgaps=False,
            hovertemplate=f"%{{y:.1f}} {unidade}<extra>{nome}</extra>",
        )
    )
    if campo == "mq135_adc":
        for referencia, legenda, cor_linha in REFERENCIAS_MQ:
            if dados[referencia].notna().any():
                figura.add_trace(
                    go.Scatter(
                        x=dados["criado_em"],
                        y=dados[referencia],
                        name=legenda,
                        mode="lines",
                        line={"color": cor_linha, "width": 1.5, "dash": "dot", "shape": "hv"},
                        connectgaps=False,
                        hovertemplate=f"%{{y:.0f}} ADC<extra>{legenda}</extra>",
                    )
                )

    inicio, fim = dados["criado_em"].min(), dados["criado_em"].max()
    if inicio == fim:
        inicio -= pd.Timedelta(seconds=5)
        fim += pd.Timedelta(seconds=5)
    tem_legenda = campo == "mq135_adc" and len(figura.data) > 1
    figura.update_layout(
        height=320,
        margin={"l": 8, "r": 12, "t": 15, "b": 70 if tem_legenda else 20},
        template="plotly_white",
        hovermode="x unified",
        uirevision=f"{campo}:{horas}",
        showlegend=tem_legenda,
        legend={"orientation": "h", "y": -0.2, "yanchor": "top", "x": 0, "font": {"size": 11}},
        font={"family": "sans-serif", "size": 12, "color": "#334155"},
        xaxis={
            "range": [inicio, fim],
            "tickformat": "%H:%M" if horas <= 6 else "%d/%m<br>%H:%M",
            "hoverformat": "%d/%m/%Y %H:%M:%S",
            "nticks": 6,
            "showgrid": False,
            "title": None,
        },
        yaxis={
            "title": unidade,
            "gridcolor": "#edf1f5",
            "zeroline": False,
            "rangemode": "normal",
            "tickformat": ".0f" if campo == "mq135_adc" else ".1f",
        },
    )
    return figura
