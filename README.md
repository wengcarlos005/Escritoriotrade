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
- **Já tem a pasta instalada (do zip)?** Coloque o `conectar_ao_github.bat` **dentro** dela e dê dois cliques: a pasta passa a
  atualizar pelo GitHub, sem perder nada.
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
| `6_ver_resultados.bat` | Mostra um resumo em texto e salva em `dados/resumo_para_o_claude.txt` (pra mandar pro Claude) |

No navegador (http://127.0.0.1:8000): **🏝️ Escritório 3D** (uma ilha ao ar livre: deck do time titular, mesas com guarda-sol dos times da reserva, escola, food truck do café, quiosque do gerente, lago e o Rex — arraste pra girar, roda/pinça pra zoom, clique num trader pra ver o que ele está fazendo e pensando; a versão pixel-art antiga continua em `/pixel`),
**📊 Visão geral** (classificação, times, rodadas), **🎓 Escola** (boletim e botão de nova temporada) e **🧠 Gerente**.

## 2.1 Como funciona a liga
- **💹 Tudo em FUTUROS (simulado):** os robôs operam futuros perpétuos, **comprando (LONG) e vendendo (SHORT)**.
  O short usa o mesmo aluno "de cabeça pra baixo": o sinal de compra no preço invertido vira sinal de venda.
  Custos de futuros: taxa 0,05% (a mercado), 0,02% (ordens limitadas da grade) e **funding** a cada 8h
  (comprado paga, vendido recebe). No seu PC, se a API de futuros da Binance responder, a agência usa o **preço do
  contrato e o funding reais**; se não, usa o preço à vista e o funding médio (o escritório mostra qual está valendo).
- **🧠 Julgamento de cada operação (risco fixo + alavancagem decidida na hora):**
  1. **Risco fixo:** se o stop bater, o robô perde no máximo **X% do caixa**, conforme o **perfil** (`futuros.perfil`):
     `moderado` = 2%; **`agressivo` = 4% + pirâmide (padrão)**; `muito_agressivo` = 6% + pirâmide.
     Na escola de futuros (4 anos), o 📈 Seykota fez: moderado +11%/ano (queda máx −14%); agressivo **+35%/ano
     (queda −36%)**; muito agressivo +45%/ano (queda −48%). Mais ganho sempre vem com quedas maiores no caminho.
  2. **Tamanho** = risco ÷ distância do stop. Stop longe → posição menor; stop perto → maior.
  3. **Alavancagem** = a maior que deixa o preço de liquidação **além do stop**, com um teto que depende da
     **confiança** (o que a escola achou + o que ele aprendeu ao vivo) e da **tendência de 200 dias** (contra a
     tendência: metade do risco e metade do teto). Máximo 10x. Cada posição mostra o "porquê".
  Assim a alavancagem é consequência do risco, não uma aposta — e liquidação vira raridade (só em saltos de preço).
- **➕ Pirâmide (regra das Tartarugas):** quando a operação anda a favor meia distância do stop, o robô soma mais uma
  unidade (metade do risco de uma entrada), até 4 unidades. Só aumenta o que já está ganhando — é o que faz as poucas
  operações boas renderem muito.
- **📚 Aprendizado:** cada operação fechada é anotada em **R** (resultado ÷ risco planejado; −1R = bateu o stop).
  A confiança do time vai se misturando com esses resultados aos poucos (com 20 operações, metade escola e metade
  ao vivo), pra não confundir sorte com habilidade. O robô também aprende se vale operar contra a tendência de
  200 dias. E **toda semana a escola reestuda** com os dados mais novos: os times atualizam os parâmetros (quem está
  posicionado troca quando fechar). Tudo isso aparece na aba **🧠 Aprendizado** da Mesa de operações.
- **🤝 Time Comitê:** as 3 melhores estratégias da escola dividindo o mesmo dinheiro (um robô por estratégia e moeda).
  Na escola de futuros caiu menos e ganhou menos que o Seykota sozinho — a liga vai mostrar ao vivo.
- **5 times:** os 4 melhores alunos da escola de futuros + o Time Comitê. Cada time tem **5 traders** (BTC, ETH,
  SOL, BNB, XRP), com **US$ 1.000 de mentira** cada (o Comitê tem 15, com US$ 333 cada).
- **Rodada toda segunda-feira, 00:00** (a 1ª depois de uma semana inteira). Pontuação = retorno das
  **últimas 4 semanas** − metade da maior queda no período. O 1º vira **🏆 titular**; os outros, **reserva**.
  (Uma semana sozinha é ruído demais — por isso olhamos 4.)
- **🏢 A empresa (minigame):** cada funcionário (trader) começa com **US$ 1.000** de mentira. A cada **US$ 50 de lucro
  realizado** (sempre um novo recorde — perdeu, precisa recuperar antes), ele fica com **US$ 20 de bônus** e manda
  **US$ 30 pro caixa do time**. Quando o caixa do time chega a **US$ 500**, o time **contrata um funcionário novo**
  (com esses US$ 500), numa moeda nova (ADA, DOGE, LINK, AVAX, LTC, DOT, TRX, NEAR, ATOM, APT), usando a estratégia do
  time. Até 15 funcionários por time. Tudo configurável em `empresa` no `config.json`.
- **🧮 Mesa de Grade (alta frequência, fora da disputa):** 10 robôs de grade (BTC, ETH, SOL, BNB, XRP, ADA, DOGE, LINK,
  AVAX, LTC), velas de 5 min, US$ 1.000 cada, 5x. Seguem a tendência de 4h (média 20 × 150): em alta montam degraus de
  **compra (LONG)** abaixo do preço; em baixa, degraus de **venda (SHORT)** acima. Cada lote fecha 0,8% a favor (ordem
  limitada, taxa maker 0,02%); se o preço sair 16% contra, fecha tudo e recomeça. **É quem faz a maior parte das
  50–100 operações por dia** (repetindo os últimos 45 dias com o motor de verdade: ~69 operações/dia na mesa, +6,8%).
  Atenção: num teste de 5 anos (aproximado), grades perderam dinheiro — por isso ela fica fora da disputa e é medida
  pelas sprints.
- **🎯 Falta X%:** cada trader mostra quanto o preço precisa subir (pra abrir LONG) ou cair (pra abrir SHORT).
- **📏 Régua:** cada time mostra quanto teria rendido **comprar e segurar as mesmas moedas** no mesmo período.
- **🏃 Sprints de 1 dia:** cada dia (meia-noite a meia-noite, Brasília) é uma sprint. As metas medem **qualidade**,
  não quantidade: lucro médio por operação depois das taxas, bater o "segurar", taxas, queda e liquidações. A agência mede operações, dinheiro girado,
  resultado, taxas pagas e tempo parado de cada time, confere as metas (em `liga.sprint.metas`) e escreve um
  diagnóstico do que melhorar. Com a chave de API, o gerente escreve a retrospectiva com 3 experimentos pra próxima.
  A aba **Laboratório** lista o que já testamos (e o resultado) e os próximos experimentos.
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
- **Carteira** BTC/ETH/SOL/BNB/XRP. No modo futuros (padrão): **LONG e SHORT**, taxa 0,05% + derrapagem 0,02%,
  funding, liquidação e o **mesmo julgamento de risco e alavancagem** do robô ao vivo; também com **custo dobrado**.
- **Comitê:** a escola também mede as 3 melhores juntas, dividindo o dinheiro.
- **Deflated Sharpe** (Bailey & López de Prado): desconta a sorte de ter testado muitos alunos.
- **Aprovação:** lucro fora da amostra, Sharpe ≥ 0,6, ganhos/perdas ≥ 1,2, ≥ 30 operações, consistência,
  queda máxima menor que 40%, aguentar custo dobrado e confiança ≥ 90%.
- **Régua:** sempre comparar com **comprar e segurar** e com **DCA semanal** no mesmo período.

### A escola de futuros (nov/2026)
- Com LONG e SHORT, risco de 2% por operação e alavancagem por julgamento: **📈 Seykota +50% em 4 anos, queda máx −14%,
  Sharpe 0,94**; Momentum +26% (queda −7%); Weinstein +6,5% (queda −3%); Minervini +14% (queda −7%).
- Comprar e segurar: **+256%, com queda de −64%**. Os robôs ganham bem menos num mercado que subiu muito, mas caem bem menos.
- **Comitê** das 3 melhores: +28%, queda −8%, Sharpe 0,91.
- Estratégias rápidas e de reversão continuam perdendo. Ninguém passou em todos os critérios (a confiança estatística é baixa).

### O que o boletim de nov/2026 mostrou (à vista, só comprando)
- Quem foi melhor: **seguir tendência em velas diárias/4h** (Seykota, Conjunto de Canais, Tartarugas).
  O 📈 Seykota teve Sharpe 0,94 (comprar e segurar: 0,87) e queda máxima de 30% (comprar e segurar: 65%).
- **Comprar e segurar rendeu mais em %** (+295%) porque o período começa no fundo de 2022. Os robôs
  ganham em **risco** (quedas bem menores), não em retorno bruto, num mercado tão altista.
- Reversão de curto prazo e velas de 1h **perderam** depois das taxas — como a pesquisa previa.
- **Ninguém passou em todos os critérios** (a confiança estatística ficou abaixo de 90%). Os times são
  formados pelas maiores notas (com `liga.so_alunos_aprovados: true`, só aprovados entram).

## 4. Configuração (`config.padrao.json` + o seu `config.json`)
Os padrões ficam em `config.padrao.json` (vem nas atualizações). Pra mudar algo, crie um `config.json` com **só** o que quer mudar — por exemplo `{"mascote": {"nome": "Thor"}}` — ele vale por cima dos padrões e nunca é sobrescrito.

- `futuros`: `perfil` (`"moderado"`, `"agressivo"` ou `"muito_agressivo"`) — o principal botão de risco. Também dá pra
  escrever direto `risco_por_operacao` (0,04 = 4%) e `piramide` (ou `null` pra desligar), que valem por cima do perfil;
  `alavancagem_max` (10), `fator_contra_tendencia` (0,5), `margem_maxima`, `dados_reais`, `vender_a_descoberto`,
  taxas, funding e a grade (`alavancagem_mesa`, `margem_por_operacao`). `liga.comite`: liga/desliga o Time Comitê.
  `aprendizado`: quantas operações até o ao vivo pesar metade (`operacoes_meio_peso`) e de quantos em quantos dias a escola reestuda.
- `liga`: número de times, moedas, US$ por trader, semanas usadas na pontuação, `so_alunos_aprovados`,
  `sprint.duracao` (`"dia"` ou `"semana"`) e `sprint.metas` (operações, lucro, taxas, queda, liquidações).
- `empresa`: meta de lucro (US$ 50), bônus do funcionário (US$ 20), parte do caixa do time (US$ 30), custo da
  contratação (US$ 500), máximo de funcionários por time e moedas dos contratados. (`bebes` foi desligado.)
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
5. **Futuros com alavancagem é o jeito mais rápido de perder dinheiro de verdade.** Confira se você pode operar
   futuros na sua corretora e no seu país antes de qualquer coisa, e comece sem alavancagem.

## 6. Referências usadas
- freqtrade, nautilus_trader, QuantConnect Lean, vectorbt, jesse, hummingbot (frameworks open-source).
- Liu & Tsyvinski (2021) *Risks and Returns of Cryptocurrency*; Zarattini, Pagani & Barbon (2025)
  *Catching Crypto Trends*; Moskowitz, Ooi & Pedersen (2012) *Time Series Momentum*;
  Bailey & López de Prado (2014) *The Deflated Sharpe Ratio*; Hudson & Urquhart (2021).
- Regras originais das Tartarugas (Curtis Faith), Ed Seykota, Larry Williams, Linda Raschke, Mark Minervini, Stan Weinstein, Larry Connors.
