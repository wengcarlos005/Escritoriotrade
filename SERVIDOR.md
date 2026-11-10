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

> **Quer de graça?** Use a **Oracle Cloud "Always Free"** — o passo a passo está logo abaixo, em
> [Oracle Cloud (grátis)](#oracle-cloud-grátis).

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

---

## Oracle Cloud (grátis)

A Oracle dá um servidor ARM grátis para sempre ("Always Free"). Dá um pouco mais de trabalho que os pagos:

### A. Criar a conta
1. Entre em **oracle.com/cloud/free** → "Start for free".
2. Ela pede **cartão de crédito** só pra confirmar que você é uma pessoa (pode aparecer uma cobrança de teste
   pequena que é devolvida). Os recursos "Always Free" não são cobrados.
3. **Região inicial ("Home Region"): escolha `Brazil East (São Paulo)` ou `Brazil Southeast (Vinhedo)`.** Ela não
   pode ser trocada depois — e não pode ser nos EUA.

### B. Criar o servidor
1. Menu ☰ → **Compute → Instances → Create instance**.
2. **Image:** clique em "Edit" → "Change image" → **Canonical Ubuntu 24.04** (ou 22.04).
3. **Shape:** "Change shape" → **Ampere** → **VM.Standard.A1.Flex**, com **1 OCPU e 6 GB** de memória
   (aparece a etiqueta "Always Free-eligible").
4. **SSH keys:** deixe "Generate a key pair for me" e clique em **"Save private key"** — baixa um arquivo
   `.key`. **Guarde ele**: é a "senha" pra entrar no servidor.
5. Clique em **Create**. Quando ficar verde (Running), anote o **Public IP address**.

> Se aparecer **"Out of capacity"**: tente outro "Availability domain" (AD-1, AD-2…) ou tente de novo mais tarde
> (às vezes leva alguns dias até ter vaga no plano grátis).

### C. Liberar as portas 80 e 443 (pro endereço com cadeado funcionar)
1. Na página do servidor, clique no nome da **Subnet** (em "Primary VNIC").
2. Clique na **Security List** (Default Security List…) → **Add Ingress Rules**.
3. Preencha: **Source CIDR** `0.0.0.0/0` · **IP Protocol** TCP · **Destination Port Range** `80,443` → **Add**.

### D. Entrar no servidor (Windows, PowerShell)
Na Oracle o usuário é **`ubuntu`** e se entra com a chave baixada. Troque o caminho do arquivo e o IP:

```
icacls "$HOME\Downloads\ssh-key-2026-11-10.key" /inheritance:r
icacls "$HOME\Downloads\ssh-key-2026-11-10.key" /grant:r "$($env:USERNAME):(R)"
ssh -i "$HOME\Downloads\ssh-key-2026-11-10.key" ubuntu@SEU_IP
```

(As duas primeiras linhas só precisam ser feitas uma vez: o Windows exige que a chave seja só sua.)
Na primeira vez digite `yes` e Enter.

### E. Instalar (repare no `sudo`)

```
curl -fsSL https://raw.githubusercontent.com/wengcarlos005/escritoriotrade/main/servidor/instalar.sh | sudo bash
```

O instalador já libera as portas dentro do servidor (a imagem da Oracle vem bloqueando). No fim ele mostra o
endereço, o usuário e a senha — daí é igual aos outros provedores (seção 4).

### ⚠️ Cuidado: a Oracle pode desligar servidor grátis "parado"
Contas só gratuitas podem ter o servidor **recuperado** se ele ficar com uso muito baixo por 7 dias seguidos — e a
agência usa pouco processamento. Pra evitar: no menu ☰ → **Billing → Upgrade and Manage Payment** → mude a conta
pra **"Pay As You Go"**. Os recursos Always Free **continuam grátis**; você só paga se criar coisas fora do plano
grátis (não crie). Se preferir não mudar, faça um backup de vez em quando (a pasta `/opt/agencia/dados`).
