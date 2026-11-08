"""Histórico de preços guardado no seu PC (pasta dados/historico), atualizado aos poucos.

Baixa uma vez e depois só busca o que falta — a escola de traders usa isso pra estudar.
"""
import gzip
import json
import time
from pathlib import Path

import mercado

PASTA = Path(__file__).resolve().parent / "dados" / "historico"

# Quantos anos de história guardar por intervalo
ANOS = {"15m": 1, "1h": 6.2, "4h": 6.2, "1d": 6.2}


def _arquivo(par, intervalo):
    return PASTA / f"{par}_{intervalo}.json.gz"


def carregar(par, intervalo):
    f = _arquivo(par, intervalo)
    if not f.exists():
        return []
    with gzip.open(f, "rt", encoding="utf-8") as fp:
        return json.load(fp)


def _salvar(par, intervalo, velas):
    PASTA.mkdir(parents=True, exist_ok=True)
    tmp = _arquivo(par, intervalo).with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fp:
        json.dump(velas, fp, separators=(",", ":"))
    tmp.replace(_arquivo(par, intervalo))


def atualizar(par, intervalo, avisar=print):
    """Garante o histórico completo e atualizado. Devolve a lista de velas [t,o,h,l,c,v]."""
    velas = carregar(par, intervalo)
    passo = mercado.INTERVALOS_MS[intervalo]
    agora = int(time.time() * 1000)
    inicio_desejado = agora - int(ANOS[intervalo] * 365.25 * 86_400_000)
    if velas and velas[0][0] > inicio_desejado + 30 * 86_400_000:
        velas = []  # histórico curto demais (ex.: mudou ANOS) — baixa de novo
    inicio = velas[-1][0] + passo if velas else inicio_desejado
    if agora - inicio > 50 * passo:
        avisar(f"   ⬇️  {par} {intervalo}: baixando {'atualização' if velas else 'histórico de ' + str(ANOS[intervalo]) + ' anos'}...")
    novas = mercado.velas_desde(par, intervalo, inicio)
    if novas:
        velas += [[v["t"], v["o"], v["h"], v["l"], v["c"], v["v"]] for v in novas]
        _salvar(par, intervalo, velas)
    return velas


def como_dicionario(velas):
    """Converte [[t,o,h,l,c,v], ...] em colunas {'t': [...], 'o': [...], ...} (mais rápido pros cálculos)."""
    return {
        "t": [x[0] for x in velas], "o": [x[1] for x in velas], "h": [x[2] for x in velas],
        "l": [x[3] for x in velas], "c": [x[4] for x in velas], "v": [x[5] for x in velas],
    }
