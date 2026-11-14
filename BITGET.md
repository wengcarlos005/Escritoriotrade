# 🟢 Bitget — do zero até a agência operando (passo a passo)

A agência já vem configurada para a **Bitget**: as taxas da simulação são as dela, e é a corretora que usamos
para operar com dinheiro de verdade. Este guia é para quem **nunca usou a Bitget**. Vá na ordem, com calma.

> ⚠️ **Antes de tudo**
> - Comece com pouco dinheiro, que você aceita perder inteiro. Futuros com alavancagem é o jeito mais rápido de perder.
> - A agência **não precisa** de dinheiro real: ela funciona 100% simulada. Este guia é opcional.
> - **Nunca mande suas chaves, senha ou códigos para ninguém** — nem para amigos, nem para "suporte" no WhatsApp,
>   nem para o Claude. A Bitget nunca pede isso.
> - Confira nos termos da Bitget se ela atende o seu país, e declare os ganhos no Imposto de Renda (ganho em
>   corretora no exterior — fale com um contador).
> - Os nomes dos botões podem mudar um pouco entre versões do app/site. Se algo estiver diferente, procure o
>   nome parecido.

---

## Por que a Bitget

- Tem **futuros USDT-M** (operar comprado e vendido), que é o que a agência usa.
- Aceita brasileiro e tem **compra de USDT com PIX** (direto ou pelo P2P).
- Tem **API** com stop de emergência na própria corretora (funciona mesmo com o seu PC desligado).
- No nosso caso (nov/2026), Binance e Bybit bloquearam futuros para contas do Brasil — a Bitget funcionou.

---

## 1. Criar a conta (10 minutos)

1. Baixe o app **Bitget** (Play Store / App Store) ou entre em **bitget.com**. Confira o endereço: golpistas
   fazem sites parecidos. Prefira digitar o endereço em vez de clicar em links.
2. **Cadastrar** → e-mail (ou celular) → crie uma **senha forte** (que você não usa em nenhum outro lugar).
3. Confirme o código que chega no e-mail/SMS.
4. **Verificação de identidade (KYC)**: no app, toque no seu perfil (canto de cima) → **Verificação de identidade**.
   Tenha em mãos o **RG ou CNH**, tire foto do documento (frente e verso) e faça a **selfie** que o app pede.
   Costuma aprovar em minutos ou algumas horas. Sem ela você pode não conseguir depositar/sacar.

## 2. Proteger a conta (5 minutos — não pule)

1. Perfil → **Segurança** → ative a **Autenticação de 2 fatores (Google Authenticator)**. Baixe o app
   *Google Authenticator* no celular, escaneie o código e **anote a chave de recuperação num papel**.
2. Ative o **código antiphishing** (uma palavra sua): todo e-mail verdadeiro da Bitget vai mostrar essa palavra.
3. Se aparecer a opção de **lista de endereços de saque confiáveis** (whitelist), ative.

## 3. Colocar dinheiro (USDT)

A agência opera com **USDT** (um "dólar digital"). Você compra USDT com reais. Há dois caminhos — use o que
aparecer para você:

### Caminho A — Depositar com PIX direto (se aparecer)
1. No app: **Ativos** (ou *Carteira*) → **Depositar** → escolha **BRL / PIX** (ou "Comprar cripto" → PIX).
2. Digite o valor em reais, gere o PIX e pague pelo app do seu banco.
3. Depois, converta os reais em **USDT** (o próprio app oferece "Converter" / "Comprar USDT").

### Caminho B — Comprar USDT no P2P com PIX (sempre funciona)
O P2P é você comprando USDT de outra pessoa, com a Bitget segurando o USDT até o pagamento ser confirmado.
1. No app: **Comprar cripto** → **P2P** (ou *Negociação P2P*) → aba **Comprar** → moeda **USDT**,
   pagamento em **BRL** e filtre por **PIX**.
2. Escolha um anunciante com **muitas negociações** (ex.: 200+) e **taxa de conclusão alta** (95%+). Compare o
   preço: ele costuma ser um pouco acima do dólar (é o "spread" do vendedor).
3. Toque em **Comprar**, digite o valor em reais e confirme. Abre um chat do pedido.
4. Pague pelo **PIX para a chave que aparece NO PEDIDO**, pelo app do seu banco, **no seu nome**, dentro do prazo.
5. Volte no pedido e toque em **"Já paguei"** (ou *Transferido, notificar vendedor*).
6. Quando o vendedor confirmar, o USDT cai na sua conta (geralmente minutos).

> 🚫 **Golpes comuns no P2P:** nunca pague fora da plataforma, nunca negocie pelo WhatsApp/Telegram, nunca marque
> "já paguei" sem ter pago, e desconfie de quem pede para você escrever "cripto" ou "USDT" na descrição do PIX.
> Se der problema, abra uma **reclamação (apelação)** dentro do pedido.

### 3.1 Mandar o USDT para os Futuros
O USDT comprado cai na carteira **Spot** (ou *Financiamento*). A agência opera na carteira de **Futuros USDT-M**:
1. **Ativos** → **Transferir**.
2. **De:** Spot (ou Financiamento) → **Para:** **Futuros USDT-M**.
3. Moeda **USDT**, valor (ex.: tudo) → **Confirmar**. É grátis e instantâneo.

## 4. Criar a chave de API (o "acesso" da agência)

A chave deixa a agência abrir e fechar posições na sua conta. **Ela NÃO pode sacar** (você não vai dar essa
permissão).

1. Pelo **site** (bitget.com, mais fácil que pelo app): clique no perfil → **Gerenciamento de API**
   (*API Management*) → **Criar API** → **Chave de API gerada pelo sistema** (*System-generated*).
2. **Nome/observação:** `agencia`.
3. **Passphrase:** invente uma senha só para essa chave (ex.: 10+ letras e números) e **anote**. A agência vai
   pedir.
4. **Permissões:** marque **leitura e escrita** em **Futuros** (Contrato) → **Ordens** e **Posições**.
   **NÃO marque** Saque (*Withdraw*), Transferência, Spot, Margem, Copy trading nem nada mais.
5. **IP:** se você sabe o IP da internet do PC que vai deixar a agência ligada, vincule (mais seguro). Para
   descobrir: abra **meuip.com.br** nesse PC. Se a sua internet muda de IP às vezes, pode deixar sem — mas aí
   a chave pode expirar depois de um tempo e você cria outra.
6. Confirme com o código do Google Authenticator / e-mail.
7. Vão aparecer **3 coisas**: **API Key** (chave de acesso), **Secret Key** (chave secreta) e a **Passphrase**
   (a que você criou). **Copie para um bloco de notas no seu PC.** A Secret só aparece uma vez — se perder,
   apague a chave e crie outra.

## 5. Ligar a agência na Bitget

No PC (com a agência fechada — Ctrl+C na janela preta):

1. `atualizar.bat` (se você instalou pelo Git) para ter a versão mais nova.
2. Dois cliques em **`9_conectar_binance.bat`** (ele serve para as 3 corretoras):
   - corretora: **3** (Bitget)
   - modo: **3** (real) — ou **1** (papel) se quiser só ver as ordens que ela mandaria, sem chave nenhuma
   - digite: `EU ENTENDO O RISCO`
   - cole a **API Key** (clique com o botão direito na janela para colar) → Enter
   - cole a **Secret Key** → Enter (não aparece nada enquanto cola — é normal)
   - cole a **Passphrase** → Enter (também não aparece)
3. Deve aparecer: **"✅ Conectado na Bitget (real). Patrimônio: US$ …"**.
4. Dois cliques em **`2_ligar_agencia.bat`**.

### Testar sem dinheiro (recomendado)
Pode fazer tudo isso **com a conta zerada**: a agência conecta, tenta mandar as ordens e a Bitget **recusa por
falta de saldo**. No escritório aparece "🟡 sem saldo — ordens recusadas pela Bitget" e no balão dos traders
"Não aberta na Bitget". Isso prova que a chave, a passphrase e as permissões estão certas. A simulação não muda.

## 6. Depois de depositar

1. Em até 1 minuto a agência abre as posições na Bitget, **na proporção** da agência (se a agência tem
   US$ 2.000 e a sua conta US$ 500, cada posição é 1/4).
2. No escritório, cartão **💰 Bitget (REAL)**: clique em **⚖️ Igualar ao saldo** para a agência ficar do
   tamanho da sua conta (copia 1 pra 1 — mais fácil de comparar).
3. Confira no app: **Futuros → Posições**. Cada posição tem um **stop loss** a ~20% do preço — é o stop de
   emergência, que fica na Bitget e funciona com o PC desligado.

## 7. Travas e botões que te protegem

- **Perdeu mais de 15% num dia** → a agência fecha tudo e para.
- **Caiu abaixo de 50% do que começou** → fecha tudo e para.
- **⛔ PARAR TUDO** (no escritório): fecha todas as posições na hora. Para voltar: **Retomar**.
- **💸 Lembrete de saque:** quando a conta sobe 50% (ou passa 1 mês no lucro), o escritório sugere sacar uma
  parte do lucro. Depósitos e saques são percebidos sozinhos (as travas se ajustam).

## 8. Tirar o dinheiro (sacar para o seu banco)

1. **Ativos → Transferir:** de **Futuros USDT-M** para **Spot**.
   (Se tiver posição aberta, saque só a parte livre — ou aperte ⛔ PARAR TUDO antes.)
2. **P2P → aba Vender → USDT → PIX:** escolha um comprador com bom histórico, informe a **sua** chave PIX
   (no seu nome) e espere o dinheiro cair no banco. **Só confirme "recebi" depois de ver o PIX na sua conta
   bancária.** (Se aparecer saque direto em BRL/PIX no app, também serve.)

## 9. Problemas comuns

| Mensagem / situação | O que fazer |
|---|---|
| `Não consegui entrar na conta` ao conectar | Confira se copiou as 3 partes inteiras, sem espaço. Recrie a chave se preciso |
| Erro de **assinatura / passphrase** | A passphrase é a que **você criou** na chave (não é a senha da conta) |
| Erro de **permissão** (`Incorrect permissions, need future order write permissions`) | A chave está sem permissão de mandar ordem em Futuros. Na Bitget: Gerenciamento de API → **Editar** a chave → **Futuros → Ordens** e **Posições** com **leitura e escrita** → salvar. Não precisa reconectar a agência |
| Erro de **IP** | O IP do PC mudou. Atualize o IP na chave (ou crie uma sem vínculo de IP) |
| Ordem recusada por **saldo** | Normal com a conta zerada. Depois de depositar, confira se o USDT está em **Futuros USDT-M** (não no Spot) |
| Quero parar tudo agora | Botão **⛔ PARAR TUDO** no escritório, ou crie o arquivo `dados/PARAR_REAL` |

Dúvidas? Mande um print da janela preta (sem as chaves aparecendo) para quem te passou a agência.
