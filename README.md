# 🔌 Script de Limpeza Automática em OLT's PARKS de remoção de ONUs parks Inactive, Invalid ou Pending via Telnet

Este script em Python se conecta via Telnet a uma OLT Parks, verifica as ONUs com status `INACTIVE`, `INVALID` ou `PENDING`, e remove automaticamente aquelas com serial iniciado por `prks00`. Ao final, um relatório com as ONUs removidas é salvo.

---

## ⚙️ Como usar

1. 🔧 Edite as variáveis no início do código abaixo com os dados da sua OLT:
``` 
OLT_IP   = "10.0.0.4"
USERNAME = "root"
PASSWORD = "12345678"
```
```python
import telnetlib
import time
import re
from datetime import datetime

OLT_IP   = "10.0.0.4"
USERNAME = "root"
PASSWORD = "12345678"
TIMEOUT  = 8

COMANDOS = [
    # ── INACTIVE ──────────────────────────────
    "sh interface gpon1/1 onu status inactive",
    "sh interface gpon1/2 onu status inactive",
    "sh interface gpon1/3 onu status inactive",
    "sh interface gpon1/4 onu status inactive",
    "sh interface gpon2/1 onu status inactive",
    "sh interface gpon2/2 onu status inactive",
    "sh interface gpon2/3 onu status inactive",
    "sh interface gpon2/4 onu status inactive",
    # ── INVALID ───────────────────────────────
    "sh interface gpon1/1 onu status invalid",
    "sh interface gpon1/2 onu status invalid",
    "sh interface gpon1/3 onu status invalid",
    "sh interface gpon1/4 onu status invalid",
    "sh interface gpon2/1 onu status invalid",
    "sh interface gpon2/2 onu status invalid",
    "sh interface gpon2/3 onu status invalid",
    "sh interface gpon2/4 onu status invalid",
    # ── PENDING ───────────────────────────────
    "sh interface gpon1/1 onu status pending",
    "sh interface gpon1/2 onu status pending",
    "sh interface gpon1/3 onu status pending",
    "sh interface gpon1/4 onu status pending",
    "sh interface gpon2/1 onu status pending",
    "sh interface gpon2/2 onu status pending",
    "sh interface gpon2/3 onu status pending",
    "sh interface gpon2/4 onu status pending",
]

# Regex robusto: captura QUALQUER serial que esteja dentro de (prks...):
REGEX_SERIAL = re.compile(r'\((prks\w+)\):')

# Prompt da OLT para saber quando parar de ler
PROMPT_RE = re.compile(r'(Solar\d+#|\w+#|\(config[^)]*\)#|\(config-if[^)]*\)#)')


def read_until_prompt(tn, timeout=15):
    """
    Lê a saída da OLT até encontrar o prompt.
    Se encontrar --More--, envia espaço para continuar.
    """
    output = ""
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            chunk = tn.read_very_eager().decode('ascii', errors='ignore')
        except Exception:
            chunk = ""

        if chunk:
            output += chunk
            start_time = time.time()  # reset timer quando recebe dados

            # Se aparecer --More--, manda espaço para continuar a listagem
            if "--More--" in output:
                output = output.replace("--More--", "")
                tn.write(b" ")
                time.sleep(0.3)
                continue

            # Se encontrou o prompt, terminou essa saída
            if PROMPT_RE.search(chunk):
                break

        time.sleep(0.2)

    return output


def send_command(tn, command, wait_after=2):
    """Envia comando e lê toda a resposta até o prompt voltar."""
    print(f"[CMD] >>> {command}")
    tn.write(command.encode('ascii') + b"\n")
    time.sleep(0.5)
    output = read_until_prompt(tn, timeout=15)
    if output.strip():
        print(f"[RSP] ---\n{output}\n---")
    time.sleep(wait_after)
    return output


def deve_remover(serial: str, status: str) -> bool:
    """
    Regras de remoção por status:
      - pending  → remove QUALQUER serial
      - inactive → remove apenas seriais 'prks00...'
      - invalid  → remove apenas seriais 'prks00...'
    """
    if status == "pending":
        return True
    return serial.startswith("prks00")


def main():
    try:
        print(f"[INFO] Conectando à OLT {OLT_IP} via Telnet...")
        tn = telnetlib.Telnet(OLT_IP, timeout=TIMEOUT)

        # Limpa buffer inicial
        tn.write(b"\n")
        time.sleep(1)
        tn.read_very_eager()

        # Login
        tn.read_until(b"Username:", timeout=TIMEOUT)
        tn.write(USERNAME.encode('ascii') + b"\n")

        tn.read_until(b"keyuser:", timeout=TIMEOUT)
        tn.write(PASSWORD.encode('ascii') + b"\n")

        time.sleep(2)
        login_output = read_until_prompt(tn, timeout=10)
        print("[LOGIN OUTPUT]:")
        print(login_output)

        if "%AUTH" in login_output or "Login failed" in login_output:
            print("[ERRO] Falha no login.")
            tn.close()
            return

        print("[SUCESSO] Login bem-sucedido!\n")

        # Tenta desabilitar paginação (terminal length 0)
        # Se não existir nesse equipamento, a OLT vai dar erro mas continua funcionando
        print("[INFO] Tentando desabilitar paginação...")
        send_command(tn, "terminal length 0", wait_after=1)

        onus_para_remover: dict[str, list[tuple[str, str]]] = {}

        for comando in COMANDOS:
            status    = comando.split()[-1]          # inactive | invalid | pending
            interface = comando.split()[2]           # gpon1/1, etc.

            output = send_command(tn, comando, wait_after=3)

            matches = list(REGEX_SERIAL.finditer(output))
            print(f"[DEBUG] {interface} [{status}] → {len(matches)} serial(is) encontrado(s)")

            for match in matches:
                serial = match.group(1)
                if deve_remover(serial, status):
                    print(f"  ► [{status.upper()}] Detectado {serial} em {interface}")
                    onus_para_remover.setdefault(interface, []).append((serial, status))

        removidas: list[tuple[str, str, str]] = []   # (interface, serial, status)
        falhas: list[tuple[str, str, str, str]] = [] # (interface, serial, status, erro)

        if onus_para_remover:
            total = sum(len(v) for v in onus_para_remover.values())
            print(f"\n[INFO] Iniciando remoção de {total} ONU(s) problemática(s)...")

            send_command(tn, "configure terminal", wait_after=2)

            for interface, itens in onus_para_remover.items():
                send_command(tn, f"interface {interface}", wait_after=1)

                for serial, status in itens:
                    print(f"[REMOVENDO] {serial} [{status}] → {interface}")

                    # Envia o comando de remoção
                    send_command(tn, f"no onu {serial}", wait_after=2)

                    # Verifica se houve erro na remoção
                    # Lê novamente para pegar qualquer mensagem de erro
                    check_output = read_until_prompt(tn, timeout=5)

                    if "%" in check_output and ("Error" in check_output or "Invalid" in check_output or "No such" in check_output):
                        erro_msg = check_output.strip().split("\n")[-1]
                        print(f"  [FALHA] {serial}: {erro_msg}")
                        falhas.append((interface, serial, status, erro_msg))
                    else:
                        print(f"  [OK] {serial} removido com sucesso.")
                        removidas.append((interface, serial, status))

                send_command(tn, "exit", wait_after=1)

            send_command(tn, "end", wait_after=2)
            send_command(tn, "copy r s", wait_after=5)
            print("[SUCESSO] Processo de remoção finalizado e configuração salva.")
        else:
            print("[INFO] Nenhuma ONU INACTIVE, INVALID ou PENDING encontrada.")

        tn.close()

        # Gera relatório
        data_str = datetime.now().strftime("%Y%m%d-%H%M%S")
        nome_arquivo = f"{OLT_IP}_relatorio_onus_{data_str}.txt"

        with open(nome_arquivo, "w", encoding="utf-8") as f:
            f.write(f"Relatório de ONUs - OLT {OLT_IP} - {data_str}\n")
            f.write("=" * 70 + "\n\n")

            if removidas:
                f.write(f"ONUs REMOVIDAS COM SUCESSO: {len(removidas)}\n")
                f.write("-" * 70 + "\n")
                f.write(f"{'Interface':<14} {'Serial':<20} {'Status'}\n")
                f.write("-" * 70 + "\n")
                for interface, serial, status in removidas:
                    f.write(f"{interface:<14} {serial:<20} {status.upper()}\n")
                f.write("\n")

                for s in ("inactive", "invalid", "pending"):
                    total = sum(1 for _, _, st in removidas if st == s)
                    if total:
                        f.write(f"  {s.upper():<10}: {total} removida(s)\n")
                f.write(f"  {'TOTAL':<10}: {len(removidas)} removida(s)\n")
            else:
                f.write("Nenhuma ONU foi removida.\n")

            if falhas:
                f.write("\n" + "=" * 70 + "\n")
                f.write(f"FALHAS NA REMOÇÃO: {len(falhas)}\n")
                f.write("-" * 70 + "\n")
                f.write(f"{'Interface':<14} {'Serial':<20} {'Status':<10} {'Erro'}\n")
                f.write("-" * 70 + "\n")
                for interface, serial, status, erro in falhas:
                    f.write(f"{interface:<14} {serial:<20} {status.upper():<10} {erro}\n")

            f.write("\n" + "=" * 70 + "\n")
            f.write("FIM DO RELATÓRIO\n")

        print(f"[RELATÓRIO] Salvo em '{nome_arquivo}'.")

        if falhas:
            print(f"[AVISO] {len(falhas)} ONU(s) não puderam ser removidas. Verifique o relatório.")

    except Exception as e:
        print(f"[ERRO CRÍTICO] {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
```
---

## 🧠 Autor

Desenvolvido por [Alan Marques Ferreira] 🧑‍💻  
Especialista em automações de rede e scripts para OLTs Parks

---

## 🐍 Requisitos de Python

- ✅ Python 3.6 até 3.10: nada precisa ser instalado  
- ⚠️ Python 3.11 ou superior: instale a alternativa `telnetlib3`:

```bash
python -m pip install telnetlib3
```

---

## 🛡️ Licença

Este projeto é de uso livre para fins administrativos.  
Dê os créditos ao autor original ao compartilhar ou modificar o script.
