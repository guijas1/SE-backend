# Desenvolvimento Python

Use Python 3.10 ou superior. A imagem Docker usa Python 3.12. Os comandos abaixo partem da raiz do projeto:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

No Windows, a ativação no PowerShell é `.venv\Scripts\Activate.ps1`.

Em um terminal, inicie a API:

```bash
python -m uvicorn smartair.main:app --app-dir api --host 0.0.0.0 --port 8080 --reload
```

Em outro terminal com o mesmo ambiente virtual ativado:

```bash
python -m streamlit run dashboard/app.py
```

`app.py` é a entrada de compatibilidade da API. O arquivo que renderiza a interface é `dashboard/app.py`; executá-los trocados pode resultar em uma página vazia.

## Onde alterar

| Mudança | Arquivo |
| --- | --- |
| Novos campos ou validações | `api/smartair/schemas.py` |
| Rotas HTTP | `api/smartair/main.py` |
| Persistência e histórico | `api/smartair/database.py` |
| Backup/importação | `api/smartair/backup.py` |
| Eventos, monitoramento e webhook Power Automate | `api/smartair/notifications.py` |
| Indicadores e organização da tela | `dashboard/app.py` |
| Eixos, séries e horários dos gráficos | `dashboard/charts.py` |

O backend usa `smartair.db` por padrão. Para trabalhar com outro banco, defina `SMARTAIR_DATABASE_PATH` antes de iniciar o processo. O dashboard consulta `http://127.0.0.1:8080` por padrão; `SMARTAIR_API_URL` altera esse endereço. O arquivo `.env` é usado pelo Compose e não é carregado automaticamente pelos comandos Python locais.

## Configuração do Docker

```bash
docker compose config --quiet
```

Ao alterar a telemetria, confira a compatibilidade com `examples/telemetria-v3.json` e atualize o [contrato da API](api.md). Depois de alterar arquivos usados no Docker, execute `docker compose up -d --build`.

## Testes de notificações

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Os testes usam bancos temporários e simulam o endpoint HTTP, sem enviar e-mails. Cobrem transições, ausência de campos, falhas DHT, pausas do buzzer, offline/reconexão, reinício, resumos, transações, concorrência, novas tentativas e as rotas da API.
