"""Notification behavior using a temporary database and a mocked HTTP endpoint."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from smartair import database
from smartair.notifications import NotificationConfig, NotificationService
from smartair.schemas import TelemetryInput, alerta_geral


class NotificationsTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "smartair.db"
        self.path_patch = patch.object(database, "DATABASE_PATH", self.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        database.inicializar()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.config = NotificationConfig(webhook_url="https://example.invalid/flow?sig=secret")
        self.service = NotificationService(self.config)

    def record(self, seconds=0, service=None, **values):
        leitura = TelemetryInput.model_validate({"temperatura": 24, "umidade": 65, **values})
        payload = leitura.model_dump()
        payload["alerta_geral"] = alerta_geral(leitura)
        return (service or self.service).registrar_leitura(payload, (self.now + timedelta(seconds=seconds)).isoformat())

    def events(self):
        with database.conectar() as banco:
            return [json.loads(row["payload"]) for row in banco.execute("SELECT payload FROM notificacoes ORDER BY rowid")]

    def row(self):
        with database.conectar() as banco:
            return dict(banco.execute("SELECT * FROM notificacoes ORDER BY rowid LIMIT 1").fetchone())

    def successful_endpoint(self):
        response = MagicMock()
        response.__enter__.return_value.status = 202
        opener = MagicMock()
        opener.open.return_value = response
        return opener

    def test_disabled_saves_without_notifications(self):
        self.record(service=NotificationService(NotificationConfig()), alerta=True)
        self.assertEqual(self.events(), [])
        self.assertTrue(database.mais_recente()["alerta_geral"])

    def test_ventilation_aliases_preserve_boolean_and_unknown_values(self):
        self.record(ventilacaoLigada=False)
        self.assertIs(database.mais_recente()["ventilacao_ligada"], False)
        self.record(1, ventilacao_ligada=True)
        self.assertIs(database.mais_recente()["ventilacao_ligada"], True)
        self.record(2)
        self.assertIsNone(database.mais_recente()["ventilacao_ligada"])
        self.assertEqual([row["ventilacao_ligada"] for row in database.historico(1, 10)], [None, True, False])

    def test_ventilation_changes_notify_without_activating_alert(self):
        self.record(estadoSistema="NORMAL", ventilacaoLigada=False)
        self.record(1, estadoSistema="NORMAL", ventilacaoLigada=True)
        self.record(2, estadoSistema="NORMAL")
        self.record(3, estadoSistema="NORMAL", ventilacaoLigada=True)
        self.assertEqual(len(self.events()), 2)
        event = self.events()[-1]
        self.assertEqual(event["mudancas"], [{
            "campo": "ventilacao_ligada", "anterior": False,
            "atual": True, "descricao": "Ventilação ligada",
        }])
        self.assertIs(event["leitura"]["ventilacao_ligada"], True)
        self.assertIs(event["leitura"]["alerta_geral"], False)
        self.record(4, estadoSistema="NORMAL", ventilacaoLigada=False)
        self.assertIn("Ventilação desligada", self.events()[-1]["mensagem"])

    def test_relay_states_are_independent_and_do_not_activate_alert(self):
        self.record(alerta=False, releLigado=False, releHabilitado=True, ventilacaoLigada=False)
        reading = database.mais_recente()
        self.assertIs(reading["rele_ligado"], False)
        self.assertIs(reading["rele_habilitado"], True)
        self.record(1, alerta=False, releLigado=True, releHabilitado=True, ventilacaoLigada=False)
        event = self.events()[-1]
        self.assertEqual([change["campo"] for change in event["mudancas"]], ["rele_ligado"])
        self.assertIs(event["leitura"]["rele_ligado"], True)
        self.assertIs(event["leitura"]["ventilacao_ligada"], False)
        self.assertIs(event["leitura"]["alerta_geral"], False)
        self.record(2, alerta=False, releLigado=False, releHabilitado=False)
        self.assertEqual({change["campo"] for change in self.events()[-1]["mudancas"]}, {"rele_ligado", "rele_habilitado"})
        self.record(3, alerta=False)
        self.assertIsNone(database.mais_recente()["rele_ligado"])
        self.assertIsNone(database.mais_recente()["rele_habilitado"])
        self.record(4, alerta=False, rele_ligado=False, rele_habilitado=False)
        self.assertEqual(len(self.events()), 3)

    def test_extended_firmware_payload_and_alert_mode_through_api(self):
        from fastapi.testclient import TestClient
        from smartair.main import app

        async def idle(service, stop):
            await stop.wait()

        sample_path = Path(__file__).resolve().parents[1] / "examples/telemetria-firmware-v2.json"
        sample = json.loads(sample_path.read_text())
        expected = {
            "led_verde": False, "led_vermelho": True, "buzzer": True,
            "buzzer_alerta": True, "rele_ligado": True, "rele_habilitado": True,
            "ventilacao_ligada": True, "estado_mq": "PRONTO",
        }
        with patch.dict(os.environ, {"SMARTAIR_POWER_AUTOMATE_URL": self.config.webhook_url}), patch.object(NotificationService, "executar", idle):
            with TestClient(app) as client:
                self.assertEqual(client.post("/api/dados", json=sample).json(), {"status": "ok", "id": 1})
                reading = client.get("/api/dados").json()
                for field, value in expected.items():
                    self.assertEqual(reading[field], value)
                    self.assertEqual(self.events()[0]["leitura"][field], value)
                self.assertTrue(reading["alerta_geral"])
                self.assertFalse(reading["alerta_qualidade_ar"])
                self.assertIsNone(reading["estado_sistema"])
                self.assertIsNone(reading["motivos_alerta"])
                self.assertIn("buzzer_alerta", [change["campo"] for change in self.events()[0]["mudancas"]])
                self.assertEqual(client.post("/api/dados", json={**sample, "buzzerLigado": False}).status_code, 200)
                self.assertEqual(len(self.events()), 1)
                self.assertFalse(client.get("/api/dados").json()["buzzer"])
                self.assertTrue(client.get("/api/dados").json()["buzzer_alerta"])
                history = client.get("/api/dados/historico").json()
                self.assertEqual(len(history), 2)
                self.assertIs(history[0]["rele_ligado"], True)
                self.assertIs(history[0]["rele_habilitado"], True)

    def test_no_device_does_not_report_offline(self):
        self.service.verificar_status(self.now)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.service.status()["conexao"], "aguardando")

    def test_first_online_and_repeated_readings(self):
        for seconds in range(4):
            self.record(seconds, estadoSistema="NORMAL", buzzerAlerta=False)
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(self.events()[0]["conexao"], "online")
        self.assertIsNone(self.events()[0]["mudancas"][0]["anterior"])
        self.assertEqual(len(database.historico(1, 100)), 4)

    def test_alert_changes_grouped_with_recovery(self):
        self.record(estadoSistema="NORMAL", alertaTemperatura=False, buzzerAlerta=False)
        self.record(1, estadoSistema="ALERTA", alertaTemperatura=True, buzzerAlerta=True, motivosAlerta=["TEMPERATURA ALTA"])
        self.record(2, estadoSistema="ALERTA", alertaTemperatura=True, buzzerAlerta=True, motivosAlerta=["TEMPERATURA ALTA"])
        self.record(3, estadoSistema="NORMAL", alertaTemperatura=False, buzzerAlerta=False, motivosAlerta=[])
        events = self.events()
        self.assertEqual(len(events), 3)
        self.assertIn("Alerta de temperatura ativado", events[1]["mensagem"])
        self.assertIn("Alerta sonoro ativado", events[1]["mensagem"])
        self.assertIn("Sistema voltou ao normal", events[2]["mensagem"])

    def test_unknown_does_not_clear_known_alert(self):
        self.record(alertaTemperatura=True)
        self.record(1)
        self.record(2, alertaTemperatura=True)
        self.assertEqual(len(self.events()), 1)
        self.record(3, alertaTemperatura=False)
        self.assertIn("Alerta de temperatura encerrado", self.events()[-1]["mensagem"])

    def test_sound_mode_ignores_beep_pauses(self):
        for seconds in range(4):
            self.record(seconds, buzzerAlerta=True, buzzerEmitindoSom=seconds % 2 == 0)
        self.assertEqual(len(self.events()), 1)

    def test_legacy_sound_detected_once_until_explicit_normal(self):
        self.record(buzzer=True)
        self.record(1, buzzer=False)
        self.record(2, buzzer=True)
        self.assertEqual(len(self.events()), 1)
        self.assertIn("Som do buzzer detectado", self.events()[0]["mensagem"])
        self.record(3, buzzer=False, alerta=False)
        self.record(4, buzzer=True, alerta=True)
        self.assertIn("Som do buzzer detectado", self.events()[-1]["mensagem"])

    def test_offline_once_and_reconnect(self):
        self.record()
        self.service.verificar_status(self.now + timedelta(seconds=12))
        self.assertEqual(len(self.events()), 1)
        self.service.verificar_status(self.now + timedelta(seconds=13))
        self.service.verificar_status(self.now + timedelta(seconds=14))
        self.assertEqual(len(self.events()), 2)
        self.assertEqual(self.events()[1]["tipo"], "dispositivo_offline")
        self.assertIn("não representam uma medição atual", self.events()[1]["mensagem"])
        self.record(15)
        self.assertEqual(self.events()[-1]["conexao"], "online")

    def test_gap_detected_without_monitor_tick(self):
        self.record()
        self.record(20)
        self.assertEqual([item["conexao"] for item in self.events()], ["online", "offline", "online"])

    def test_restart_preserves_transition_state(self):
        self.record(estadoSistema="ALERTA", buzzerAlerta=True)
        restarted = NotificationService(self.config)
        restarted.verificar_status(self.now + timedelta(seconds=1))
        self.record(2, service=restarted, estadoSistema="ALERTA", buzzerAlerta=True)
        self.assertEqual(len(self.events()), 1)

    def test_enable_existing_and_reconcile_disabled_period(self):
        disabled = NotificationService(NotificationConfig())
        self.record(service=disabled, estadoSistema="NORMAL")
        self.service.verificar_status(self.now)
        self.assertEqual(self.events()[0]["tipo"], "estado_inicial")
        self.record(1, service=disabled, estadoSistema="ALERTA")
        self.service.verificar_status(self.now + timedelta(seconds=2))
        self.assertIn("Alerta geral ativado", self.events()[-1]["mensagem"])
        self.assertEqual(self.events()[-1]["leitura"]["id"], 2)

    def test_sensor_error_uses_null_values_and_reports_recovery(self):
        self.record(erroDHT=True)
        self.assertIsNone(self.events()[0]["leitura"]["temperatura"])
        self.assertIn("Temperatura: não informado", self.events()[0]["mensagem"])
        self.record(1, erroDHT=False)
        self.assertIn("Sensor DHT22 recuperado", self.events()[-1]["mensagem"])

    def test_email_html_escapes_firmware_text(self):
        self.record(motivosAlerta=["<script>alert('x')</script>"])
        self.assertNotIn("<script>", self.events()[0]["corpo_html"])
        self.assertIn("&lt;script&gt;", self.events()[0]["corpo_html"])

    def test_optional_summary_survives_restart(self):
        service = NotificationService(NotificationConfig(webhook_url=self.config.webhook_url, summary_interval_seconds=60))
        self.record(service=service)
        restarted = NotificationService(service.config)
        restarted.verificar_status(self.now + timedelta(seconds=59))
        self.assertNotIn("resumo_periodico", [item["tipo"] for item in self.events()])
        restarted.verificar_status(self.now + timedelta(seconds=60))
        restarted.verificar_status(self.now + timedelta(seconds=61))
        self.assertEqual([item["tipo"] for item in self.events()].count("resumo_periodico"), 1)

    def test_reading_and_event_rollback_together(self):
        with patch.object(self.service, "_enfileirar", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                self.record()
        self.assertIsNone(database.mais_recente())
        self.assertEqual(self.events(), [])

    def test_concurrent_readings_emit_one_transition(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: self.record(estadoSistema="NORMAL"), range(8)))
        self.assertEqual(len(self.events()), 1)
        self.assertEqual(len(database.historico(1, 100)), 8)

    def test_success_posts_json_and_acknowledges_once(self):
        self.record()
        response = MagicMock()
        response.__enter__.return_value.status = 202
        opener = MagicMock()
        opener.open.return_value = response
        with patch("smartair.notifications.build_opener", return_value=opener):
            self.assertTrue(self.service.enviar_pendente(self.now))
            self.assertFalse(self.service.enviar_pendente(self.now))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), self.events()[0])
        self.assertEqual(request.get_header("Idempotency-key"), self.events()[0]["evento_id"])
        self.assertEqual(self.row()["status"], "enviado")
        self.assertEqual(self.service.status()["enviados"], 1)
        self.assertNotIn("secret", json.dumps(self.service.status()))

    def test_failure_persists_retries_and_fifo(self):
        self.record()
        self.record(1, estadoSistema="ALERTA")
        opener = MagicMock()
        opener.open.side_effect = HTTPError(self.config.webhook_url, 503, "unavailable", {}, None)
        with patch("smartair.notifications.build_opener", return_value=opener):
            self.service.enviar_pendente(self.now)
            self.assertFalse(NotificationService(self.config).enviar_pendente(self.now))
            first = self.row()
            later = datetime.fromtimestamp(first["proxima_tentativa"] + 1, timezone.utc)
            NotificationService(self.config).enviar_pendente(later)
        self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(self.row()["tentativas"], 2)
        self.assertEqual(self.row()["status"], "pendente")
        self.assertEqual(self.service.status()["ultimo_erro"], "HTTP 503")

    def test_alert_cooldown_suppresses_repeats_and_preserves_recovery(self):
        opener = self.successful_endpoint()
        with patch("smartair.notifications.build_opener", return_value=opener):
            self.record(alertaTemperatura=True)
            self.assertTrue(self.service.enviar_pendente(self.now))
            self.record(1, alerta=False, alertaTemperatura=False)
            self.assertTrue(self.service.enviar_pendente(self.now + timedelta(seconds=1)))
            self.record(2, alertaTemperatura=True)
            restarted = NotificationService(self.config)
            self.assertFalse(restarted.enviar_pendente(self.now + timedelta(seconds=2)))
            self.assertEqual(restarted.status()["suprimidos"], 1)
            self.record(3, alerta=False, alertaTemperatura=False)
            self.assertTrue(restarted.enviar_pendente(self.now + timedelta(seconds=3)))
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual(len(database.historico(1, 100)), 4)
        self.assertEqual(self.service.status()["pendentes"], 0)
        self.assertEqual(self.service.status()["alerta_intervalo_minimo_segundos"], 300)

    def test_alert_cooldown_allows_a_different_alert_immediately(self):
        opener = self.successful_endpoint()
        with patch("smartair.notifications.build_opener", return_value=opener):
            self.record(alertaTemperatura=True)
            self.service.enviar_pendente(self.now)
            self.record(1, alertaTemperatura=True, alertaQualidadeAr=True)
            self.assertTrue(self.service.enviar_pendente(self.now + timedelta(seconds=1)))
        self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(self.service.status()["suprimidos"], 0)

    def test_alert_cooldown_expires_at_the_configured_limit(self):
        opener = self.successful_endpoint()
        with patch("smartair.notifications.build_opener", return_value=opener):
            self.record(alerta=True)
            self.service.enviar_pendente(self.now)
            self.record(1, alerta=False)
            self.service.enviar_pendente(self.now + timedelta(seconds=1))
            self.record(2, alerta=True)
            with database.conectar() as banco:
                timestamp = banco.execute("SELECT enviado_em FROM notificacao_alertas_enviados WHERE campo = 'alerta_geral'").fetchone()[0]
            after_hold = datetime.fromtimestamp(timestamp + 300, timezone.utc)
            self.assertTrue(self.service.enviar_pendente(after_hold))
        self.assertEqual(opener.open.call_count, 3)
        self.assertEqual(self.service.status()["suprimidos"], 0)

    def test_alert_cooldown_covers_status_changes_during_an_active_alert(self):
        opener = self.successful_endpoint()
        with patch("smartair.notifications.build_opener", return_value=opener):
            self.record(alerta=True, buzzerAlerta=True, buzzerLigado=False, estadoMQ="AQUECENDO")
            self.service.enviar_pendente(self.now)
            self.record(1, alerta=True, buzzerAlerta=True, buzzerLigado=True, estadoMQ="PRONTO")
            self.assertFalse(self.service.enviar_pendente(self.now + timedelta(seconds=1)))
        self.assertEqual(opener.open.call_count, 1)
        self.assertEqual(self.service.status()["suprimidos"], 1)

    def test_failed_delivery_does_not_start_alert_cooldown(self):
        self.record(alerta=True)
        opener = self.successful_endpoint()
        opener.open.side_effect = HTTPError(self.config.webhook_url, 503, "unavailable", {}, None)
        with patch("smartair.notifications.build_opener", return_value=opener):
            self.service.enviar_pendente(self.now)
            with database.conectar() as banco:
                self.assertEqual(banco.execute("SELECT count(*) FROM notificacao_alertas_enviados").fetchone()[0], 0)
            opener.open.side_effect = None
            retry_time = datetime.fromtimestamp(self.row()["proxima_tentativa"] + 1, timezone.utc)
            self.assertTrue(self.service.enviar_pendente(retry_time))
        self.assertEqual(self.row()["status"], "enviado")
        self.assertEqual(self.row()["tentativas"], 2)
        self.assertEqual(self.service.status()["suprimidos"], 0)

    def test_alert_cooldown_can_be_disabled(self):
        service = NotificationService(NotificationConfig(webhook_url=self.config.webhook_url, alert_cooldown_seconds=0))
        opener = self.successful_endpoint()
        with patch("smartair.notifications.build_opener", return_value=opener):
            for seconds, alert in enumerate((True, False, True)):
                self.record(seconds, service=service, alerta=alert)
                self.assertTrue(service.enviar_pendente(self.now + timedelta(seconds=seconds)))
        self.assertEqual(opener.open.call_count, 3)

    def test_alert_cooldown_uses_deliveries_from_before_the_upgrade(self):
        opener = self.successful_endpoint()
        with patch("smartair.notifications.build_opener", return_value=opener):
            self.record(alerta=True)
            self.service.enviar_pendente(self.now)
            with database.conectar() as banco:
                banco.execute("DELETE FROM notificacao_alertas_enviados")
            self.record(1, alerta=False)
            self.service.enviar_pendente(self.now + timedelta(seconds=1))
            self.record(2, alerta=True)
            self.assertFalse(NotificationService(self.config).enviar_pendente(self.now + timedelta(seconds=2)))
        self.assertEqual(opener.open.call_count, 2)
        self.assertEqual(self.service.status()["suprimidos"], 1)

    def test_timeout_does_not_expose_url(self):
        self.record()
        opener = MagicMock()
        opener.open.side_effect = URLError(self.config.webhook_url)
        with patch("smartair.notifications.build_opener", return_value=opener):
            self.service.enviar_pendente(self.now)
        self.assertNotIn("secret", json.dumps(self.service.status()))
        self.assertEqual(self.row()["status"], "pendente")

    def test_lease_prevents_double_claim_and_recovers_after_crash(self):
        self.record()
        first = self.service._reservar(self.now)
        another = NotificationService(self.config)
        self.assertIsNone(another._reservar(self.now))
        retry = another._reservar(self.now + timedelta(seconds=41))
        self.assertEqual(first["id"], retry["id"])
        self.assertNotEqual(first["lease_token"], retry["lease_token"])

    def test_migration_preserves_legacy_readings(self):
        legacy_path = Path(self.folder.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_path)) as banco:
            banco.execute("CREATE TABLE leituras (id INTEGER PRIMARY KEY, temperatura REAL, umidade REAL, criado_em TEXT)")
            banco.execute("INSERT INTO leituras VALUES (1, 24, 65, ?)", (self.now.isoformat(),))
            banco.commit()
        with patch.object(database, "DATABASE_PATH", legacy_path):
            database.inicializar()
            database.inicializar()
            self.assertEqual(database.mais_recente()["id"], 1)
            self.assertIsNone(database.mais_recente()["alerta_geral"])
            self.assertIsNone(database.mais_recente()["ventilacao_ligada"])
            self.assertIsNone(database.mais_recente()["rele_ligado"])
            self.assertIsNone(database.mais_recente()["rele_habilitado"])
            self.service.verificar_status(self.now)
            self.assertEqual(len(self.events()), 1)
            self.record(1, ventilacaoLigada=True, releLigado=False, releHabilitado=True)
            self.assertEqual(database.historico(1, 10)[-1]["id"], 1)
            self.assertIs(database.mais_recente()["ventilacao_ligada"], True)
            self.assertIs(database.mais_recente()["rele_ligado"], False)
            self.assertIs(database.mais_recente()["rele_habilitado"], True)

    def test_firmware_payload_is_accepted_and_stored_by_api(self):
        from fastapi.testclient import TestClient
        from smartair.main import app

        sample_path = Path(__file__).resolve().parents[1] / "examples/telemetria-firmware-v1.json"
        sample = json.loads(sample_path.read_text())
        with patch.dict(os.environ, {"SMARTAIR_POWER_AUTOMATE_URL": ""}):
            with TestClient(app) as client:
                for state in (False, True, None):
                    with self.subTest(ventilation=state):
                        payload = {**sample, "ventilacaoLigada": state}
                        self.assertEqual(client.post("/api/dados", json=payload).status_code, 200)
                        reading = client.get("/api/dados").json()
                        self.assertIs(reading["ventilacao_ligada"], state)
                        self.assertFalse(reading["alerta_geral"])
                        self.assertIsNone(reading["buzzer_alerta"])
                        self.assertNotIn("ventilacaoLigada", reading)
                history = client.get("/api/dados/historico").json()
                self.assertEqual([row["ventilacao_ligada"] for row in history], [None, True, False])
                self.assertEqual(client.post("/api/dados", json={**sample, "campoInexistente": True}).status_code, 422)
                error_payload = {**sample, "temperatura": None, "umidade": None, "erroDHT": True}
                self.assertEqual(client.post("/api/dados", json=error_payload).status_code, 200)
                self.assertIsNone(client.get("/api/dados").json()["temperatura"])
                self.assertTrue(client.get("/api/dados").json()["erro_dht"])

    def test_api_lifespan_validation_and_status(self):
        from fastapi.testclient import TestClient
        from smartair.main import app

        async def idle(service, stop):
            await stop.wait()

        with patch.dict(os.environ, {"SMARTAIR_POWER_AUTOMATE_URL": self.config.webhook_url}), patch.object(NotificationService, "executar", idle):
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/health").status_code, 200)
                self.assertEqual(client.get("/api/dados").status_code, 404)
                self.assertEqual(client.post("/api/dados", json={"temperatura": 24}).status_code, 422)
                self.assertEqual(self.events(), [])
                self.assertEqual(client.post("/api/dados", json={"temperatura": 24, "umidade": 65}).json(), {"status": "ok", "id": 1})
                self.assertEqual(client.get("/api/dados").json()["temperatura"], 24)
                self.assertEqual(len(client.get("/api/dados/historico").json()), 1)
                status = client.get("/api/notificacoes/status").json()
                self.assertTrue(status["habilitado"])
                self.assertEqual(status["pendentes"], 1)
                self.assertEqual(status["conexao"], "online")

    def test_background_delivery_does_not_block_telemetry(self):
        from fastapi.testclient import TestClient
        from smartair.main import app

        self.record()
        opened, release = Event(), Event()
        response = MagicMock()
        response.__enter__.return_value.status = 202

        def slow_webhook(*args, **kwargs):
            opened.set()
            release.wait(5)
            return response

        opener = MagicMock()
        opener.open.side_effect = slow_webhook
        with patch.dict(os.environ, {"SMARTAIR_POWER_AUTOMATE_URL": self.config.webhook_url}), patch("smartair.notifications.build_opener", return_value=opener):
            with TestClient(app) as client:
                try:
                    self.assertTrue(opened.wait(3), "O monitor deve iniciar junto com a API")
                    reading = client.post("/api/dados", json={"temperatura": 24, "umidade": 65, "alerta": True})
                    self.assertEqual(reading.status_code, 200)
                    self.assertEqual(client.get("/api/notificacoes/status").json()["em_envio"], 1)
                finally:
                    release.set()
        self.assertEqual(self.row()["status"], "enviado")
        self.assertEqual(len(self.events()), 2)

    def test_https_configuration(self):
        with self.assertRaises(ValueError):
            NotificationConfig(webhook_url="http://example.invalid")
        with self.assertRaises(ValueError):
            NotificationConfig(offline_after_seconds=0)
        with self.assertRaises(ValueError):
            NotificationConfig(alert_cooldown_seconds=-1)


if __name__ == "__main__":
    unittest.main()
