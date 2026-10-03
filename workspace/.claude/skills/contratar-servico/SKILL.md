---
name: contratar-servico
description: Contatar uma empresa para contratar, ativar, alterar ou cancelar um serviço
  (gás, luz, água, internet, seguros, manutenção). Use quando o Lucas pedir para "falar com a
  empresa X" sobre um serviço.
---
# Contratar serviço
1. Identifique empresa e serviço. Sem empresa definida: sugira 2–3 opções, uma linha cada
   (prós e contras), e pergunte.
2. Ache o canal oficial (site oficial → página de contactos). Desconfie de agregadores e
   anúncios. Guarde com contacts_save e source_url da página oficial.
3. Veja na memória (memory_search) e em vault_list_keys o que já existe: morada, NIF,
   código da instalação (CUI no gás, CPE na luz), número de cliente.
4. Rascunho em PT-PT formal com gmail_create_draft: assunto claro, pedido num parágrafo,
   dados com placeholders ({{dados.morada}}, {{dados.nif}}, {{dados.nome_completo}}),
   pedido de confirmação de próximos passos e prazos.
5. propose_action(kind="email.send") com draft_id, to, subject, body e, em reason, por que este
   destinatário (ex.: "email de apoio indicado na página oficial de contactos").
6. Depois do envio (o sistema avisa quando a proposta for executada): confirme que existe
   vigilância da thread (follow-up em 3 dias úteis, no máximo 2) e diga ao Lucas quando espera
   novidades.
7. Só formulário: use o navegador até antes de submeter; o clique final pede aprovação.
   Só telefone: escreva um roteiro de ligação de 5 linhas para o Lucas.
