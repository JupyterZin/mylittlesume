# Desenvolvimento do Talos

Este ficheiro serve para quem **constrói** o Talos. A persona do agente em runtime fica em `workspace/CLAUDE.md`.

1. **Leia o `LEDGER.md` antes de qualquer trabalho.** Ele tem o estado atual, as próximas ações, os factos do servidor e as armadilhas já conhecidas.
2. **Atualize o `LEDGER.md`** ao fim de cada bloco de trabalho e antes de a conversa ficar longa:
   - reescreva "Estado atual" e "Próximas ações";
   - acrescente uma entrada ao "Diário".
3. Regras do `SPEC.md` §0 e §2, sempre:
   - passos humanos em português do Brasil, curtos e um de cada vez;
   - confirmar antes de firewall, SSH, rede ou apagar dados;
   - nenhum segredo nem dado pessoal no Git;
   - sem `ANTHROPIC_API_KEY`.
4. Antes de cada push: `make test` e `make app-test` verdes, e commits pequenos (Conventional Commits).
