# Operação real (Binance ou Bybit) — passo a passo

A conta de **futuros USDT-M** da Binance passa a copiar a agência, na proporção: se a agência tem US$ 1.500 e a sua
conta tem US$ 500, cada posição da conta é 1/3 da posição da agência (somando os 4 times em cada moeda — quando dois
times estão em lados opostos, a conta fica só com a diferença e paga menos taxa).

> ⚠️ Isto é dinheiro de verdade. Os testes mostram que a estratégia funcionou no passado (inclusive de 2018 pra cá),
> mas **o passado não garante o futuro** e houve quedas de até ~50% no caminho. Coloque só o que aceita perder.

## Os 4 modos (faça nesta ordem)

| Modo | O que faz | Precisa de chave? |
|---|---|---|
| **papel** | calcula as ordens e só **anota** (aparecem na janela e no cartão 📝 do escritório) | não |
| **testnet** | manda ordens na **Binance de treino** (dinheiro de mentira, plataforma de verdade) | sim, da testnet |
| **real** | **dinheiro de verdade** | sim, da conta real |
| desligado | nada | — |

Pra trocar de modo: rode o **`9_conectar_binance.bat`** no PC que vai operar.

### 1. Papel (1 a 3 dias)
Rode o `9_conectar_binance.bat` → opção **1**. Ligue a agência e acompanhe as ordens que ela mandaria.

### 2. Testnet (pelo menos 1 a 2 semanas)
1. Entre em **testnet.binancefuture.com**, faça login e pegue o saldo de teste (USDT de mentira).
2. Lá mesmo, em **API Key**, crie uma chave e copie a *API Key* e a *Secret Key*.
3. Rode o `9_conectar_binance.bat` → opção **2** e cole as duas chaves **na janela preta** (a Secret não aparece
   enquanto você digita — é normal). **Nunca mande a chave pra ninguém, nem pro Claude.**
4. Ligue a agência. O cartão **🧪 Binance (testnet)** aparece no topo do escritório e as ordens aparecem na janela.
   Confira no site da testnet se as posições batem.

### 3. Real
1. Na Binance de verdade, transfira **só o valor que vai operar** (ex.: US$ 500) pra carteira de **Futuros USDT-M**.
2. Em **Gerenciamento de API**, crie uma chave com **só "Ativar Futuros"** (e leitura). **NUNCA marque "Ativar
   Saques".** Se puder, restrinja a chave ao **IP do seu PC**.
3. Rode o `9_conectar_binance.bat` → opção **3**, digite **EU ENTENDO O RISCO** e cole as chaves.

## Travas de segurança (já vêm ligadas)

- **Perdeu mais de 15% no dia** → fecha tudo e **para**.
- **Patrimônio abaixo de 50% do que começou** → fecha tudo e **para**.
- **Teto de exposição**: as posições somadas nunca passam de 4× o patrimônio.
- **Stop de emergência NA BINANCE** a 20% contra cada posição: funciona **mesmo com o PC desligado**.
- **⛔ PARAR TUDO**: botão vermelho no cartão da Binance, no escritório (fecha tudo a mercado). Também dá pra criar o
  arquivo `dados/PARAR_REAL`. Depois de parada, só volta quando você clicar em **Retomar**.

Os números ficam em `conta_binance` no `config.json` (`perda_max_dia_pct`, `piso_pct`, `stop_emergencia_pct`, `max_exposicao_x`).

## Mais de um PC

- A chave fica só em `dados/binance.json` do PC onde você conectou — **não vai pro GitHub nem pra nuvem**.
- Só opera o PC onde você rodou o `9_conectar_binance.bat`. Se quiser operar do trabalho **e** de casa, conecte nos
  dois — mas deixe a agência aberta em **um por vez** (é a mesma regra da sincronia).
- Com todos os PCs desligados, a conta **fica parada com as posições abertas**, protegida só pelo stop de emergência
  (20%). Ao ligar de novo, a agência recupera as velas perdidas e ajusta a conta. Pra dinheiro de verdade, o ideal é
  um PC que fique ligado — ou o servidor (veja `SERVIDOR.md`).

## Bybit (pra quem está no Brasil e a Binance bloqueou futuros)

1. Na Bybit, deixe na **Conta Unificada** só o valor que vai operar (em USDT).
2. **API → Criar nova chave → Transação API**, "Leitura e gravação". Permissões: **só** *Trading Unificado → Contrato →
   Ordens* e *Posições*. **Nada** de Ativos, Transferência ou Saque. Restrinja ao IP do PC que vai operar.
3. Rode o `9_conectar_binance.bat` → corretora **2 (Bybit)** → modo **3 (real)** → `EU ENTENDO O RISCO` → cole as chaves.
4. Pra treinar antes: no site da Bybit ligue o **Demo Trading**, crie a chave lá e use o modo **2 (treino)**.

Na Bybit o stop de emergência é o **stop loss da própria posição** (aparece na posição, no app), a 20% do preço.
