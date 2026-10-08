# Operação do SmartAir

Todos os comandos abaixo são executados na raiz do projeto. A máquina precisa ter Docker com Compose iniciado. O ESP32 e a máquina que executa a API precisam conseguir se comunicar pela rede local.

## Iniciar, verificar e parar

```bash
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 api dashboard
```

O dashboard aguarda a API ficar saudável. Acesse `http://localhost:8501`; de outro computador na rede, use `http://IP_DA_MAQUINA:8501`. O endereço usado pelo ESP32 é `http://IP_DA_MAQUINA:8080/api/dados`.

```bash
docker compose stop
docker compose start
```

Os serviços usam reinicialização automática com o Docker, exceto quando foram parados manualmente. A configuração dessa inicialização do Docker depende da máquina destino.

## Atualizar o código

Se o projeto já estiver vinculado ao GitHub:

```bash
git pull --ff-only
docker compose up -d --build
```

Para remover os containers mantendo o banco: `docker compose down`. O nome do projeto Compose continua `smartair`, preservando o volume `smartair_smartair-data` utilizado pela configuração anterior na pasta backend.

## Banco e backups

O banco Docker fica em `/data/smartair.db`, dentro do volume. O banco de desenvolvimento local fica em `smartair.db`. Eles são independentes e não fazem parte do GitHub.

Para exportar um snapshot consistente do banco em uso:

Os comandos de backup abaixo usam redirecionamento binário e devem ser executados em Bash (Linux, macOS ou WSL).

```bash
mkdir -p backups
docker compose exec -T api python -m smartair.backup export > backups/smartair.db
```

Para importar o histórico local **antes do primeiro início no Docker**, pare a API Python local e execute:

```bash
docker compose run --build --rm -T --no-deps api python -m smartair.backup import < smartair.db
docker compose up -d --build
```

Para trocar de máquina, copie o projeto e o backup separadamente. Na máquina destino, antes de iniciar os serviços:

```bash
docker compose run --build --rm -T --no-deps api python -m smartair.backup import < backups/smartair.db
docker compose up -d --build
```

A importação verifica a integridade do SQLite e recusa sobrescrever um banco existente. O comando `docker compose down -v` remove o volume e apaga seu histórico; utilize `docker compose down` para preservá-lo.

## Portas

Os padrões são 8080 para API e 8501 para dashboard. Se precisar trocar, copie `.env.example` para `.env` e edite as portas externas. Ajuste também a URL do ESP32 se trocar a porta da API. O dashboard usa `http://api:8080` dentro do Docker automaticamente.

## Diagnóstico

| Situação | O que conferir |
| --- | --- |
| Docker daemon indisponível | Iniciar o Docker Desktop/Engine e verificar suas permissões. |
| Porta ocupada | Parar o servidor Python anterior ou escolher outra porta no `.env`. |
| API indisponível | `docker compose ps` e `docker compose logs api`. |
| Painel sem leituras | No Monitor Serial, verificar se o POST retornou HTTP 200. |
| GET retorna 404 | Ainda não foi recebida nenhuma leitura válida. |
| POST retorna 422 | Consultar a mensagem de validação e o [contrato JSON](api.md). |
| ESP32 retorna erro de conexão | Conferir IP, porta, Wi-Fi, firewall e acesso entre dispositivos. |
| Estado de sensor/atuador não informado | O firmware precisa enviar esse campo; o Python não inventa o estado. |

Após 12 segundos sem novas leituras, por padrão, o painel indica ausência de sinal recente. `SMARTAIR_OFFLINE_AFTER_SECONDS` altera esse limite no painel e nas notificações. Os gráficos apresentam até 5.000 amostras por consulta no período escolhido, com horário de Brasília.

Para receber e-mails quando o ESP32 perder sinal, voltar a enviar dados ou mudar de alerta, siga o [guia do Power Automate](power-automate.md). A API precisa continuar executando para detectar ausência de telemetria. Se a própria máquina/API parar, este monitor não consegue avisar; isso exige monitoramento externo.
