"""Monitor bpytop-like pour acq_worker et son processus parent.

Lancé dans un terminal séparé par MainWindow au démarrage de l'acquisition.
Prend --child-pid et --parent-pid en arguments, affiche CPU % et mémoire RSS
en temps réel (plotext) jusqu'à ce que l'un des processus disparaisse.
"""
import argparse
import io
import shutil
import sys
import time

import plotext as plt
import psutil

HISTORY_LEN = 60   # un point ≈ 1 s → 60 s d'historique
_HEADER_LINES = 10  # lignes imprimées par _make_header

# Buffer alternatif : isole l'affichage du scrollback (comme htop/btop).
_ALT_ON  = "\033[?1049h\033[H"
_ALT_OFF = "\033[?1049l"
_HOME    = "\033[H"
_EOL     = "\033[K"             # efface jusqu'à la fin de la ligne


def _get_proc(pid: int) -> "psutil.Process | None":
    try:
        return psutil.Process(pid)
    except psutil.NoSuchProcess:
        return None


def _collect(proc: "psutil.Process") -> "dict | None":
    """Lit CPU %, mémoire, état et nb de threads — retourne None si disparu."""
    try:
        return {
            "cpu":     proc.cpu_percent(interval=None),
            "mem_kb":  proc.memory_info().rss / 1024,
            "mem_mb":  proc.memory_info().rss / 1024 / 1024,
            "status":  proc.status(),
            "threads": proc.num_threads(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _fmt_uptime(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _make_header(child_pid: int, parent_pid: int, ic: dict, ip: dict,
                 uptime: float) -> str:
    """Retourne le bloc header (10 lignes) sous forme de chaîne."""
    w    = shutil.get_terminal_size((80, 24)).columns
    sep  = "─" * w
    half = max(10, (w - 6) // 2)

    cpu_c = f"{ic['cpu']:.1f}%"
    cpu_p = f"{ip['cpu']:.1f}%"
    mem_c = f"{ic['mem_kb']:.3f} kB"
    mem_p = f"{ip['mem_kb']:.3f} kB"

    lines = [
        sep,
        f"  PROCESS MONITOR  ─  uptime {_fmt_uptime(uptime)}",
        sep,
        f"  {'acq_worker':^{half}}    {'parent':^{half}}",
        f"  {'PID  ' + str(child_pid):^{half}}    {'PID  ' + str(parent_pid):^{half}}",
        f"  {'CPU  ' + cpu_c:^{half}}    {'CPU  ' + cpu_p:^{half}}",
        f"  {'MEM  ' + mem_c:^{half}}    {'MEM  ' + mem_p:^{half}}",
        f"  {'État  ' + ic['status']:^{half}}    {'État  ' + ip['status']:^{half}}",
        f"  {'Threads  ' + str(ic['threads']):^{half}}    {'Threads  ' + str(ip['threads']):^{half}}",
        sep,
    ]
    return "".join(line + _EOL + "\n" for line in lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor bpytop-like — acq_worker + parent")
    parser.add_argument("--child-pid",  type=int, required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args()

    pchild  = _get_proc(args.child_pid)
    pparent = _get_proc(args.parent_pid)
    if pchild is None or pparent is None:
        print("Processus introuvable.")
        sys.exit(1)

    # Premier appel retourne 0 (pas de référence temporelle) — à ignorer
    pchild.cpu_percent(interval=None)
    pparent.cpu_percent(interval=None)

    hist_cpu_c = [0.0] * HISTORY_LEN
    hist_cpu_p = [0.0] * HISTORY_LEN
    hist_mem_c = [0.0] * HISTORY_LEN
    hist_mem_p = [0.0] * HISTORY_LEN
    xs = list(range(HISTORY_LEN))

    plt.theme("dark")
    start_time = time.time()

    sys.stdout.write(_ALT_ON)
    sys.stdout.flush()

    try:
        while True:
            time.sleep(1.0)

            ic = _collect(pchild)
            ip = _collect(pparent)
            if ic is None or ip is None:
                who = "acq_worker" if ic is None else "parent"
                sys.stdout.write(_ALT_OFF)
                sys.stdout.flush()
                print(f"{who} terminé — fermeture du monitor dans 3 s.")
                time.sleep(3)
                break

            hist_cpu_c.append(ic["cpu"]);    hist_cpu_c.pop(0)
            hist_cpu_p.append(ip["cpu"]);    hist_cpu_p.pop(0)
            hist_mem_c.append(ic["mem_mb"]); hist_mem_c.pop(0)
            hist_mem_p.append(ip["mem_mb"]); hist_mem_p.pop(0)

            w, h = shutil.get_terminal_size((80, 24))
            available_h = max(10, h - _HEADER_LINES)

            plt.clf()
            plt.plotsize(w, available_h)
            plt.subplots(2, 1)

            plt.subplot(1, 1)
            plt.title("CPU %")
            plt.plot(xs, hist_cpu_c, label=f"acq_worker [{args.child_pid}]",  color="orange", marker="braille")
            plt.plot(xs, hist_cpu_p, label=f"parent     [{args.parent_pid}]", color="cyan",   marker="braille")
            plt.ylim(0, 105)
            plt.xlabel(f"← {HISTORY_LEN} s")

            plt.subplot(2, 1)
            plt.title("Mémoire RSS (MB)")
            plt.plot(xs, hist_mem_c, label=f"acq_worker [{args.child_pid}]",  color="orange", marker="braille")
            plt.plot(xs, hist_mem_p, label=f"parent     [{args.parent_pid}]", color="cyan",   marker="braille")
            plt.xlabel(f"← {HISTORY_LEN} s")

            # Capture plt.show() dans un buffer puis écriture atomique avec le header
            buf = io.StringIO()
            sys.stdout, _real = buf, sys.stdout
            plt.show()
            sys.stdout = _real
            header = _make_header(args.child_pid, args.parent_pid, ic, ip,
                                  time.time() - start_time)
            sys.stdout.write(_HOME + header + buf.getvalue())
            sys.stdout.flush()

    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write(_ALT_OFF)
        sys.stdout.flush()


if __name__ == "__main__":
    main()
