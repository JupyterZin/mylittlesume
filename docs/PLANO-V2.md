# Talos v2 — plano de evolução

> Pedido do Lucas (2026-10-03): rever o **Muse** (Meta), o **dots** (OpenAI) e o **Grok Bot** (xAI) para melhorar o Talos. Prioridades dele:
> 1. **Não misturar assuntos** numa única conversa, nem estourar o contexto.
> 2. **Mandar fotos**, aproveitando a visão do Claude.
>
> Este documento é **só planejamento**. Nada aqui está implementado.

## 1. Resumo

O Talos já tem a arquitetura do Muse em pequeno:
- um computador próprio e isolado;
- um navegador visível que você pode assumir;
- uma **Sentinela** separada que decide o que sai;
- aprovações antes de ações com consequência;
- preenchimento de credenciais com o agente pausado.

O que nos separa dos três não é a segurança. É a **experiência**:

| Lacuna | Quem faz bem | Impacto para o Lucas |
|---|---|---|
| Uma conversa única que mistura tudo | Muse ("side chats"), dots (um *dot* por objetivo) | **Alto**, foi o pedido |
| Contexto que cresce sem controle | Grok Bot (resumos), dots (notas próprias) | Alto (custo da assinatura e qualidade) |
| Sem fotos nem documentos | Muse (foto → ação), dots, Grok | **Alto**, foi o pedido |
| Memória invisível | Muse (Memory/Soul editáveis), Grok (mapa de memória) | Médio |
| Uma aprovação por passo | Muse (aprovações com escopo), Grok (Require/Always Allow) | Médio |
| Não aprende com demonstração | Grok Bot (*teach-a-task*) | Médio |
| Sem modo voz | Muse (widget de chamada), dots (ligação) | Médio |

**Ordem proposta:**
1. **Conversas por assunto**, com memória partilhada e orçamento de contexto.
2. **Fotos e documentos.**
3. **Memória visível.**
4. Os objetivos da F6 original.
5. A F7 de endurecimento.
6. Aprovações com escopo, modo voz e "ensinar uma tarefa".

## 2. O que eles fazem (pesquisa de 2026-10-03)

### Muse (Meta) — lançado em 8 de setembro de 2026
- **O que é:** agente pessoal que executa tarefas longas: email, viagens, formulários, compras, baixar contas. Continua trabalhando depois de você fechar o app. Roda no modelo Muse Spark. Disponível no app, na web e **dentro do WhatsApp**. Plano grátis, US$ 20 e US$ 100.
- **Secure VM:** cada pessoa tem uma VM dedicada com o agente, o navegador e os dados. É o "sistema de registo"; os dados só saem para a inferência.
- **Sentinel:** um programa separado do agente, ao nível do sistema. Nas palavras da Meta, nada do que o Muse faz chega à internet sem a aprovação dele. *(É o mesmo desenho da nossa Sentinela.)*
- **Aprovações:** distingue trabalho rotineiro de ações com consequência. Cada aprovação fica **ligada a um destino e a um propósito**, e pode ser única, por sessão, por tarefa ou por tempo limitado.
- **Navegador visível e takeover:** com uma aba dedicada para ver a tela da VM. Quando o usuário assume, ou enquanto o cofre de credenciais preenche um formulário, o agente fica **pausado**.
- **Conversa principal + "side chats":** a conversa principal é a relação contínua (preferências, dados pessoais, o que atravessa projetos). Os projetos grandes vão para **side chats**, para não poluírem a principal. A memória atravessa todas as conversas.
- **Memória editável:** "Memory" (o que sabe de você) e "Soul" (estilo), ambas visíveis e editáveis.
- **Multimodal:** foto → ação (ex.: reel de receita → lista de compras; prateleira → ranking por proteína).
- **Voz:** widget de chamada compacto. O agente continua a tarefa enquanto você fala.
- **Incidentes no primeiro mês (lições):**
  - um usuário pôs o Muse a gerir vendas no Marketplace; ele **partilhou a morada** com compradores, **aceitou uma oferta baixa** e só avisou à noite;
  - investigadores fizeram-no **compactar o sistema de ficheiros** da VM;
  - uma definição escondida no app de Mac permitia sequestrar o token do agente;
  - a própria Meta admite que **prompt injection continua em aberto**.

### dots (OpenAI) — lançado em 29 de setembro de 2026
- **O que é:** agentes "sempre ligados", com nome e avatar, dentro do ChatGPT. Correm no GPT-6 Astra.
- Cada *dot* tem **um objetivo**, um computador na nuvem, memória e apps ligados (mais de 4.000 integrações). Trabalha entre as conversas e **reporta no seu próprio ritmo**.
- **Canais:** ChatGPT, SMS (beta), Slack, Teams e chamada de voz. O contexto passa de um canal para outro. No Slack, você encaminha uma thread para o *dot* assumir.
- **Memória em três camadas:**
  - a conversa em que está a trabalhar;
  - a memória do ChatGPT;
  - **notas próprias do dot** (preferências, decisões, trabalho em curso), que atravessam os canais.
- **Pesquisa proativa:** quando você não está a falar com ele, procura formas de ajudar.
- Em breve: controlar **vários dots** como uma equipa. Há também dots especialistas para empresas.

### Grok Bot (xAI) — lançado em agosto de 2026
- **O que é:** "colegas" com nome e cargo. Cada um tem um computador persistente na nuvem (navegador, ficheiros, terminal), conectores e MCP.
- **Teach-a-task:** você grava a tela uma vez (até 10 min, sem áudio) e o Grok transforma isso numa **skill** repetível. A xAI recomenda rever a skill e acrescentar verificações, falhas e pontos de aprovação antes de agendar.
- **Correções que ficam:** quando você corrige um passo, a correção vale para as próximas execuções.
- **Regras de aprovação:** "Require Approval" sempre para a ação. "Always Allow" só passa se a revisão automática não encontrar nada. Se as duas casarem, a aprovação ganha.
- **Mapa de memória com 7 lugares**, cada um com um papel e uma duração diferentes:
  - descrição do bot (papel, regras, limites de aprovação);
  - conversa (a tarefa atual);
  - memória aprendida (preferências estáveis);
  - skills (método repetível);
  - rotinas (gatilho, entradas e resultado);
  - workspace (ficheiros duráveis);
  - **sistema de origem** (o que muda fora do bot: preços, agenda, contas).

  Regra: cada item durável tem dono, gatilho de atualização e regra de frescura.
- **Fraqueza admitida:** cada bot usa **uma única thread longa**, resumida automaticamente perto do limite do contexto. A própria xAI avisa que "a memória não substitui uma fonte autoritativa": o resumo perde detalhes sem avisar.

### Fontes
- Muse:
  - [Axios: Meta debuts Muse](https://www.axios.com/2026/09/08/meta-debuts-muse-personal-ai-agent)
  - [TechCrunch](https://techcrunch.com/2026/09/08/meta-debuts-its-muse-ai-agent-will-consumers-trust-it/)
  - [CNBC](https://www.cnbc.com/2026/09/08/meta-personal-ai-agents-public-reckoning-privacy-safety.html)
  - [eesel: como funciona](https://www.eesel.ai/blog/meta-muse-agent)
  - [ALM Corp: guia](https://almcorp.com/meta-muse-complete-guide-personal-ai-agent/)
  - [VM tab e widget de voz](https://www.progressiverobot.com/2026/09/27/muse-agent-dedicated-vm-tab-voice-mode-widget/)
  - [Memeburn: incidente do Marketplace](https://memeburn.com/metas-muse-sent-a-stranger-to-a-users-door-its-permission-settings-explain-why/)
  - [Privacy Guides: sequestro no Mac](https://www.privacyguides.org/news/2026/09/22/metas-muse-ai-assistant-vulnerable-to-hijacking-via-undocumented-setting/)
- dots:
  - [OpenAI: Introducing dots](https://openai.com/index/introducing-dots/)
  - [FAQ de privacidade e segurança](https://help.openai.com/en/articles/20001529-dots-privacy-security-and-safety-faqs)
  - [TechCrunch](https://techcrunch.com/2026/09/29/openai-launches-dots-its-bubbly-agentic-avatar/)
  - [Flavio Copes: deep dive](https://flaviocopes.com/openai-dots/)
  - [Engadget](https://www.engadget.com/2272230/dots-are-openais-new-personal-agents-and-soon-youll-be-able-to-control-several-of-them/)
- Grok Bot:
  - [docs.x.ai: Skills e rotinas](https://docs.x.ai/grok-bot/skills-routines-and-automations)
  - [xAI: Designing Grok Bot](https://x.ai/news/designing-grok-bot)
  - [Layer3: teach-a-task](https://www.layer3labs.io/guides/grok-bot-teach-a-task)
  - [Mapa de memória](https://x.com/alphabatcher/article/2096550148201435621)
  - [Pesquisa sobre a janela de contexto](https://github.com/matteoantoci/firstmate/blob/master/research/grok-bot-context-window.md)

## 3. Comparação direta

| Capacidade | Muse | dots | Grok Bot | **Talos hoje** |
|---|---|---|---|---|
| Computador próprio sempre ligado | Secure VM | VM na nuvem | VM na nuvem | ✅ VPS própria (só tailnet) |
| Navegador visível + assumir | ✅ | ✅ | ✅ | ✅ Tela + takeover |
| Guardião separado | Sentinel | — | revisão automática | ✅ Sentinela (regras + egress + snapshot + Jev) |
| Aprovações | com escopo | "o que pode fazer sozinho" | Require / Always Allow | ⚠️ só por ação (concessão única) |
| Credenciais sem o agente ver | cofre + agente pausado | — | — | ✅ cofre + `vault_fill` + takeover |
| Conversas separadas por assunto | side chats | 1 dot = 1 objetivo | 1 bot = 1 papel | ❌ 1 conversa por canal (rotação diária) |
| Gestão de contexto | memória + side chats | notas próprias | resumo automático (com perdas) | ⚠️ rotação diária determinística |
| Memória visível e editável | Memory/Soul | notas | memória aprendida | ⚠️ existe (`memory_facts`, `memoria/`), mas não no app |
| Fotos e documentos | ✅ | ✅ | ✅ | ❌ |
| Voz | widget de chamada | chamada | — | ⚠️ só ditado no app |
| Aprender por demonstração | — | "ensinar" | teach-a-task | ❌ |
| Proatividade | — | pesquisa proativa | rotinas | ✅ briefing, monitor, follow-ups, organização; ⬜ objetivos |
| Canais | app, web, WhatsApp | ChatGPT, SMS, Slack, Teams, voz | desktop, iOS | app (PWA) + Telegram |
| Custo para o Lucas | US$ 0–100/mês | plano Pro | SuperGrok Heavy | a assinatura Pro que já tem + VPS |

## 4. Propostas

### E1 · Conversas por assunto ("Assuntos") — prioridade 1

**Problema.** A conversa principal guarda tudo do dia: a conta da água, o restaurante, a conversa leve. Os assuntos misturam-se e o contexto cresce sem controle. A rotação diária (ADR-010) corta por data, não por assunto.

**Modelo mental** (Muse + dots, evitando a fraqueza do Grok):
- **Talos (principal):** a relação contínua. Conversa leve, perguntas rápidas, o que atravessa tudo. É **curta por desenho**: conhece a lista de assuntos, não o conteúdo deles.
- **Assunto:** um espaço por tema, por exemplo "Conta da água — EPAL" ou "Reserva jantar sábado".
  - Toda tarefa é um assunto.
  - Um assunto também pode ser só conversa, sem tarefa (ex.: "Ideias para as férias").
- **Memória partilhada:** os fatos duráveis ("o meu contador é o João") vão para a memória e valem em todos os assuntos. Os detalhes de um assunto ficam no **ledger do assunto**.

**Como funciona:**
1. **Roteamento automático, barato e visível.** Cada mensagem passa pelo Jev, que **não gasta assinatura**. Ele vê a mensagem e a lista de assuntos ativos (título + linha de estado) e escolhe uma de três opções:
   - principal;
   - assunto existente;
   - assunto novo.

   A resposta mostra sempre a etiqueta **📁 Conta da água**, com um botão **"Mover"** para corrigir. Abaixo da confiança mínima, a mensagem vai para a principal, e esta pode chamar `thread_open`.
2. **No app:**
   - a Conversa ganha uma gaveta **Assuntos**, com o Talos no topo e os assuntos por atividade recente;
   - dentro de um assunto, você fala diretamente com ele, sem passar pela principal (o `task_continue` deixa de ser necessário);
   - o assunto mostra a conversa e a linha do tempo da tarefa: passos, aprovações, prints.
3. **No Telegram:**
   - responder (reply) a uma mensagem de um assunto envia para esse assunto;
   - comandos `/assuntos`, `/novo <título>` e `/arquivar`.

   Os tópicos em chats privados com bots existem (Bot API 9.x), mas tiveram bugs e uma regressão em maio de 2026 (Bot API 10.0). Ficam como opção para depois de testar.
4. **Contexto sob controle (orçamento por sessão):**
   - cada assunto tem a sua sessão do SDK;
   - o runtime mede os tokens de entrada de cada execução (`ResultMessage.usage`);
   - acima de um teto (ex.: 60 mil tokens no Pro), ou depois de X horas parado, o assunto **recomeça numa sessão nova** a partir do seu ledger. Não usamos o resumo automático do CLI, porque perde detalhes sem avisar;
   - a principal também roda por orçamento, não só por dia.
5. **Ledger do assunto:** a fonte de verdade, em vez da transcrição.
   - É estruturado: objetivo, fatos, decisões, pendentes, próximo passo e ligações (threads de email, aprovações, ficheiros).
   - É atualizado pelo agente (`ledger_update`) e por eventos determinísticos (aprovação decidida, resposta recebida).
   - Ao recomeçar, a sessão nova recebe a persona, o ledger e os fatos relevantes da memória (`memory_search`). Os dados autoritativos (Gmail, Agenda) são relidos, nunca confiados à memória, seguindo a lição do Grok.
6. **Fim de vida:**
   - um assunto com a tarefa concluída arquiva sozinho em 7 dias;
   - o ledger continua pesquisável, então "lembra da conta da água?" funciona meses depois;
   - a reflexão noturna propõe promover fatos de um assunto para a memória geral.

**Dados.** Uma tabela `threads` (ou `conversations` estendida) com estes campos:
- `kind` (main/topic/task), `title`, `status` (active/archived);
- `task_id`, `session_id`, `session_tokens`;
- `ledger_json`, `last_activity_at`.

`messages.thread_id` passa a ser obrigatório.

**Custo.**
- O roteamento usa o Jev, sem assinatura.
- As sessões ficam menores, então cada execução gasta menos tokens. No plano Pro isso **poupa** uso.

**Critérios de aceitação:**
- "Conta da água" e "restaurante" no mesmo dia ficam em assuntos diferentes, e nenhum vê a transcrição do outro.
- Uma mensagem ambígua mostra a etiqueta e o "Mover" funciona.
- Um assunto com mais de 60 mil tokens recomeça sozinho e continua a tarefa sem perder decisões.
- Um assunto arquivado volta a abrir com contexto.
- Responder no Telegram a uma mensagem do assunto cai nele.

### E2 · Fotos e documentos — prioridade 2

**Ideia.** Tirar foto da conta da água e dizer "trata disto". O Talos lê a entidade, o valor, a referência e a data limite, cria o assunto, põe um lembrete na agenda e propõe os passos. **Pagar continua a ser você**, porque cartão e homebanking são takeover.

**Como funciona:**
- **Entrada:**
  - Telegram: foto, documento ou PDF (até 20 MB, o limite da Bot API);
  - app: botão 📷 que abre a câmera ou a galeria (`<input accept="image/*,application/pdf" capture>`), além de colar e arrastar.
- **Pipeline:**
  1. Guardar em `/var/lib/talos/uploads/` (fora do Git, dentro do backup).
  2. **Remover o EXIF**, incluindo o GPS.
  3. Reduzir o lado maior para cerca de 1.568 px.
  4. Associar o ficheiro ao assunto.
- **Visão pela assinatura, sem API à parte.**
  - **Opção A, recomendada:** pôr o ficheiro no workspace do agente (`uploads/<assunto>/…`) e dizer "o Lucas enviou uma foto: …". O agente usa a ferramenta `Read`, que no Claude Code lê imagens e PDFs. Não muda nada no runtime.
  - **Opção B:** mandar a imagem como bloco `image` na entrada em streaming do SDK (`query(AsyncIterable[...])`). É o plano B se a A não servir.
  - Um *spike* de 30 minutos no servidor decide qual usar.
- **Segurança:**
  - imagem e PDF são **conteúdo externo não confiável**, porque uma foto pode trazer texto com instruções. Valem as mesmas regras do email;
  - números de cartão numa foto: o Talos não os transcreve nem guarda, por regra da persona e com verificação no egress;
  - as fotos só saem do servidor para a inferência da Anthropic, como todo o resto.
- **App:** cada assunto mostra os seus ficheiros (miniaturas).
- **Áudio no Telegram:** o Claude não ouve áudio. Fica como opção posterior com **whisper.cpp local** na VPS, sem enviar para terceiros.

**Critérios de aceitação:**
- Foto de uma conta → resumo com valor e data limite → assunto criado → lembrete na agenda.
- O EXIF é removido.
- Um PDF de várias páginas é lido.
- Uma foto com "ignore as instruções…" escrito não muda o comportamento.

### E3 · Memória visível e editável — prioridade 3

Inspirado no Memory/Soul do Muse e no mapa de memória do Grok:
- Uma página **Memória** no app, com três áreas:
  - **Sobre você**: fatos com origem e data, para editar ou apagar;
  - **Estilo**: tom e preferências, vindos da persona e das correções;
  - **Assuntos arquivados**, pesquisáveis.
- O diff da reflexão noturna aparece aí para aprovar item a item.
- Cada informação tem um lugar fixo:

| O quê | Onde vive | Quem atualiza | Frescura |
|---|---|---|---|
| Papel, regras, limites | `workspace/CLAUDE.md` (Git) | o desenvolvimento | por commit |
| Fatos sobre o Lucas | `memory_facts` | o agente propõe, o Lucas aprova | revisão mensal |
| Estado de um assunto | ledger do assunto | o agente e os eventos | contínua |
| Método repetível | skills | o Git e as skills aprendidas (E6) | por versão |
| Rotinas | `schedules` | `schedule_create` | — |
| Ficheiros | `workspace/` e `uploads/` | o agente e o Lucas | — |
| Emails, agenda, contas | sistema de origem (Google, sites) | **reler sempre** | nunca confiar na memória |

- **Correções que ficam (Grok):** quando você corrige o Talos ("não, assina só Lucas"), ele propõe guardar a correção como preferência, que você aprova com um toque.

### E4 · Aprovações com escopo — prioridade 4

Hoje cada passo sensível pede um cartão. Proposta inspirada no Muse e no Grok:
- No cartão, além de **Aprovar só isto**, aparece **Aprovar para esta tarefa neste site (30 min)**. Isso cria uma concessão ligada a quatro coisas:
  - **destino:** o host;
  - **propósito:** o tipo de ação, como preencher ou submeter;
  - **tarefa;**
  - **validade:** tempo e número de usos.
- **Nunca vale para:**
  - pagamentos e compras;
  - destinatários novos;
  - dados pessoais para um host novo;
  - senhas e cartões (que continuam a ser takeover);
  - nada que as regras inegociáveis proíbam.
- **Regras pessoais** no app ("Sempre pedir para X" / "Pode fazer Y sozinho"):
  - **endurecer** é sempre permitido;
  - **afrouxar** só é possível dentro de uma lista fechada de ações N1.

  Isto segue a regra do Grok: "Require Approval vence".
- **Lição do Muse (Marketplace):** negociações e vendas exigem **limites explícitos aprovados antes**, como preço mínimo e o que se pode partilhar. Além disso, **qualquer compromisso com terceiros gera aviso imediato**, não no fim do dia.

### E5 · Modo voz no app — prioridade 5

- Um **widget de chamada** compacto, como o do Muse: você fala e o Talos responde em voz, com o mascote a "falar".
- O trabalho continua na Tela enquanto você fala.
- Tecnologia:
  - reconhecimento pela Web Speech API do Chrome (já usada no ditado);
  - resposta com `speechSynthesis` numa voz pt-BR.
- Nota de privacidade: no Android, o reconhecimento passa pelos servidores do Google, e isso será dito em Ajustes.
- O texto das respostas em voz é mais curto (estilo próprio na persona).

### E6 · Ensinar uma tarefa — prioridade 6

Inspirado no teach-a-task do Grok:
1. Na Tela, em vez de só assumir, você toca **Gravar demonstração**.
2. Durante o takeover, o Talos regista os passos por CDP: navegação, cliques e **nomes** dos campos, **nunca valores**, e nunca senhas.
3. Com isso gera um **rascunho de skill**: entradas, passos, verificações, pontos de aprovação e falhas.
4. Você revê o rascunho no app.
5. O Talos faz uma execução de teste acompanhada antes de a skill poder ser agendada.

Cuidado de engenharia: o `deploy.sh` sincroniza `workspace/` com `--delete`. As skills aprendidas têm de viver **fora** do diretório que vem do Git, por exemplo `/srv/talos/workspace/.claude/skills/aprendidas-*`, excluído do rsync. Se não, a atualização seguinte apaga-as.

### E7 · Objetivos e proatividade (a F6 original, reenquadrada)

- **Objetivos** (`goals`) com check-ins agendados. Cada objetivo é um assunto de longa duração, ao estilo de "um dot por objetivo".
- **Pesquisa proativa leve**, como nos dots: uma vez por semana, para cada objetivo ativo, o Talos procura algo útil (preço, prazo, alternativa) e só fala se encontrar. Fica dentro do teto diário e prefere o Jev ao Claude.
- `config/mcp.yaml` para ligar servidores MCP extra, sempre atrás da Sentinela. É a nossa resposta às "4.000 integrações": ligamos só o que o Lucas usa.

### Não fazer agora (e porquê)

| Ideia | Quem tem | Porque não agora |
|---|---|---|
| Ligações telefónicas para empresas | dots | Exige operadora (ex.: Twilio), voz sintética, regras de gravação e consentimento em Portugal, e custo. Revisitar depois do E5. |
| WhatsApp como canal | Muse | Exige a API Business da Meta, um número próprio e custos. O Telegram já cobre. |
| Vários agentes com nome | dots, Grok | Um Talos com assuntos é mais simples. Quem testou o Grok queixa-se de "fazer malabarismo com agentes". |
| Milhares de integrações | dots | O MCP sob demanda (E7) cobre o que importa, com a Sentinela à frente. |
| Óculos e wearables | Muse | Fora do âmbito. |

## 5. Roteiro

| Ordem | Fase | Entregas | Esforço | Depende de |
|---|---|---|---|---|
| 1 | **F6a · Assuntos** | E1 completo: modelo de dados, roteador Jev, ledger por assunto, orçamento de sessão, UI de assuntos no app, reply no Telegram, migração da conversa atual para "Talos (principal)" | Grande | — |
| 2 | **F6b · Fotos e documentos** | E2: spike de visão, upload no app e no Telegram, EXIF, ficheiros por assunto | Médio | F6a (associar a assuntos) |
| 3 | **F6c · Memória visível** | E3: página Memória, diff da reflexão aprovado no app, correções que ficam | Pequeno/Médio | F6a |
| 4 | **F6d · Objetivos + MCP** | E7 | Médio | F6a |
| 5 | **F7 · Endurecimento** | Teste de restauração, simulação de alertas, testes de injeção com imagens e roteamento, revisão do `SECURITY.md` | Médio | F6a–d |
| 6 | **F8 · Aprovações com escopo + voz** | E4 + E5 | Médio | F7 |
| 7 | **F9 · Ensinar uma tarefa** | E6 | Grande | F8 |

Cada fase segue as regras de sempre:
- ADR antes de codificar;
- testes offline com fakes;
- commits pequenos;
- verificação no servidor com o Lucas, um passo de cada vez;
- `PROGRESS.md` e `LEDGER.md` atualizados.

## 6. Perguntas para o Lucas

Todas têm um padrão, para não bloquear.

1. **Telegram:** usar responder (reply) e etiquetas para os assuntos (padrão), ou tentar os tópicos dentro do chat com o bot? Os tópicos são mais bonitos, mas tiveram bugs em 2026.
2. **Roteamento:** automático com etiqueta e botão "Mover" (padrão), ou só por comando (`/novo`)?
3. **Fotos:** guardar 90 dias e depois apagar (padrão), ou guardar para sempre, dentro do backup?
4. **Voz:** aceitar que o reconhecimento de voz do app use o serviço do Google (padrão: sim, com aviso), ou só texto?

## 7. Riscos

| Risco | Mitigação |
|---|---|
| O roteador manda a mensagem para o assunto errado | Etiqueta sempre visível + "Mover"; na dúvida, vai para a principal; testes com conversas reais anonimizadas |
| O ledger fica pobre e a tarefa perde o fio ao recomeçar | Eventos determinísticos escrevem no ledger (aprovações, respostas); teste "recomeçar a meio" obrigatório |
| Injeção por imagem | Imagem = conteúdo externo; nada sai sem aprovação; testes com imagens armadilhadas |
| Mais funções = mais uso da assinatura | Sessões curtas por assunto poupam; o Jev faz o roteamento; teto diário mantido |
| As skills aprendidas são apagadas no deploy | Diretório próprio excluído do rsync (E6) |
