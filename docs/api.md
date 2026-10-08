# Contrato da API

O arquivo `api/smartair/main.py` define as rotas. `schemas.py` valida e normaliza a entrada; `database.py` armazena e consulta o SQLite. A documentação interativa em `/docs` mostra todos os campos e faixas aceitas.

| Método e rota | Finalidade |
| --- | --- |
| `GET /api/health` | Verificar se a API está respondendo. |
| `POST /api/dados` | Receber e persistir uma leitura do ESP32. |
| `GET /api/dados` | Consultar a última leitura; 404 antes da primeira. |
| `GET /api/dados/historico?horas=24&limite=1000` | Consultar amostras recentes, da mais nova para a mais antiga. |
| `GET /api/notificacoes/status` | Consultar conexão do ESP32, configuração de notificações e contagens da fila, sem expor o webhook. |

## Payload do ESP32

Veja [examples/telemetria-v3.json](../examples/telemetria-v3.json). Esse arquivo é uma amostra para documentação e desenvolvimento; o dashboard não o carrega como dados reais.

| Campo normalizado | Outros nomes aceitos | Unidade/valor |
| --- | --- | --- |
| `temperatura` | — | °C, de -40 a 80 |
| `umidade` | — | %, de 0 a 100 |
| `mq135_adc` | `mq135ADC`, `mq135` | ADC de 12 bits, de 0 a 4095 |
| `baseline_mq135` | `baselineMQ135` | Referência ADC |
| `limite_mq_alerta` | `limiteMQAlerta`, `limiteMQ135` | Limiar de alerta ADC |
| `limite_mq_normal` | `limiteMQNormal`, `limiteNormalMQ135` | Limiar de retorno ao normal ADC |
| `estado_mq` | `estadoMQ`, `estadoMQ135` | `AQUECENDO`, `CALIBRANDO`, `PRONTO` |
| `estado_sistema` | `estadoSistema` | Estado informado: `NORMAL` ou `ALERTA` |
| `erro_dht` | `erroDHT` | Booleano |
| `alerta_temperatura` | `alertaTemperatura` | Booleano |
| `alerta_umidade` | `alertaUmidade` | Booleano |
| `alerta_qualidade_ar` | `alertaQualidadeAr` | Booleano |
| `alerta_geral` | `alertaGeral`, `alerta` | Booleano |
| `led_verde` | `ledVerde`, `ledVerdeLigado` | Booleano |
| `led_vermelho` | `ledVermelho`, `ledVermelhoLigado` | Booleano |
| `buzzer` | `buzzerLigado`, `buzzerEmitindoSom` | Som emitido no instante da amostra, booleano |
| `buzzer_alerta` | `buzzerAlerta`, `buzzerEmAlerta` | Modo de alerta sonoro ativo, booleano |
| `ventilacao_ligada` | `ventilacaoLigada` | Estado da ventilação informado pelo firmware, booleano |
| `rele_ligado` | `releLigado` | Relé acionado, booleano |
| `rele_habilitado` | `releHabilitado` | Relé habilitado no firmware, booleano |
| `motivos_alerta` | `motivosAlerta` | Lista de até 16 textos de 1 a 120 caracteres |

Temperatura e umidade devem ser enviadas juntas; o payload mínimo antigo continua aceito. Também é possível enviar o MQ-135 sozinho ou reportar uma falha DHT. Campos opcionais omitidos permanecem desconhecidos.

O backend usa snake_case nas respostas, acrescenta `id` e `criado_em` em UTC e mantém o horário da recepção no servidor. Se `erro_dht` for verdadeiro, temperatura e umidade daquela amostra ficam nulas para não apresentar valores antigos como atuais. Um alerta específico verdadeiro ativa o alerta geral mesmo que o campo agregado indique falso.

`estadoSistema: "ALERTA"` também ativa o alerta geral. Se o campo agregado estiver ausente, `estadoSistema: "NORMAL"` informa ausência de alerta, desde que nenhum alerta específico esteja ativo. O estado informado pelo dispositivo é preservado em `estado_sistema`.

`buzzerAlerta` e `buzzerEmitindoSom` são independentes: durante a pausa entre bipes, o primeiro pode ser verdadeiro e o segundo falso. O campo normalizado `buzzer` mantém o significado de som na amostra para preservar a compatibilidade com clientes antigos. Ele não informa o que ocorreu entre dois envios de telemetria.

`motivosAlerta: []` significa que o dispositivo enviou uma lista vazia; campo omitido resulta em `null`. A lista é armazenada em JSON no SQLite e devolvida como lista nas rotas de consulta. Ao iniciar a API, as colunas novas são adicionadas automaticamente ao banco existente; leituras antigas mantêm esses campos como `null`.

`ventilacaoLigada` é aceito e devolvido como `ventilacao_ligada`, também no histórico e no webhook do Power Automate. O valor pode ser verdadeiro, falso ou nulo; ausência do campo significa estado desconhecido. Esse atuador não ativa o alerta geral por si só. O backend não controla o relé.

O [payload com LEDs, buzzer e relé](../examples/telemetria-firmware-v2.json) também é aceito. `releLigado`, `releHabilitado` e `ventilacaoLigada` representam informações independentes e são preservados separadamente. Um relé pode estar habilitado e desligado. Esses estados não ativam o alerta geral por si só; campos omitidos ficam nulos. Os alertas ambientais são os informados pelo firmware; o backend não recalcula `alertaQualidadeAr` a partir do ADC e do limite.

O [exemplo do firmware completo atual](../examples/telemetria-firmware-v1.json) contém os campos enviados por `SmartAir1.ino.ino` após a calibração. Os campos adicionais do exemplo v3 são opcionais. O backend aceita falhas DHT com `erroDHT: true` e temperatura/umidade nulas; o firmware precisa continuar fazendo POST durante a falha para ela ser registrada. Se ele suspender os envios, o backend detectará ausência de comunicação.

Campos desconhecidos, valores fora da faixa ou limites de calibração incoerentes recebem HTTP 422. O POST válido responde HTTP 200 com `{"status":"ok","id":...}`. A API não converte o sinal ADC do MQ-135 em ppm/AQI e não controla os atuadores do ESP32.

## Notificações

Quando configurado, o monitor envia eventos ao Power Automate em segundo plano. A leitura e seu evento são gravados na mesma transação; uma falha de rede no webhook não impede a recepção da telemetria. Consulte o [guia de configuração e contrato do webhook](power-automate.md).

`GET /api/notificacoes/status` retorna `habilitado`, `dispositivo`, `conexao` (`aguardando`, `online` ou `offline`), `ultima_leitura_em`, `offline_apos_segundos`, `resumo_intervalo_segundos`, `pendentes`, `em_envio`, `enviados`, `ultimo_envio_em` e `ultimo_erro`. `enviados` contabiliza eventos aceitos pelo endpoint HTTP, não confirma a entrega do e-mail. `ultimo_erro` contém apenas um diagnóstico resumido, como `HTTP 401` ou falha de conexão.

`alerta_intervalo_minimo_segundos` informa o bloqueio de repetição configurado em `SMARTAIR_ALERT_COOLDOWN_SECONDS` (300 por padrão). `suprimidos` conta os eventos com alertas já enviados recentemente que foram mantidos na fila como registro, sem fazer outro POST ao Power Automate. Um alerta de outro tipo é liberado imediatamente.
