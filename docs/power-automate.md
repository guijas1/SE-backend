# E-mails de status pelo Power Automate

O backend detecta mudanças no ESP32, grava os eventos no SQLite e faz POST HTTPS para um fluxo do Power Automate. O fluxo define os destinatários e envia o e-mail. Nenhuma alteração no firmware é necessária se ele já enviar a telemetria documentada.

## Eventos enviados

| Situação | Quando notifica |
| --- | --- |
| Online | Primeira leitura e retorno após ficar offline. |
| Offline | Mais de 12 segundos sem leituras válidas, por padrão. |
| Alertas | Ativação e encerramento dos alertas geral, de temperatura, umidade e qualidade do ar. |
| DHT22 | Falha de leitura e recuperação do sensor. |
| Alerta sonoro | Ativação e encerramento de `buzzer_alerta`. As pausas entre bipes não geram novos eventos. |
| Buzzer antigo | Se apenas `buzzer` estiver disponível, informa som observado uma vez, até receber retorno explícito ao normal e ausência de som. |
| Ventilação | Mudança de ligada/desligada informada pelo ESP32. |
| Relé | Mudança de acionamento ou habilitação informada pelo ESP32. |
| Estado do sistema/MQ-135 | Mudança de estado, incluindo aquecimento, calibração e pronto. |
| Motivos | Mudança na lista de motivos enviada pelo equipamento. |
| Resumo periódico | Opcional; desativado por padrão. |

Mudanças na mesma leitura são reunidas em um evento/e-mail. Uma amostra repetida não gera outro evento; variações nos valores de temperatura, umidade, ADC e LEDs, por si só, não geram e-mails. Os limites de alerta continuam definidos no firmware.

O e-mail inclui a conexão, o horário do evento e da última leitura, temperatura, umidade, ADC, estados dos sensores, alertas, LEDs e buzzer. Horários do e-mail usam Brasília por padrão; datas no JSON continuam em UTC. Um campo ausente aparece como não informado e não encerra um alerta anteriormente conhecido. Os valores de um dispositivo offline são identificados como a última amostra recebida.

O projeto monitora **um único equipamento**, como o contrato atual da API. “Online” significa telemetria válida recente. A API precisa permanecer executando para detectar a perda de sinal; uma queda da máquina/backend exige monitoramento externo. Antes da primeira leitura, o estado é `aguardando` e nenhum aviso de offline é criado.

## 1. Criar o fluxo na Microsoft

Para enviar e-mails somente quando um alerta for ativado, mantendo todos os eventos na planilha, use o [modelo HTML e a condição de envio para alertas](email-alerta.md). Os passos abaixo descrevem o envio genérico de status.

1. No Power Automate, crie um fluxo de nuvem com o gatilho **When an HTTP request is received / Quando uma solicitação HTTP é recebida**.
2. No campo de esquema JSON do gatilho, cole o conteúdo de [examples/power-automate-schema.json](../examples/power-automate-schema.json).
3. Em **Who can trigger the flow? / Quem pode acionar o fluxo?**, selecione **Anyone / Qualquer pessoa** para este modo de integração. O backend usa a URL assinada do gatilho e não obtém tokens OAuth do Microsoft Entra. O padrão dos fluxos novos pode exigir autenticação do tenant; se mantido, esta integração receberá 401/403. Conforme a [documentação da Microsoft](https://learn.microsoft.com/en-us/power-automate/oauth-authentication), quem possui essa URL pode acionar o fluxo. Guarde a URL como uma senha.
4. Adicione a ação **Office 365 Outlook → Send an email (V2) / Enviar um e-mail (V2)** e conecte a conta remetente. Essa ação é descrita no [guia da Microsoft para fluxos de nuvem](https://learn.microsoft.com/en-us/power-automate/get-started-logic-flow).
5. Em **Para**, preencha os destinatários desejados. Em **Assunto**, selecione o conteúdo dinâmico `assunto`. Em **Corpo**, use `corpo_html`; se necessário, abra o editor HTML (`</>`) para inserir esse conteúdo. O backend já gera HTML com os textos do equipamento escapados.
6. Se os campos não aparecerem no conteúdo dinâmico, use as expressões `triggerBody()?['assunto']` e `triggerBody()?['corpo_html']`.
7. Salve o fluxo e copie a **URL HTTP POST completa** gerada pelo gatilho, incluindo os parâmetros de assinatura. Use o endereço atual mostrado pelo Power Automate, sem montar ou alterar a URL manualmente.

Confira no seu ambiente se o gatilho HTTP está disponível no plano e se a política da organização permite o modo `Anyone`. Se ele estiver bloqueado, este modo não funcionará: será necessário adaptar a autenticação ao Microsoft Entra. Os direitos de uso de conectores dependem da [licença do Power Automate](https://learn.microsoft.com/en-us/power-platform/admin/power-automate-licensing/types).

Não é necessário adicionar uma ação de resposta para a integração aceitar o evento. O backend considera qualquer HTTP 2xx como aceitação pelo fluxo; isso não confirma a entrega do e-mail. Confira as falhas da ação Outlook no histórico de execução do Power Automate. Se adicionar uma resposta após o envio, configure o timeout do backend considerando a duração do fluxo.

## 2. Configurar o backend

Copie `.env.example` para `.env` se esse arquivo ainda não existir e preencha:

```dotenv
SMARTAIR_POWER_AUTOMATE_URL="COLE_A_URL_HTTPS_COMPLETA_DO_GATILHO"
SMARTAIR_DEVICE_NAME="SmartAir ESP32"
SMARTAIR_OFFLINE_AFTER_SECONDS=12
SMARTAIR_SUMMARY_INTERVAL_SECONDS=0
```

Escolha um limite de offline maior que o intervalo normal de envio do ESP32, com folga para atrasos. O Compose repassa o mesmo limite ao painel. Para também receber um resumo a cada hora, use `SMARTAIR_SUMMARY_INTERVAL_SECONDS=3600`.

Recrie os serviços para aplicar o código e as variáveis:

```bash
docker compose up -d --build
```

O `.env` é ignorado pelo Git. O webhook só é repassado ao container da API. Evite compartilhar a saída completa de `docker compose config`, que pode conter a URL; use `docker compose config --quiet` para validar a configuração.

Em desenvolvimento sem Docker, exporte as variáveis no terminal antes de iniciar Uvicorn. O comando Python não carrega `.env` automaticamente.

| Variável | Padrão | Finalidade |
| --- | --- | --- |
| `SMARTAIR_POWER_AUTOMATE_URL` | Vazia | URL HTTPS assinada; vazia desativa o monitor e os envios. |
| `SMARTAIR_DEVICE_NAME` | `SmartAir ESP32` | Nome exibido no e-mail. |
| `SMARTAIR_OFFLINE_AFTER_SECONDS` | `12` | Tempo sem telemetria para considerar offline. |
| `SMARTAIR_NOTIFICATION_CHECK_SECONDS` | `2` | Intervalo de verificação da conexão e da fila. |
| `SMARTAIR_NOTIFICATION_TIMEOUT_SECONDS` | `10` | Timeout de cada chamada ao webhook. |
| `SMARTAIR_SUMMARY_INTERVAL_SECONDS` | `0` | Intervalo dos resumos; `0` desativa. |
| `SMARTAIR_NOTIFICATION_TIMEZONE` | `America/Sao_Paulo` | Fuso do texto do e-mail. |

## 3. Conferir a integração

```bash
curl http://localhost:8080/api/notificacoes/status
docker compose logs --tail=100 api
```

O status deve ter `habilitado: true`. Se o banco já tiver leituras e nenhum estado de notificações, o monitor envia o estado inicial; a última leitura pode já estar offline. Caso contrário, envie dados pelo ESP32 para gerar o primeiro evento online. Confira a execução do fluxo e o e-mail recebido.

Para testar offline, interrompa temporariamente os envios do ESP32 mantendo o backend ativo. Depois do limite configurado, será criado um evento offline; ao retomar as leituras, será criado um evento online. A detecção ocorre no ciclo seguinte ao limite e pode atrasar durante uma chamada ao webhook. Alertas só são notificados se o equipamento os informar: o backend não simula sensor ou acionamento do buzzer.

`pendentes` e `em_envio` indicam eventos na fila; `enviados` conta os aceitos pelo endpoint. `ultimo_envio_em` e `ultimo_erro` ajudam a diagnosticar sem revelar a URL assinada. Erros HTTP 400 indicam geralmente contrato/fluxo; 401/403, URL ou autenticação; 429, limite de chamadas; falhas de conexão podem indicar internet, DNS ou timeout.

## Persistência e novas tentativas

Os eventos e o estado de comparação ficam no mesmo SQLite das leituras, incluídos nos backups. A leitura e sua notificação são gravadas na mesma transação. O envio ocorre em segundo plano e falhas de rede não interrompem os POSTs da telemetria. Reiniciar a API preserva a fila e não repete alertas inalterados.

Os eventos são enviados em ordem. Uma falha é tentada novamente após 5, 10, 20 segundos e assim por diante, até um intervalo de 5 minutos, enquanto a configuração estiver habilitada. Um evento com erro bloqueia os posteriores até ser aceito: corrija o fluxo/URL e acompanhe a fila. Eventos aceitos são mantidos no banco para contagem e diagnóstico. Desativar o webhook pausa os envios sem apagar pendências; ao reativar, elas continuam. Mudanças ocorridas durante a desativação não são todas reconstruídas; o monitor compara a última leitura disponível.

A entrega HTTP usa novas tentativas: se o fluxo aceitar um evento e a confirmação se perder, ele poderá ser enviado novamente. `evento_id` permanece igual nas tentativas, e também vai no cabeçalho `Idempotency-Key`. O Power Automate não elimina duplicatas automaticamente por esse cabeçalho; se a operação exigir isso, registre/verifique `evento_id` no fluxo antes de enviar o e-mail. Um backup restaurado também restaura eventos pendentes.

## Contrato do webhook

O backend envia JSON com `Content-Type: application/json; charset=utf-8`. O [esquema pronto](../examples/power-automate-schema.json) permite sensores e estados nulos, preservando a compatibilidade com firmware antigo.

| Campo | Conteúdo |
| --- | --- |
| `evento_id` | UUID estável por evento. |
| `tipo` | `status_alterado`, `dispositivo_offline`, `estado_inicial` ou `resumo_periodico`. |
| `dispositivo` | Nome configurado. |
| `ocorrido_em` | Horário do evento em UTC. |
| `conexao` | `online` ou `offline` no evento. |
| `assunto` | Assunto pronto para o e-mail. |
| `mensagem` | Corpo em texto simples. |
| `corpo_html` | Corpo em HTML pronto para o Outlook. |
| `mudancas` | Lista com `campo`, `anterior`, `atual` e `descricao`; vazia nos resumos. |
| `leitura` | Última telemetria normalizada, incluindo `id` e `criado_em`. |
