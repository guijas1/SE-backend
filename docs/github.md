# Publicação no GitHub

O repositório é [guijas1/SE-backend](https://github.com/guijas1/SE-backend), **privado**, com a branch principal `main`. Para clonar, a conta GitHub precisa ter acesso ao repositório.

O `.gitignore` exclui bancos SQLite, backups, ambientes virtuais e `.env`. O modelo `.env.example` é versionado para que outra pessoa possa configurar as portas da própria máquina.

Antes de publicar, confira `git status --short`. Não inclua um banco ou configuração local à força usando `git add -f`.

## Enviar alterações

O remote `origin` já está configurado no projeto publicado e será criado automaticamente ao clonar. Na raiz do projeto:

```bash
git pull --ff-only
git add .
git commit -m "Descreva a alteração realizada"
git push origin main
```

Confira a configuração com `git status` e `git remote -v`. A autenticação pode ser feita com `gh auth login` ou pelo método Git usado pela equipe. Antes de `git pull`, registre ou guarde alterações locais pendentes.

Se houver alterações remotas que precisem ser integradas, resolva essa integração antes de enviar; não use push forçado para apagar o histórico. A licença de distribuição deve ser escolhida pela equipe antes de acrescentar um arquivo LICENSE.

## Para outra pessoa executar

```bash
git clone https://github.com/guijas1/SE-backend.git
cd SE-backend
docker compose up -d --build
```

Depois, abrir `http://localhost:8501` e configurar o firmware do ESP32, mantido separadamente, para enviar ao IP dessa máquina. O histórico deve ser transferido separadamente conforme o [guia de operação](operacao.md).
