"""MODELO DE ALUNO NOVO — copie este arquivo com outro nome (sem "_" no começo), ex.: alunos/minha_ideia.py

Como funciona:
  • Cada aluno é uma metodologia de trade. Ele diz QUANDO ENTRAR (entrada) e QUANDO SAIR (saida) olhando as velas.
  • Pra vender (SHORT), a agência usa o MESMO aluno no preço "espelhado" (de cabeça pra baixo) — então você só
    escreve a regra de compra.
  • Toda semana a escola testa o aluno em 8 semestres que ele nunca viu (walk-forward), escolhendo os parâmetros
    da `grade` com os 2 anos anteriores a cada prova. Depois a PROVA DA AGÊNCIA simula ele no escritório (BTC, ETH
    e SOL, velas de 4h, alavancagem pela volatilidade) e compara com o campeão atual.
  • Se ele melhorar a agência de verdade, aparece como candidato na aba 🎓 Escola.

Ferramentas: indicadores.py (ema, sma, rsi, atr, maxima_anterior, minima_anterior, roc, macd, supertrend, adx…)
e os atalhos _ok, cruzou_pra_cima, cruzou_pra_baixo de estrategias.py.
"""
import indicadores as ind_
from estrategias import Estrategia, _ok, cruzou_pra_baixo, cruzou_pra_cima


class MeuAluno(Estrategia):
    id = "meu_aluno"                 # único, sem espaços
    nome = "Nome da metodologia"
    emoji = "🧪"
    inspiracao = "De quem é a ideia"
    descricao = "Explique em uma frase como ele opera."
    params = {"intervalo": "4h", "rapida": 10, "lenta": 50, "stop_atr": 3.0}   # stop_atr = stop inicial em ATRs
    grade = {"intervalo": ["4h", "1d"], "rapida": [10, 20], "lenta": [50, 100]}  # o que a escola testa

    def valida(self, p):
        return p["rapida"] < p["lenta"]

    def indicadores(self, v, p):          # v = velas {'t','o','h','l','c','v'}
        return {"r": ind_.sma(v["c"], p["rapida"]), "l": ind_.sma(v["c"], p["lenta"])}

    def entrada(self, d, v, i, p):        # True = compra no fechamento da vela i
        return cruzou_pra_cima(d["r"], d["l"], i)

    def saida(self, d, v, i, p):          # True = sai no fechamento da vela i (o stop é automático)
        return cruzou_pra_baixo(d["r"], d["l"], i)
