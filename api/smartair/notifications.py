"""Persistent status transitions and delivery to a Power Automate HTTP flow."""

import asyncio
import html
import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4
from zoneinfo import ZoneInfo

from smartair import database


logger = logging.getLogger(__name__)
SINAIS = {
    "alerta_geral": ("Alerta geral ativado", "Sistema voltou ao normal"),
    "alerta_temperatura": ("Alerta de temperatura ativado", "Alerta de temperatura encerrado"),
    "alerta_umidade": ("Alerta de umidade ativado", "Alerta de umidade encerrado"),
    "alerta_qualidade_ar": ("Alerta de qualidade do ar ativado", "Alerta de qualidade do ar encerrado"),
    "erro_dht": ("Falha no sensor DHT22", "Sensor DHT22 recuperado"),
    "buzzer_alerta": ("Alerta sonoro ativado", "Alerta sonoro encerrado"),
    "ventilacao_ligada": ("Ventilação ligada", "Ventilação desligada"),
    "rele_ligado": ("Relé ligado", "Relé desligado"),
    "rele_habilitado": ("Relé habilitado", "Relé desabilitado"),
}
ALERTAS = frozenset({
    "alerta_geral", "alerta_temperatura", "alerta_umidade", "alerta_qualidade_ar",
    "erro_dht", "buzzer_alerta", "buzzer",
})


@dataclass(frozen=True)
class NotificationConfig:
    webhook_url: str = ""
    device_name: str = "SmartAir ESP32"
    offline_after_seconds: int = 12
    check_interval_seconds: int = 2
    request_timeout_seconds: int = 10
    summary_interval_seconds: int = 0
    alert_cooldown_seconds: int = 300
    timezone_name: str = "America/Sao_Paulo"

    def __post_init__(self):
        if self.webhook_url:
            url = urlsplit(self.webhook_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment:
                raise ValueError("SMARTAIR_POWER_AUTOMATE_URL deve ser uma URL HTTPS válida")
        for field in ("offline_after_seconds", "check_interval_seconds", "request_timeout_seconds"):
            if getattr(self, field) < 1:
                raise ValueError(f"{field} deve ser maior que zero")
        if self.summary_interval_seconds < 0:
            raise ValueError("summary_interval_seconds não pode ser negativo")
        if self.alert_cooldown_seconds < 0:
            raise ValueError("alert_cooldown_seconds não pode ser negativo")
        ZoneInfo(self.timezone_name)

    @property
    def enabled(self) -> bool:
        return bool(self.webhook_url)

    @classmethod
    def from_env(cls):
        return cls(
            webhook_url=os.getenv("SMARTAIR_POWER_AUTOMATE_URL", "").strip(),
            device_name=os.getenv("SMARTAIR_DEVICE_NAME", "SmartAir ESP32"),
            offline_after_seconds=int(os.getenv("SMARTAIR_OFFLINE_AFTER_SECONDS", "12")),
            check_interval_seconds=int(os.getenv("SMARTAIR_NOTIFICATION_CHECK_SECONDS", "2")),
            request_timeout_seconds=int(os.getenv("SMARTAIR_NOTIFICATION_TIMEOUT_SECONDS", "10")),
            summary_interval_seconds=int(os.getenv("SMARTAIR_SUMMARY_INTERVAL_SECONDS", "0")),
            alert_cooldown_seconds=int(os.getenv("SMARTAIR_ALERT_COOLDOWN_SECONDS", "300")),
            timezone_name=os.getenv("SMARTAIR_NOTIFICATION_TIMEZONE", "America/Sao_Paulo"),
        )


def instante(valor: str) -> datetime:
    data = datetime.fromisoformat(valor)
    return data.replace(tzinfo=timezone.utc) if data.tzinfo is None else data


def carregar_estado(banco: sqlite3.Connection) -> dict | None:
    row = banco.execute("SELECT dados FROM notificacao_estado WHERE id = 1").fetchone()
    return json.loads(row["dados"]) if row else None


def salvar_estado(banco: sqlite3.Connection, estado: dict) -> None:
    banco.execute(
        "INSERT OR REPLACE INTO notificacao_estado (id, dados) VALUES (1, ?)",
        (json.dumps(estado, ensure_ascii=False),),
    )


class SemRedirecionamento(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NotificationService:
    def __init__(self, config: NotificationConfig):
        self.config = config

    def registrar_leitura(self, payload: dict, criado_em: str) -> int:
        if not self.config.enabled:
            return database.salvar(payload, criado_em)
        agora = instante(criado_em)
        with database.conectar() as banco:
            # Serialize telemetry, state changes and the offline monitor across workers.
            banco.execute("BEGIN IMMEDIATE")
            leitura_id = database.inserir_leitura(banco, payload, criado_em)
            leitura = {**payload, "id": leitura_id, "criado_em": criado_em}
            self._observar_leitura(banco, carregar_estado(banco), leitura, agora)
            return leitura_id

    def _observar_leitura(self, banco, estado, leitura, agora):
        mudancas = []
        if estado is None:
            estado = {"online": False, "sinais": {}, "ultimo_resumo": agora.timestamp()}
        elif estado["online"] and self._offline(estado["leitura"], agora):
            # Detect gaps even if the monitor was stopped or busy delivering a webhook.
            self._marcar_offline(banco, estado, agora)
        if not estado["online"]:
            mudancas.append({"campo": "conexao", "anterior": None if "leitura" not in estado else "offline", "atual": "online", "descricao": "Dispositivo online"})
        anteriores = estado["sinais"]
        for campo, mensagens in SINAIS.items():
            atual = leitura.get(campo)
            anterior = anteriores.get(campo)
            if atual is not None:
                if atual != anterior and (anterior is not None or atual is True):
                    mudancas.append({"campo": campo, "anterior": anterior, "atual": atual, "descricao": mensagens[0 if atual else 1]})
                anteriores[campo] = atual
        # Without the mode field, report observed sound once until an explicit return
        # to normal. Pauses between beeps must not generate repeated emails.
        if leitura.get("buzzer_alerta") is None and leitura.get("buzzer") is True and not estado.get("som_notificado"):
            mudancas.append({"campo": "buzzer", "anterior": None, "atual": True, "descricao": "Som do buzzer detectado na amostra"})
            estado["som_notificado"] = True
        if leitura.get("buzzer_alerta") is not None:
            estado["som_notificado"] = leitura["buzzer_alerta"]
        elif leitura.get("alerta_geral") is False and leitura.get("buzzer") is False:
            estado["som_notificado"] = False
        for campo, nome in (("estado_mq", "MQ-135"), ("estado_sistema", "Sistema"), ("motivos_alerta", "Motivos do alerta")):
            atual = leitura.get(campo)
            anterior = anteriores.get(campo)
            if atual is not None:
                if atual != anterior and (anterior is not None or (campo == "motivos_alerta" and atual)):
                    texto = ("; ".join(atual) or "Nenhum") if isinstance(atual, list) else atual
                    mudancas.append({"campo": campo, "anterior": anterior, "atual": atual, "descricao": f"{nome}: {texto}"})
                anteriores[campo] = atual
        estado.update(online=True, leitura=leitura)
        if mudancas:
            self._enfileirar(banco, estado, agora, "status_alterado", mudancas)
        salvar_estado(banco, estado)
        return estado

    def _offline(self, leitura: dict, agora: datetime) -> bool:
        return (agora - instante(leitura["criado_em"])).total_seconds() > self.config.offline_after_seconds

    def _marcar_offline(self, banco, estado, agora):
        estado["online"] = False
        self._enfileirar(banco, estado, agora, "dispositivo_offline", [{
            "campo": "conexao", "anterior": "online", "atual": "offline",
            "descricao": f"Dispositivo offline: sem leituras há mais de {self.config.offline_after_seconds} segundos",
        }])

    def verificar_status(self, agora: datetime) -> None:
        if not self.config.enabled:
            return
        with database.conectar() as banco:
            banco.execute("BEGIN IMMEDIATE")
            estado = carregar_estado(banco)
            row = banco.execute("SELECT * FROM leituras ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return  # No device has been observed yet.
            leitura = database._formatar(row)
            if estado is None:
                online = not self._offline(leitura, agora)
                estado = {"online": online, "leitura": leitura, "sinais": {
                    campo: leitura[campo] for campo in (*SINAIS, "estado_mq", "estado_sistema", "motivos_alerta")
                    if leitura.get(campo) is not None
                }, "ultimo_resumo": agora.timestamp()}
                self._enfileirar(banco, estado, agora, "estado_inicial", [{
                    "campo": "conexao", "anterior": None, "atual": "online" if online else "offline",
                    "descricao": "Monitoramento iniciado: dispositivo " + ("online" if online else "offline"),
                }])
            elif leitura["id"] != estado["leitura"]["id"]:
                # Reconcile readings received while notifications were disabled.
                estado = self._observar_leitura(banco, estado, leitura, instante(leitura["criado_em"]))
            if estado["online"] and self._offline(estado["leitura"], agora):
                self._marcar_offline(banco, estado, agora)
            intervalo = self.config.summary_interval_seconds
            if intervalo and agora.timestamp() - estado["ultimo_resumo"] >= intervalo:
                self._enfileirar(banco, estado, agora, "resumo_periodico", [])
                estado["ultimo_resumo"] = agora.timestamp()
            salvar_estado(banco, estado)

    def _enfileirar(self, banco, estado, agora, tipo, mudancas):
        leitura = estado["leitura"]
        conexao = "online" if estado["online"] else "offline"
        descricoes = [mudanca["descricao"] for mudanca in mudancas]
        titulo = "; ".join(descricoes) if descricoes else "Resumo periódico"
        assunto = f"[SmartAir] {self.config.device_name}: {titulo}"[:250]
        local = ZoneInfo(self.config.timezone_name)
        horario = agora.astimezone(local).strftime("%d/%m/%Y %H:%M:%S %Z")
        ultima = instante(leitura["criado_em"]).astimezone(local).strftime("%d/%m/%Y %H:%M:%S %Z")
        linhas = [f"Dispositivo: {self.config.device_name}", f"Evento: {horario}", f"Conexão: {conexao}", f"Última leitura: {ultima}", *descricoes]
        for campo, nome, unidade in (
            ("temperatura", "Temperatura", " °C"), ("umidade", "Umidade", " %"),
            ("mq135_adc", "MQ-135", " ADC"), ("estado_sistema", "Estado do sistema", ""),
            ("estado_mq", "Estado do MQ-135", ""),
        ):
            valor = leitura.get(campo)
            linhas.append(f"{nome}: {valor}{unidade}" if valor is not None else f"{nome}: não informado")
        for campo, nome in (
            ("alerta_geral", "Alerta geral"), ("alerta_temperatura", "Alerta de temperatura"),
            ("alerta_umidade", "Alerta de umidade"), ("alerta_qualidade_ar", "Alerta de qualidade do ar"),
            ("erro_dht", "Falha no DHT22"), ("buzzer_alerta", "Modo de alerta sonoro"),
            ("buzzer", "Som do buzzer na amostra"), ("led_verde", "LED verde"), ("led_vermelho", "LED vermelho"),
            ("ventilacao_ligada", "Ventilação"),
            ("rele_ligado", "Relé ligado"), ("rele_habilitado", "Relé habilitado"),
        ):
            valor = leitura.get(campo)
            linhas.append(f"{nome}: " + ("não informado" if valor is None else ("ativo" if valor else "inativo")))
        motivos = leitura.get("motivos_alerta")
        linhas.append("Motivos: " + ("não informados" if motivos is None else ("; ".join(motivos) or "Nenhum")))
        if conexao == "offline":
            linhas.append("As leituras e os estados acima são os últimos recebidos; não representam uma medição atual.")
        evento_id = str(uuid4())
        payload = {
            "evento_id": evento_id, "tipo": tipo, "dispositivo": self.config.device_name,
            "ocorrido_em": agora.isoformat(timespec="seconds"), "conexao": conexao,
            "assunto": assunto, "mensagem": "\n".join(linhas),
            "corpo_html": "<p>" + "<br>".join(html.escape(linha) for linha in linhas) + "</p>",
            "mudancas": mudancas, "leitura": leitura,
        }
        banco.execute("INSERT INTO notificacoes (id, payload, criado_em) VALUES (?, ?, ?)",
                      (evento_id, json.dumps(payload, ensure_ascii=False), payload["ocorrido_em"]))

    @staticmethod
    def _alertas_ativos(payload: str) -> set[str]:
        evento = json.loads(payload)
        if evento.get("conexao") != "online":
            return set()
        leitura = evento.get("leitura", {})
        campos = {campo for campo in ALERTAS if leitura.get(campo) is True}
        if leitura.get("buzzer_alerta") is not None:
            campos.discard("buzzer")  # Beep pulses do not constitute a new alert type.
        return campos

    def _reservar(self, agora: datetime) -> dict | None:
        with database.conectar() as banco:
            banco.execute("BEGIN IMMEDIATE")
            row = banco.execute(
                "SELECT * FROM notificacoes WHERE status IN ('pendente', 'enviando') ORDER BY rowid LIMIT 1"
            ).fetchone()
            if row is None or row["proxima_tentativa"] > agora.timestamp() or row["lease_ate"] > agora.timestamp():
                return None
            item = dict(row)
            alertas = self._alertas_ativos(item["payload"])
            intervalo = self.config.alert_cooldown_seconds
            if alertas and intervalo:
                limite = agora.timestamp() - intervalo
                recentes = {
                    salvo["campo"] for salvo in banco.execute(
                        "SELECT campo FROM notificacao_alertas_enviados WHERE enviado_em > ?",
                        (limite,),
                    )
                }
                if not alertas.issubset(recentes):
                    # Honor events accepted before the cooldown table existed.
                    enviados = banco.execute(
                        "SELECT payload, enviado_em FROM notificacoes WHERE status = 'enviado' AND enviado_em >= ?",
                        (datetime.fromtimestamp(limite, timezone.utc).isoformat(),),
                    ).fetchall()
                    for enviado in enviados:
                        timestamp = instante(enviado["enviado_em"]).timestamp()
                        if timestamp <= limite:
                            continue
                        for campo in self._alertas_ativos(enviado["payload"]):
                            recentes.add(campo)
                            banco.execute(
                                """INSERT INTO notificacao_alertas_enviados (campo, enviado_em) VALUES (?, ?)
                                   ON CONFLICT(campo) DO UPDATE SET enviado_em = max(enviado_em, excluded.enviado_em)""",
                                (campo, timestamp),
                            )
                if alertas.issubset(recentes):
                    banco.execute(
                        """UPDATE notificacoes SET status = 'suprimido', ultimo_erro = NULL,
                           lease_ate = 0, lease_token = NULL WHERE id = ?""",
                        (item["id"],),
                    )
                    logger.info("Evento %s suprimido pelo intervalo de repetição de alertas", item["id"])
                    return None
            item["lease_token"] = str(uuid4())
            item["tentativas"] += 1
            banco.execute(
                "UPDATE notificacoes SET status = 'enviando', lease_token = ?, lease_ate = ?, tentativas = ? WHERE id = ?",
                (item["lease_token"], agora.timestamp() + self.config.request_timeout_seconds + 30, item["tentativas"], item["id"]),
            )
            return item

    def enviar_pendente(self, agora: datetime) -> bool:
        if not self.config.enabled:
            return False
        item = self._reservar(agora)
        if item is None:
            return False
        erro = None
        try:
            request = Request(self.config.webhook_url, data=item["payload"].encode("utf-8"),
                              headers={"Content-Type": "application/json; charset=utf-8", "Idempotency-Key": item["id"]}, method="POST")
            with build_opener(SemRedirecionamento()).open(request, timeout=self.config.request_timeout_seconds) as resposta:
                if not 200 <= resposta.status < 300:
                    erro = f"HTTP {resposta.status}"
        except HTTPError as exc:
            erro = f"HTTP {exc.code}"
            exc.close()
        except (URLError, OSError, ValueError):
            erro = "Falha de conexão ou timeout"
        concluido = datetime.now(timezone.utc)
        with database.conectar() as banco:
            if erro:
                atraso = min(300, 5 * 2 ** min(item["tentativas"] - 1, 6))
                banco.execute(
                    "UPDATE notificacoes SET status = 'pendente', ultimo_erro = ?, proxima_tentativa = ?, lease_ate = 0, lease_token = NULL WHERE id = ? AND lease_token = ?",
                    (erro, concluido.timestamp() + atraso, item["id"], item["lease_token"]),
                )
                logger.warning("Power Automate: evento %s pendente (%s); nova tentativa em %ss", item["id"], erro, atraso)
            else:
                atualizado = banco.execute(
                    "UPDATE notificacoes SET status = 'enviado', enviado_em = ?, ultimo_erro = NULL, lease_ate = 0, lease_token = NULL WHERE id = ? AND lease_token = ?",
                    (concluido.isoformat(timespec="seconds"), item["id"], item["lease_token"]),
                )
                if atualizado.rowcount:
                    for campo in self._alertas_ativos(item["payload"]):
                        banco.execute(
                            """INSERT INTO notificacao_alertas_enviados (campo, enviado_em) VALUES (?, ?)
                               ON CONFLICT(campo) DO UPDATE SET enviado_em = excluded.enviado_em""",
                            (campo, concluido.timestamp()),
                        )
        return True

    def status(self) -> dict:
        leitura = database.mais_recente()
        agora = datetime.now(timezone.utc)
        conexao = "aguardando" if leitura is None else ("offline" if self._offline(leitura, agora) else "online")
        with database.conectar() as banco:
            contagens = {row["status"]: row["total"] for row in banco.execute("SELECT status, count(*) AS total FROM notificacoes GROUP BY status")}
            ultimo = banco.execute("SELECT max(enviado_em) FROM notificacoes").fetchone()[0]
            falha = banco.execute("SELECT ultimo_erro FROM notificacoes WHERE ultimo_erro IS NOT NULL ORDER BY rowid DESC LIMIT 1").fetchone()
        return {"habilitado": self.config.enabled, "dispositivo": self.config.device_name, "conexao": conexao,
                "ultima_leitura_em": leitura["criado_em"] if leitura else None,
                "offline_apos_segundos": self.config.offline_after_seconds,
                "resumo_intervalo_segundos": self.config.summary_interval_seconds,
                "alerta_intervalo_minimo_segundos": self.config.alert_cooldown_seconds,
                "pendentes": contagens.get("pendente", 0), "em_envio": contagens.get("enviando", 0),
                "suprimidos": contagens.get("suprimido", 0),
                "enviados": contagens.get("enviado", 0), "ultimo_envio_em": ultimo,
                "ultimo_erro": falha[0] if falha else None}

    def _ciclo(self):
        self.verificar_status(datetime.now(timezone.utc))
        self.enviar_pendente(datetime.now(timezone.utc))

    async def executar(self, parar: asyncio.Event):
        while not parar.is_set():
            try:
                await asyncio.to_thread(self._ciclo)
            except Exception as exc:
                # Only the type is logged: exception strings can contain the secret URL.
                logger.error("Falha no monitor de notificações (%s)", type(exc).__name__)
            try:
                await asyncio.wait_for(parar.wait(), timeout=self.config.check_interval_seconds)
            except asyncio.TimeoutError:
                pass
