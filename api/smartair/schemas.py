"""Validated request and response data models."""

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


class TelemetryInput(BaseModel):
    """Normalized telemetry accepted from the ESP32."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    temperatura: float | None = Field(default=None, ge=-40, le=80)
    umidade: float | None = Field(default=None, ge=0, le=100)
    mq135_adc: int | None = Field(
        default=None,
        ge=0,
        le=4095,
        validation_alias=AliasChoices("mq135_adc", "mq135ADC", "mq135"),
    )
    baseline_mq135: int | None = Field(
        default=None,
        ge=0,
        le=4095,
        validation_alias=AliasChoices("baseline_mq135", "baselineMQ135"),
    )
    limite_mq_alerta: int | None = Field(
        default=None,
        ge=0,
        le=8190,
        validation_alias=AliasChoices("limite_mq_alerta", "limiteMQAlerta", "limiteMQ135"),
    )
    limite_mq_normal: int | None = Field(
        default=None,
        ge=0,
        le=8190,
        validation_alias=AliasChoices("limite_mq_normal", "limiteMQNormal"),
    )
    estado_mq: Literal["AQUECENDO", "CALIBRANDO", "PRONTO"] | None = Field(
        default=None, validation_alias=AliasChoices("estado_mq", "estadoMQ")
    )
    erro_dht: bool | None = Field(default=None, validation_alias=AliasChoices("erro_dht", "erroDHT"))
    alerta_temperatura: bool | None = Field(
        default=None, validation_alias=AliasChoices("alerta_temperatura", "alertaTemperatura")
    )
    alerta_umidade: bool | None = Field(
        default=None, validation_alias=AliasChoices("alerta_umidade", "alertaUmidade")
    )
    alerta_qualidade_ar: bool | None = Field(
        default=None, validation_alias=AliasChoices("alerta_qualidade_ar", "alertaQualidadeAr")
    )
    alerta_geral: bool | None = Field(
        default=None, validation_alias=AliasChoices("alerta_geral", "alertaGeral", "alerta")
    )
    led_verde: bool | None = Field(default=None, validation_alias=AliasChoices("led_verde", "ledVerde"))
    led_vermelho: bool | None = Field(
        default=None, validation_alias=AliasChoices("led_vermelho", "ledVermelho")
    )
    buzzer: bool | None = Field(
        default=None, validation_alias=AliasChoices("buzzer", "buzzerLigado")
    )

    @field_validator("estado_mq", mode="before")
    @classmethod
    def normalizar_estado_mq(cls, valor):
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            return None
        if isinstance(valor, str):
            return valor.strip().upper()
        return valor

    @model_validator(mode="after")
    def validar_leitura_dht(self):
        if (self.temperatura is None) != (self.umidade is None):
            raise ValueError("temperatura e umidade devem ser enviadas juntas")
        if self.erro_dht:
            # Do not persist the last valid DHT values as if they were current.
            self.temperatura = None
            self.umidade = None
        if self.temperatura is None and self.mq135_adc is None and not self.erro_dht:
            raise ValueError("envie ao menos uma leitura de sensor ou informe erro_dht")
        if (
            self.baseline_mq135 is not None
            and self.limite_mq_alerta is not None
            and self.limite_mq_alerta < self.baseline_mq135
        ):
            raise ValueError("limite_mq_alerta não pode ser menor que o baseline")
        if (
            self.baseline_mq135 is not None
            and self.limite_mq_normal is not None
            and self.limite_mq_normal < self.baseline_mq135
        ):
            raise ValueError("limite_mq_normal não pode ser menor que o baseline")
        if (
            self.limite_mq_normal is not None
            and self.limite_mq_alerta is not None
            and self.limite_mq_normal > self.limite_mq_alerta
        ):
            raise ValueError("limite_mq_normal não pode ser maior que o limite de alerta")
        return self


def alerta_geral(leitura: TelemetryInput) -> bool | None:
    """Return true/false when known, otherwise preserve an unknown state."""
    sinais = [
        leitura.erro_dht,
        leitura.alerta_temperatura,
        leitura.alerta_umidade,
        leitura.alerta_qualidade_ar,
    ]
    if any(sinal is True for sinal in sinais):
        return True
    if leitura.alerta_geral is not None:
        return leitura.alerta_geral
    if all(sinal is False for sinal in sinais):
        return False
    return None
