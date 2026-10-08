# E-mail HTML somente para alertas

O modelo [email-alerta-power-automate.html](../examples/email-alerta-power-automate.html) usa os campos do webhook atual. Tem cabeçalho SmartAir, destaque vermelho, alertas, motivos e leituras. Os horários são apresentados em Brasília. Campos opcionais nulos aparecem como não informados; zero continua sendo uma leitura válida.

O filtro abaixo envia um e-mail quando uma leitura registra a ativação de um alerta geral/específico, uma falha DHT ou o alerta sonoro. Várias ativações na mesma leitura produzem um e-mail. Um evento de encerramento, conexão, calibração ou resumo, sozinho, não satisfaz o filtro. Um alerta já ativo na última leitura ao habilitar o monitor pode aparecer em `estado_inicial`; esse evento não representa uma nova ativação e fica fora deste filtro.

## Configurar o fluxo

Mantenha a etapa de adicionar linha ao Excel para todos os eventos. A condição deve envolver somente a ação de enviar o e-mail; não adicione este filtro às condições do gatilho HTTP.

1. Adicione **Operações de dados → Filtrar matriz** e renomeie a ação para `Filtrar_alertas`.
2. Em **De**, abra a aba **Expressão** e cole:

```text
coalesce(triggerBody()?['mudancas'], json('[]'))
```

3. No modo avançado de **Filtrar matriz**, cole:

```text
@and(
  equals(item()?['atual'], true),
  contains(
    createArray('alerta_geral', 'alerta_temperatura', 'alerta_umidade', 'alerta_qualidade_ar', 'erro_dht', 'buzzer_alerta', 'buzzer'),
    item()?['campo']
  )
)
```

O filtro usa o valor booleano `true` e uma lista explícita dos campos de alerta. A ação **Filtrar matriz** é documentada pela [Microsoft](https://learn.microsoft.com/en-us/power-automate/data-operations#use-the-filter-array-action).

4. Depois do filtro, adicione uma **Condição**. Na expressão do valor esquerdo, cole:

```text
and(
  equals(triggerBody()?['tipo'], 'status_alterado'),
  equals(triggerBody()?['conexao'], 'online'),
  greater(length(body('Filtrar_alertas')), 0)
)
```

Selecione **é igual a** e, no valor direito, use a expressão booleana `true`. Se a ação de filtro tiver outro nome interno, ajuste `body('Filtrar_alertas')` para o nome correspondente.

5. No ramo **Se sim**, coloque **Enviar um e-mail (V2)**. Em **Para**, configure os destinatários. Em **Assunto**, use:

```text
[SmartAir] Alerta detectado — @{triggerBody()?['dispositivo']}
```

6. No **Corpo**, clique no botão `</>` e cole o conteúdo completo do [arquivo HTML](../examples/email-alerta-power-automate.html). Preserve as expressões `@{...}`. A [documentação da Microsoft sobre HTML em e-mails](https://learn.microsoft.com/pt-br/power-automate/email-customization) descreve esse editor.
7. Deixe o ramo **Se não** sem ação de e-mail. Salve o fluxo e confira uma execução com alerta real. Este arquivo não altera automaticamente o fluxo na conta Microsoft.

As expressões de filtro e data usam as [funções disponíveis no Power Automate](https://learn.microsoft.com/en-us/azure/logic-apps/expression-functions-reference).

O modelo também mostra `leitura.ventilacao_ligada`. Uma mudança da ventilação, por si só, não satisfaz o filtro de alerta. Para registrar o atuador na planilha, use o cabeçalho `Ventilacao_Ligada` e a expressão `triggerBody()?['leitura']?['ventilacao_ligada']`. Atualize o esquema JSON do gatilho com [power-automate-schema.json](../examples/power-automate-schema.json) para disponibilizar esse campo no conteúdo dinâmico.

O relé também aparece no modelo: `leitura.rele_ligado` informa acionamento e `leitura.rele_habilitado` informa habilitação no firmware. Na planilha, use `Rele_Ligado` e `Rele_Habilitado`, mapeados respectivamente para `triggerBody()?['leitura']?['rele_ligado']` e `triggerBody()?['leitura']?['rele_habilitado']`. Mudanças desses estados, por si só, não satisfazem o filtro de alerta.

O filtro evita e-mails por outras mudanças enquanto um alerta permanece inalterado. Novas tentativas HTTP do mesmo evento ainda podem repetir a execução; use `evento_id` para deduplicação no fluxo se necessário, como descrito no [guia de integração](power-automate.md#persist%C3%AAncia-e-novas-tentativas).
