import telnetlib
import time
import re
from datetime import datetime

OLT_IP   = "10.0.0.2"
USERNAME = "root"
PASSWORD = "12345"
TIMEOUT  = 5

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

REGEX_SERIAL = re.compile(r'(?:\d+-|(?<=\())(prks\w+):')

def send_command(tn, command, wait=1):
    tn.write(command.encode('ascii') + b"\n")
    time.sleep(wait)
    return tn.read_very_eager().decode('ascii', errors='ignore')

def deve_remover(serial: str, status: str) -> bool:
    """
    Regras de remoção por status:
      - pending  → remove QUALQUER serial (todas são indesejadas)
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

        tn.write(b"\n")
        time.sleep(1)

        tn.read_until(b"Username:", timeout=TIMEOUT)
        tn.write(USERNAME.encode('ascii') + b"\n")

        tn.read_until(b"keyuser:", timeout=TIMEOUT)
        tn.write(PASSWORD.encode('ascii') + b"\n")

        time.sleep(2)
        login_output = tn.read_very_eager().decode('ascii', errors='ignore')
        print("[LOGIN OUTPUT]:")
        print(login_output)

        if "%AUTH" in login_output or "Login failed" in login_output:
            print("[ERRO] Falha no login.")
            tn.close()
            return

        print("[SUCESSO] Login bem-sucedido!\n")

        onus_para_remover: dict[str, list[tuple[str, str]]] = {}

        for comando in COMANDOS:
            # Extrai o status do próprio comando (última palavra)
            status    = comando.split()[-1]          # inactive | invalid | pending
            interface = comando.split()[2]           # gpon1/1, etc.

            print(f"[INFO] Enviando: {comando}")
            output = send_command(tn, comando, wait=2)
            print("[RESPOSTA]:")
            print(output)

            for match in REGEX_SERIAL.finditer(output):
                serial = match.group(1)
                if deve_remover(serial, status):
                    print(f"  ► [{status.upper()}] Detectado {serial} em {interface}")
                    onus_para_remover.setdefault(interface, []).append((serial, status))

        removidas: list[tuple[str, str, str]] = []   # (interface, serial, status)

        if onus_para_remover:
            print("\n[INFO] Iniciando remoção de ONUs problemáticas...")
            send_command(tn, "configure terminal", wait=1)
            for interface, itens in onus_para_remover.items():
                send_command(tn, f"interface {interface}", wait=1)
                for serial, status in itens:
                    print(f"[REMOVENDO] {serial} [{status}] → {interface}")
                    send_command(tn, f"no onu {serial}", wait=1)
                    removidas.append((interface, serial, status))
                send_command(tn, "exit", wait=0.5)
            send_command(tn, "end",      wait=1)
            send_command(tn, "copy r s", wait=2)
            print("[SUCESSO] ONUs removidas e configuração salva.")
        else:
            print("[INFO] Nenhuma ONU INACTIVE, INVALID ou PENDING encontrada.")

        tn.close()

        if removidas:
            data_str     = datetime.now().strftime("%Y%m%d-%H%M%S")
            nome_arquivo = f"{OLT_IP}_relatorio_onus_removidas_{data_str}.txt"
            with open(nome_arquivo, "w", encoding="utf-8") as f:
                f.write(f"Relatório de ONUs removidas - {OLT_IP} - {data_str}\n")
                f.write("=" * 65 + "\n")
                f.write(f"{'Interface':<14} {'Serial':<20} {'Status'}\n")
                f.write("-" * 65 + "\n")
                for interface, serial, status in removidas:
                    f.write(f"{interface:<14} {serial:<20} {status.upper()}\n")
                f.write("=" * 65 + "\n")

                for s in ("inactive", "invalid", "pending"):
                    total = sum(1 for _, _, st in removidas if st == s)
                    if total:
                        f.write(f"  {s.upper():<10}: {total} removida(s)\n")
                f.write(f"  {'TOTAL':<10}: {len(removidas)} removida(s)\n")
            print(f"[RELATÓRIO] Salvo em '{nome_arquivo}'.")
        else:
            print("[RELATÓRIO] Nenhuma ONU removida. Arquivo não criado.")

    except Exception as e:
        print(f"[ERRO] {e}")

if __name__ == "__main__":
    main()
