# Contrato da API

O arquivo `api/smartair/main.py` define as rotas. `schemas.py` valida e normaliza a entrada; `database.py` armazena e consulta o SQLite. A documentação interativa em `/docs` mostra todos os campos e faixas aceitas.

| Método e rota | Finalidade |
| --- | --- |
| `GET /api/health` | Verificar se a API está respondendo. |
| `POST /api/dados` | Receber e persistir uma leitura do ESP32. |
| `GET /api/dados` | Consultar a última leitura; 404 antes da primeira. |
| `GET /api/dados/historico?horas=24&limite=1000` | Consultar amostras recentes, da mais nova para a mais antiga. |

## Payload do firmware v3

Veja [examples/telemetria-v3.json](../examples/telemetria-v3.json). Esse arquivo é uma amostra para documentação e desenvolvimento; o dashboard não o carrega como dados reais.

| Campo normalizado | Outros nomes aceitos | Unidade/valor |
| --- | --- | --- |
| `temperatura` | — | °C, de -40 a 80 |
| `umidade` | — | %, de 0 a 100 |
| `mq135_adc` | `mq135ADC`, `mq135` | ADC de 12 bits, de 0 a 4095 |
| `baseline_mq135` | `baselineMQ135` | Referência ADC |
| `limite_mq_alerta` | `limiteMQAlerta`, `limiteMQ135` | Limiar de alerta ADC |
| `limite_mq_normal` | `limiteMQNormal` | Limiar de retorno ao normal ADC |
| `estado_mq` | `estadoMQ` | `AQUECENDO`, `CALIBRANDO`, `PRONTO` |
| `erro_dht` | `erroDHT` | Booleano |
| `alerta_temperatura` | `alertaTemperatura` | Booleano |
| `alerta_umidade` | `alertaUmidade` | Booleano |
| `alerta_qualidade_ar` | `alertaQualidadeAr` | Booleano |
| `alerta_geral` | `alertaGeral`, `alerta` | Booleano |
| `led_verde`, `led_vermelho` | `ledVerde`, `ledVermelho` | Booleano |
| `buzzer` | `buzzerLigado` | Booleano |

Temperatura e umidade devem ser enviadas juntas; o payload mínimo antigo continua aceito. Também é possível enviar o MQ-135 sozinho ou reportar uma falha DHT. Campos opcionais omitidos permanecem desconhecidos.

O backend usa snake_case nas respostas, acrescenta `id` e `criado_em` em UTC e mantém o horário da recepção no servidor. Se `erro_dht` for verdadeiro, temperatura e umidade daquela amostra ficam nulas para não apresentar valores antigos como atuais. Um alerta específico verdadeiro ativa o alerta geral mesmo que o campo agregado indique falso.

Campos desconhecidos, valores fora da faixa ou limites de calibração incoerentes recebem HTTP 422. O POST válido responde HTTP 200 com `{"status":"ok","id":...}`. A API não converte o sinal ADC do MQ-135 em ppm/AQI e não controla os atuadores do ESP32.
