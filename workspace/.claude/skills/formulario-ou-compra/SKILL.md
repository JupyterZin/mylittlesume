---
name: formulario-ou-compra
description: Preencher um formulário ou fazer uma compra no navegador do Talos (a Tela). Use
  quando a empresa só aceitar formulário ou quando o Lucas pedir uma compra/encomenda online.
---
# Formulário ou compra
1. Navegue e leia a página (browser_snapshot). Descreva sempre o elemento em `element`
   ("Campo Nome", "Botão Seguinte") ao clicar ou escrever.
2. Preencha só campos não sensíveis. Dados pessoais: vault_fill(selector, key) — pede aprovação.
3. Antes de submeter, pagar ou confirmar: tire screenshot e escreva um resumo (total, vendedor,
   prazo de entrega, política de devolução). O clique final é pausado para o Lucas aprovar.
4. Pagamento: NUNCA digite dados de cartão. Se o site já tiver meio de pagamento guardado e
   bastar confirmar, o clique final acontece depois da aprovação. Senão, peça takeover.
5. Login, captcha ou 2FA: peça ao Lucas para assumir a Tela.
