# SmartAir · API e dashboard

Este repositório contém somente o software Python do SmartAir. O firmware do ESP32 é mantido separadamente. A API recebe as leituras dos sensores, valida os dados e os grava em SQLite; o Streamlit mostra condições atuais, tendências e alertas enviados pelo equipamento.

## Início rápido

Instale e inicie Docker com Docker Compose. Com acesso ao repositório privado, clone o projeto e execute:

```bash
git clone https://github.com/guijas1/SE-backend.git
cd SE-backend
docker compose up -d --build
```

Se já tiver o projeto na máquina, execute apenas o comando Docker na pasta que contém `compose.yaml`.

Pare a API/Streamlit que já estiverem executando diretamente no Python para liberar as portas. A primeira construção exige internet.

- Dashboard: http://localhost:8501
- Documentação da API: http://localhost:8080/docs
- Conferir serviços: `docker compose ps`
- Acompanhar mensagens: `docker compose logs -f`
- Parar os dois: `docker compose stop`

Nas próximas execuções, `docker compose up -d` inicia a imagem existente. Para receber dados reais, o firmware deve enviar a `http://IP_DO_COMPUTADOR:8080/api/dados`. Sem uma leitura aceita, o painel informa que está aguardando dados.

## Mapa do repositório

```text
.
├── README.md                 # início rápido
├── compose.yaml              # inicia os dois serviços
├── Dockerfile                # imagem Python
├── .env.example              # exemplo das portas externas
├── requirements.txt          # dependências Python de todo o projeto
├── app.py                    # compatibilidade com o comando antigo da API
├── api/
│   ├── smartair/
│   │   ├── main.py           # rotas FastAPI
│   │   ├── schemas.py        # validação/normalização
│   │   ├── database.py       # SQLite e consultas
│   │   ├── notifications.py  # eventos e webhook Power Automate
│   │   └── backup.py         # exportação/importação do banco
│   └── requirements.txt
├── dashboard/
│   ├── app.py                # interface Streamlit
│   ├── charts.py             # gráficos e histórico
│   └── requirements.txt
├── examples/                 # amostra do JSON enviado pelo ESP32
└── docs/                     # guias detalhados
```

## Para quem assumir a operação

- [Executar, atualizar, fazer backup e trocar de máquina](docs/operacao.md)
- [Contrato JSON e rotas da API](docs/api.md)
- [E-mails de status e alertas pelo Power Automate](docs/power-automate.md)
- [Desenvolver sem Docker](docs/desenvolvimento.md)
- [Publicar e clonar pelo GitHub](docs/github.md)

O banco local fica em `smartair.db`; no Docker, fica em um volume persistente. Bancos, backups e arquivos `.env` não são enviados ao GitHub. O histórico existente precisa ser importado separadamente seguindo o guia de operação.

O painel mostra somente dados recebidos pela API. Estados opcionais ausentes são indicados como não informados. O sinal do MQ-135 é apresentado em ADC, sem conversão calibrada para ppm/AQI.

O backend pode notificar mudanças de conexão, alertas, falhas de sensor e modo do buzzer por um webhook do Power Automate. O envio fica desativado até configurar `SMARTAIR_POWER_AUTOMATE_URL`. Os eventos ficam em uma fila persistente com novas tentativas em caso de falha. Consulte o [guia de configuração](docs/power-automate.md).
