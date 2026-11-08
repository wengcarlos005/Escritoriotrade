# 🏢 Agência de Trade — Liga de 5 times, Escola de Traders, Escritório e o Claude como gerente

Robôs de cripto **simulados**: preços reais da Binance e **dinheiro de mentira**.
A **Escola de Traders** testa 15 estratégias inspiradas nos traders mais famosos do mundo, de forma honesta.
As **5 melhores viram times** de uma liga. Toda semana o melhor time vira o **titular** (o que operaria com
dinheiro real no futuro) e os outros ficam na reserva. O **Claude** é o gerente: relatório diário e chat.

> ⚠️ Simulação educativa. Trade é risco: dá pra perder e não existe lucro garantido.
> Resultado passado não garante o futuro. Nada aqui é recomendação de investimento.

---

## 1. Instalar (uma vez)

1. **Python 3.10+**: https://www.python.org/downloads/ — no instalador, **marque “Add python.exe to PATH”**.
2. **Gerente (opcional, recomendado):** dois cliques em `3_instalar_gerente.bat` (ou `pip install anthropic`).
   Depois cole sua chave de API na aba 🧠 Gerente do painel (o passo a passo aparece lá).

## 1.1 Instalar e atualizar pelo GitHub

O projeto mora em https://github.com/wengcarlos005/Escritoriotrade (privado).

- **Primeira vez:** instale o Git (https://git-scm.com/download/win, tudo padrão). Coloque o
  `instalar_do_github.bat` na pasta onde quer a agência (se tiver a pasta antiga `agencia-de-trade`, ao lado
  dela) e dê dois cliques. Ele baixa tudo na pasta `Escritoriotrade` e copia seus dados da pasta antiga.
- **Atualizar:** feche a agência e dê dois cliques em `atualizar.bat`. Pronto.
- **Seus dados nunca vão pro GitHub nem são apagados:** a pasta `dados/` (temporada, chave do gerente,
  histórico) e o seu `config.json` ficam só no seu PC.

## 2. Usar (Windows: dois cliques)

| Arquivo | O que faz |
|---|---|
| `1_rodar_escola.bat` | A escola faz as provas e mostra o boletim (≈ 1 minuto; o histórico já vem junto) |
| `2_ligar_agencia.bat` | Liga a liga ao vivo e abre o **Escritório** no navegador. **Deixe a janela aberta** |
| `3_instalar_gerente.bat` | Instala a biblioteca do Claude |
| `4_so_abrir_painel.bat` | Só abre o escritório/painel, sem ligar os robôs |
| `5_testar_gerente.bat` | Testa a conexão com o Claude e mostra o motivo exato se falhar |
| `atualizar.bat` | Baixa a versão mais nova do GitHub (feche a agência antes) |

No navegador (http://127.0.0.1:8000): **🏢 Escritório** (planta vista de cima: sala do titular, mesas dos times da reserva, escola, gerência e lounge — clique num trader pra ver o que falta pra ele comprar),
**📊 Visão geral** (classificação, times, rodadas), **🎓 Escola** (boletim e botão de nova temporada) e **🧠 Gerente**.

## 2.1 Como funciona a liga
- **5 times = os 5 melhores alunos da escola.** Cada time tem **5 traders** (BTC, ETH, SOL, BNB, XRP),
  com **US$ 100 de mentira** cada, todos usando a estratégia do time.
- **Rodada toda segunda-feira, 00:00** (a 1ª depois de uma semana inteira). Pontuação = retorno das
  **últimas 4 semanas** − metade da maior queda no período. O 1º vira **🏆 titular**; os outros, **reserva**.
  (Uma semana sozinha é ruído demais — por isso olhamos 4.)
- **Bebês traders:** a cada **R$ 500 de lucro de um time**, nasce um bebê nesse time, pago só com o lucro,
  operando uma moeda nova (ADA, DOGE, LINK, AVAX, LTC). Até 5 bebês por time. Quando o 1º bebê de um time
  chega a R$ 500 de lucro, o CEO dá R$ 500 pra cada trader daquele time.
- **Nova temporada:** quando a escola gerar um boletim novo, use o botão na aba Escola pra montar os times
  com o top 5 atualizado (o dinheiro de mentira recomeça).
- **Dinheiro real:** ainda **não** está ligado — de propósito. A estrutura de titular/reserva já está pronta pra isso.

## 3. A Escola de Traders

### Os alunos

| Aluno | Inspiração | Ideia |
|---|---|---|
| 🛰️ Conjunto de Canais | Zarattini, Pagani & Barbon (2025) | Vários rompimentos Donchian votam; posição menor quando a volatilidade sobe |
| 🧭 Momentum de Série Temporal | Moskowitz, Ooi & Pedersen (AQR) | Subiu nos últimos N dias → comprado; caiu → fora |
| 🐢 Tartarugas | Richard Dennis | Rompe a máxima de 20/55 → compra; perde a mínima de 10/20 → sai; stop de 2 ATR |
| 📈 Médias Exponenciais Longas | Ed Seykota | Cruzamento de médias exponenciais longas (ex.: 15/150) |
| 🎩 Acima da Média de 200 | Paul Tudor Jones | Comprado acima da média longa, fora abaixo (com margem contra sinais falsos) |
| 🪜 Análise de Estágios | Stan Weinstein | Entra no “estágio 2”: preço acima da média de 30 semanas subindo |
| 🏆 Molde de Tendência | Mark Minervini | Só ativos em tendência forte, no rompimento; stop curto |
| 🚀 Rompimento de Volatilidade | Larry Williams | Compra quando o preço anda mais que k × a amplitude anterior |
| 🎯 RSI(2) Reversão | Larry Connors | Compra quedas fortes de curto prazo dentro de tendência de alta |
| 🏹 Santo Graal | Linda Raschke | ADX forte + recuo até a média de 20 |
| 🦸 Supertrend | Olivier Seban | Linha de volatilidade que vira de baixa pra alta |
| 🌊 MACD | Gerald Appel | Cruzamento do MACD acima da média de 200 |
| 💥 Aperto e Explosão | Bollinger / John Carter | Bandas apertadas → explosão pra cima |
| 🪃 Bandas de Bollinger | John Bollinger | Compra abaixo da banda inferior, vende na média |
| 🤖 Cruzamento de Médias | (estratégia original) | A primeira versão da agência — fica como “turma de controle” |

### Como é a prova (pra não se enganar)
- **Walk-forward:** 8 provas de 6 meses (fim de 2022 → hoje). Antes de cada prova o aluno estuda
  os 2 anos anteriores; a nota vem só do que ele **nunca viu**.
- **Carteira** BTC/ETH/SOL/BNB, **taxa 0,1% + derrapagem 0,05%** por ordem; também com **custo dobrado**.
- **Deflated Sharpe** (Bailey & López de Prado): desconta a sorte de ter testado muitos alunos.
- **Aprovação:** lucro fora da amostra, Sharpe ≥ 0,6, ganhos/perdas ≥ 1,2, ≥ 30 operações, consistência,
  queda máxima menor que 40%, aguentar custo dobrado e confiança ≥ 90%.
- **Régua:** sempre comparar com **comprar e segurar** e com **DCA semanal** no mesmo período.

### O que o boletim de nov/2026 mostrou
- Quem foi melhor: **seguir tendência em velas diárias/4h** (Seykota, Conjunto de Canais, Tartarugas).
  O 📈 Seykota teve Sharpe 0,94 (comprar e segurar: 0,87) e queda máxima de 30% (comprar e segurar: 65%).
- **Comprar e segurar rendeu mais em %** (+295%) porque o período começa no fundo de 2022. Os robôs
  ganham em **risco** (quedas bem menores), não em retorno bruto, num mercado tão altista.
- Reversão de curto prazo e velas de 1h **perderam** depois das taxas — como a pesquisa previa.
- **Ninguém passou em todos os critérios** (a confiança estatística ficou abaixo de 90%). Os times são
  formados pelas maiores notas (com `liga.so_alunos_aprovados: true`, só aprovados entram).

## 4. Configuração (`config.padrao.json` + o seu `config.json`)
Os padrões ficam em `config.padrao.json` (vem nas atualizações). Pra mudar algo, crie um `config.json` com **só** o que quer mudar — por exemplo `{"mascote": {"nome": "Thor"}}` — ele vale por cima dos padrões e nunca é sobrescrito.

- `liga`: número de times, moedas, US$ por trader, semanas usadas na pontuação, `so_alunos_aprovados`.
- `bebes`: R$ de lucro por bebê, máximo por time, moedas dos bebês, bônus do CEO.
- `humor.muda_tamanho_da_aposta`, `regras.ativo`, `cansaco.ativo`: as regras divertidas do vídeo
  (apostar menos depois de perder, bônus/corte de US$ 50, videogame depois de 3 derrotas).
  Vêm **desligadas** porque **atrapalham** estratégias de tendência, que perdem muitas vezes pouco e ganham
  poucas vezes muito. Ligue (`true`) se quiser igualzinho ao vídeo. O humor aparece de qualquer jeito.
- `mascote`: nome, emoji e frases. `gerente`: relatório automático e intervalo.

## 5. Antes de pensar em dinheiro real
1. Meses de simulação ao vivo com a estratégia escolhida (não dias).
2. Um time titular formado por aluno **aprovado** na escola, e que continue aprovado quando a escola rodar de novo.
3. Valores pequenos que você aceita perder; chave da Binance **sem permissão de saque** e com IP restrito.
4. Este projeto ainda **não envia ordens reais** — de propósito.

## 6. Referências usadas
- freqtrade, nautilus_trader, QuantConnect Lean, vectorbt, jesse, hummingbot (frameworks open-source).
- Liu & Tsyvinski (2021) *Risks and Returns of Cryptocurrency*; Zarattini, Pagani & Barbon (2025)
  *Catching Crypto Trends*; Moskowitz, Ooi & Pedersen (2012) *Time Series Momentum*;
  Bailey & López de Prado (2014) *The Deflated Sharpe Ratio*; Hudson & Urquhart (2021).
- Regras originais das Tartarugas (Curtis Faith), Ed Seykota, Larry Williams, Linda Raschke, Mark Minervini, Stan Weinstein, Larry Connors.
