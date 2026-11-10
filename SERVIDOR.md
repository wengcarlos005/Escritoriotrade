# Agência de Trade num servidor na nuvem (ligada 24h)

Com isso a agência roda sozinha num computador alugado na internet: você acompanha pelo celular ou por qualquer
computador, com o seu PC desligado. O endereço tem **HTTPS** (cadeado) e pede **usuário e senha**.

## 1. Alugar o servidor (uns R$ 25 a 35 por mês)

Qualquer servidor com **Ubuntu 24.04** e **2 GB de memória ou mais** serve. Duas opções boas:

| Provedor | Plano | Preço aproximado | Onde criar |
|---|---|---|---|
| **Hetzner** (recomendado) | CX22 (2 CPUs, 4 GB) | ~€ 4,60/mês | Alemanha ou Finlândia |
| **Vultr** | Regular Cloud Compute 2 GB | ~US$ 10/mês | **São Paulo** (mais perto) |

⚠️ **Não crie o servidor nos EUA**: a Binance bloqueia os dados de futuros para endereços americanos.

Na hora de criar:
1. Escolha a imagem **Ubuntu 24.04**.
2. Escolha a região (Europa ou São Paulo).
3. Em acesso, escolha **senha de root** (o mais simples) ou uma chave SSH, se você já tiver.
4. Crie e anote o **IP** do servidor (algo como `91.98.123.45`).

> Opção grátis: a **Oracle Cloud "Always Free"** (região São Paulo ou Vinhedo) também funciona. Ela pede cartão no
> cadastro, às vezes não tem vaga, e você precisa liberar as portas **80** e **443** na "Security List" da rede
> (VCN) no site da Oracle.

## 2. Entrar no servidor

No Windows, abra o **PowerShell** (menu Iniciar → digite "PowerShell") e escreva, trocando pelo seu IP:

```
ssh root@91.98.123.45
```

Na primeira vez ele pergunta se confia no servidor: digite `yes` e Enter. Depois cole a senha de root (ela não
aparece enquanto você digita, é normal) e Enter.

## 3. Instalar a agência (um comando só)

Já dentro do servidor, cole este comando e aperte Enter:

```
curl -fsSL https://raw.githubusercontent.com/wengcarlos005/escritoriotrade/main/servidor/instalar.sh | bash
```

Ele instala tudo, liga a agência como um serviço (liga sozinha se o servidor reiniciar e volta se cair) e, no
fim, mostra:

```
   Endereço:  https://91-98-123-45.sslip.io
   Usuário:   agencia
   Senha:     xxxxxxxxxxxx
```

**Guarde a senha.** Na primeira vez a escola baixa o histórico e faz as provas: o endereço só abre depois de uns
**15 a 30 minutos**. Pra acompanhar enquanto isso:

```
journalctl -u agencia -f
```

(`Ctrl+C` pra sair — a agência continua rodando.)

## 4. No dia a dia

- **Acompanhar:** abra o endereço no celular ou no PC, entre com usuário `agencia` e a senha. No celular, use
  "Adicionar à tela inicial" para ter um atalho como se fosse um app.
- **Atualizações:** o servidor baixa a versão nova do GitHub **sozinho todo dia** (madrugada) e reinicia só se
  mudou algo. Seus dados ficam. Pra atualizar na hora: entre no servidor e rode `agencia-atualizar`.
- **Ver o que está acontecendo:** `journalctl -u agencia -f`
- **Reiniciar:** `systemctl restart agencia`
- **Parar / ligar:** `systemctl stop agencia` / `systemctl start agencia`
- **Trocar a senha:** rode o instalador de novo com a senha que quiser:
  `curl -fsSL https://raw.githubusercontent.com/wengcarlos005/escritoriotrade/main/servidor/instalar.sh | SENHA='sua-senha-nova' bash`
- **Mudar configurações** (ex.: `risco_alvo`): edite `/opt/agencia/config.json` (`nano /opt/agencia/config.json`)
  e reinicie.

## 5. E o PC de casa?

A agência do PC e a do servidor são **simulações separadas**. Pode desligar a do PC (ou deixar as duas rodando,
se quiser comparar). O que vale é a do servidor.

## Segurança

- O painel só abre com a senha, e só passa por HTTPS.
- **Nunca** coloque chaves de API da Binance com permissão de saque. Por enquanto a conta real é só simulada:
  nenhuma ordem vai pra corretora.
- A chave do Claude (gerente), se você usar, fica só no servidor (`/opt/agencia/dados`).
