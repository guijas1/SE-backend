"""Operational SmartAir dashboard; all values come from the telemetry API."""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
import streamlit as st

from charts import criar_grafico, preparar_historico


st.set_page_config(
    page_title="SmartAir | Qualidade ambiental",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded",
)

API_URL = os.getenv("SMARTAIR_API_URL", "http://127.0.0.1:8080").rstrip("/")
JANELAS = {"1 hora": 1, "6 horas": 6, "24 horas": 24, "7 dias": 168}
FUSO_HORARIO = "America/Sao_Paulo"
CONFIG_GRAFICO = {"displaylogo": False, "scrollZoom": False}

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.5rem; padding-bottom: 2rem;}
      [data-testid="stMetric"] {
        background: #f7faf9; border: 1px solid #e4ece8;
        border-radius: 14px; padding: 14px 16px;
      }
      [data-testid="stMetricLabel"] p {color: #50645b;}
      div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 14px;}
    </style>
    """,
    unsafe_allow_html=True,
)


def buscar_json(caminho: str):
    resposta = requests.get(f"{API_URL}{caminho}", timeout=4)
    if resposta.status_code == 404:
        return None
    resposta.raise_for_status()
    return resposta.json()


def data_hora(valor: str) -> datetime:
    instante = datetime.fromisoformat(valor)
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante


def mostrar_grafico(dados, campo, nome, unidade, cor, horas):
    valores = dados[campo].dropna()
    if valores.empty:
        st.info("Sem leituras desse sensor no período selecionado.")
        return
    st.plotly_chart(
        criar_grafico(dados, campo, nome, unidade, cor, horas),
        use_container_width=True,
        key=f"grafico_{campo}",
        config=CONFIG_GRAFICO,
    )
    casas = 0 if campo == "mq135_adc" else 1
    st.caption(
        f"Mínima: {valores.min():.{casas}f} {unidade} · "
        f"Média: {valores.mean():.{casas}f} {unidade} · "
        f"Máxima: {valores.max():.{casas}f} {unidade}"
    )


def mostrar_alertas(ultima: dict) -> None:
    sinais = [
        ("erro_dht", "Falha de leitura no sensor DHT22", "error"),
        ("alerta_temperatura", "Temperatura acima do limite configurado", "warning"),
        ("alerta_umidade", "Umidade acima do limite configurado", "warning"),
        ("alerta_qualidade_ar", "Leitura do MQ-135 acima do limite configurado", "warning"),
    ]
    ativos = [(texto, nivel) for campo, texto, nivel in sinais if ultima.get(campo) is True]
    desconhecidos = all(ultima.get(campo) is None for campo, _, _ in sinais)

    st.subheader("Alertas e sensores")
    esquerda, direita = st.columns([1.2, 1])
    with esquerda:
        with st.container(border=True):
            if ativos:
                for texto, nivel in ativos:
                    getattr(st, nivel)(texto)
            elif desconhecidos:
                st.info("O firmware ainda não enviou os estados dos alertas.")
            else:
                st.success("Nenhum alerta ativo na última leitura.")
    with direita:
        with st.container(border=True):
            st.markdown("**Calibração do MQ-135**")
            estado_mq = ultima.get("estado_mq") or "Não informado"
            explicacoes = {
                "AQUECENDO": "Aguardando o aquecimento inicial do sensor.",
                "CALIBRANDO": "Calculando o baseline em ambiente atual.",
                "PRONTO": "Baseline calculado; limites de alerta ativos.",
            }
            st.write(f"Estado: **{estado_mq}**")
            if estado_mq in explicacoes:
                st.caption(explicacoes[estado_mq])

    st.markdown("**Atuadores**")
    led_verde, led_vermelho, buzzer = st.columns(3)
    led_verde.metric("LED verde", estado_atuador(ultima.get("led_verde")))
    led_vermelho.metric("LED vermelho", estado_atuador(ultima.get("led_vermelho")))
    buzzer.metric("Buzzer", estado_atuador(ultima.get("buzzer")))


def estado_atuador(valor: bool | None) -> str:
    if valor is None:
        return "Sem telemetria"
    return "Ligado" if valor else "Desligado"


st.title("🌿 SmartAir")
st.caption("Monitoramento ambiental baseado nas leituras recebidas do ESP32")

with st.sidebar:
    st.markdown("### Painel de monitoramento")
    janela = st.selectbox("Período dos gráficos", list(JANELAS))
    st.caption(f"API: `{API_URL}`")
    st.caption("Atualização automática a cada 5 segundos")


@st.fragment(run_every="5s")
def painel():
    horas = JANELAS[janela]
    try:
        ultima = buscar_json("/api/dados")
        historico = buscar_json(
            f"/api/dados/historico?horas={horas}&limite=5000"
        ) or []
    except requests.RequestException as erro:
        st.error(f"Não foi possível acessar a API: {erro}")
        st.info("Inicie o backend. Se estiver em outro endereço, ajuste SMARTAIR_API_URL.")
        return

    if ultima is None:
        st.warning("Aguardando a primeira leitura enviada pelo ESP32.")
        st.caption("Os indicadores serão preenchidos assim que o primeiro POST válido chegar.")
        return

    instante = data_hora(ultima["criado_em"])
    idade = max(0, int((datetime.now(timezone.utc) - instante).total_seconds()))
    ativo = idade <= 12
    estado_mq = ultima.get("estado_mq") or "Não informado"

    status_col, mq_col, horario_col = st.columns([1, 1, 2])
    status_col.metric("Sistema", "Online" if ativo else "Sem sinal", f"Última leitura há {idade}s")
    mq_col.metric("Sensor MQ-135", estado_mq)
    horario_col.metric("Última atualização", instante.astimezone(ZoneInfo(FUSO_HORARIO)).strftime("%d/%m/%Y às %H:%M:%S"))

    st.markdown("### Condições atuais")
    temp_col, umid_col, mq_col, delta_col = st.columns(4)
    temperatura = ultima.get("temperatura")
    umidade = ultima.get("umidade")
    mq_adc = ultima.get("mq135_adc")
    baseline = ultima.get("baseline_mq135")

    temp_col.metric("Temperatura", f"{temperatura:.1f} °C" if temperatura is not None else "—")
    umid_col.metric("Umidade", f"{umidade:.1f} %" if umidade is not None else "—")
    mq_col.metric("MQ-135 · ADC", str(mq_adc) if mq_adc is not None else "—")
    if mq_adc is not None and baseline is not None:
        delta_col.metric("Variação sobre baseline", f"{mq_adc - baseline:+d} ADC")
    else:
        delta_col.metric("Baseline MQ-135", str(baseline) if baseline is not None else "—")

    if ultima.get("erro_dht") is True:
        st.warning("O DHT22 reportou erro. Temperatura e umidade desta leitura foram removidas para evitar exibir valores antigos como atuais.")

    dados = preparar_historico(historico, FUSO_HORARIO)
    if not dados.empty:

        st.markdown(f"### Tendências · {janela.lower()}")
        st.caption(
            f"{len(dados):,} leituras exibidas · "
            f"{dados['criado_em'].iloc[0]:%d/%m %H:%M} a "
            f"{dados['criado_em'].iloc[-1]:%d/%m %H:%M} · horário de Brasília. "
            "Até 5.000 leituras por consulta."
        )
        graf_temp, graf_umid = st.columns(2, gap="medium")
        with graf_temp:
            with st.container(border=True):
                st.markdown("**Temperatura**")
                st.caption("Variação das leituras do DHT22 em °C")
                mostrar_grafico(dados, "temperatura", "Temperatura", "°C", "#e76f51", horas)
        with graf_umid:
            with st.container(border=True):
                st.markdown("**Umidade relativa**")
                st.caption("Variação das leituras do DHT22 em %")
                mostrar_grafico(dados, "umidade", "Umidade", "%", "#2878b5", horas)
        with st.container(border=True):
            st.markdown("**MQ-135 · sinal e calibração**")
            st.caption("ADC de 0 a 4095. As referências acompanham os valores enviados em cada leitura.")
            mostrar_grafico(dados, "mq135_adc", "MQ-135", "ADC", "#159570", horas)

        total = len(dados)
        leituras_alerta = int((dados["alerta_geral"] == 1).sum())
        temperaturas_validas = dados["temperatura"].dropna()
        umidades_validas = dados["umidade"].dropna()
        estatisticas = st.columns(5)
        estatisticas[0].metric("Amostras exibidas", f"{total:,}".replace(",", "."))
        estatisticas[1].metric(
            "Temperatura média",
            f"{temperaturas_validas.mean():.1f} °C" if not temperaturas_validas.empty else "—",
        )
        estatisticas[2].metric(
            "Umidade média",
            f"{umidades_validas.mean():.1f} %" if not umidades_validas.empty else "—",
        )
        estatisticas[3].metric("Amostras em alerta", f"{leituras_alerta:,}".replace(",", "."))
        estatisticas[4].metric(
            "Leituras DHT válidas",
            f"{len(temperaturas_validas)}/{total}",
        )

        mostrar_alertas(ultima)

        with st.expander("Tabela de telemetria recebida"):
            tabela = dados.sort_values("criado_em", ascending=False).copy()
            tabela["criado_em"] = tabela["criado_em"].dt.strftime("%d/%m/%Y %H:%M:%S")
            colunas = [
                "criado_em", "temperatura", "umidade", "mq135_adc", "baseline_mq135",
                "estado_mq", "alerta_temperatura", "alerta_umidade",
                "alerta_qualidade_ar", "erro_dht", "alerta_geral",
            ]
            disponiveis = [coluna for coluna in colunas if coluna in tabela]
            tabela = tabela[disponiveis].rename(
                columns={
                    "criado_em": "Horário",
                    "temperatura": "Temperatura °C",
                    "umidade": "Umidade %",
                    "mq135_adc": "MQ-135 ADC",
                    "baseline_mq135": "Baseline ADC",
                    "estado_mq": "Calibração MQ-135",
                    "alerta_temperatura": "Alerta temperatura",
                    "alerta_umidade": "Alerta umidade",
                    "alerta_qualidade_ar": "Alerta MQ-135",
                    "erro_dht": "Erro DHT",
                    "alerta_geral": "Alerta geral",
                }
            )
            st.dataframe(tabela, use_container_width=True, hide_index=True)
        st.caption("O MQ-135 é exibido em contagens ADC comparadas ao baseline. O projeto ainda não converte esse sinal em ppm ou índice AQI calibrado.")
    else:
        st.info("A leitura atual chegou, mas ainda não há histórico dentro do período escolhido.")


painel()
