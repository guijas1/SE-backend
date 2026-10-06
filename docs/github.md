# Publicação no GitHub

O `.gitignore` exclui bancos SQLite, backups, ambientes virtuais e `.env`. O modelo `.env.example` é versionado para que outra pessoa possa configurar as portas da própria máquina.

Antes de publicar, confira `git status --short`. Não inclua um banco ou configuração local à força usando `git add -f`.

## Repositório novo

Crie um repositório vazio no GitHub com o nome e a visibilidade escolhidos pela equipe. Copie a URL HTTPS/SSH dele. Na raiz do projeto:

```bash
git init -b main
git add .
git commit -m "Organiza SmartAir para execução e publicação"
git remote add origin URL_DO_REPOSITORIO
git push -u origin main
```

Se o Git já tiver sido inicializado ou existir um commit, continue a partir da configuração do remote. Confira com `git status` e `git remote -v`. A autenticação pode ser feita com `gh auth login` ou pelo método Git usado pela equipe.

Se o repositório remoto já tiver arquivos, primeiro integre esse histórico; não use push forçado para apagá-los. A licença de distribuição deve ser escolhida pela equipe antes de acrescentar um arquivo LICENSE.

## Para outra pessoa executar

```bash
git clone URL_DO_REPOSITORIO
cd NOME_DO_REPOSITORIO
docker compose up -d --build
```

Depois, abrir `http://localhost:8501` e configurar o firmware do ESP32, mantido separadamente, para enviar ao IP dessa máquina. O histórico deve ser transferido separadamente conforme o [guia de operação](operacao.md).
