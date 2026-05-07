"""Monitor bpytop-like pour acq_worker et son processus parent.

Lancé dans un terminal séparé par MainWindow au démarrage de l'acquisition.
Prend --child-pid et --parent-pid en arguments, affiche CPU % et mémoire RSS
en temps réel (plotext) jusqu'à ce que l'un des processus disparaisse.
"""
import argparse
import shutil
import sys
import time

import plotext as plt
import psutil

HISTORY_LEN = 60   # un point ≈ 1 s → 60 s d'historique
_HEADER_LINES = 10  # lignes imprimées par _print_header (sep+titre+sep + 6 données + sep)


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
            "mem_mb":  proc.memory_info().rss / 1024 / 1024,
            "status":  proc.status(),
            "threads": proc.num_threads(),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def _print_header(child_pid: int, parent_pid: int, ic: dict, ip: dict) -> None:
    w    = shutil.get_terminal_size((80, 24)).columns
    sep  = "─" * w
    half = max(10, (w - 6) // 2)

    cpu_c = f"{ic['cpu']:.1f}%"
    cpu_p = f"{ip['cpu']:.1f}%"
    mem_c = f"{ic['mem_mb']:.1f} MB"
    mem_p = f"{ip['mem_mb']:.1f} MB"

    print(sep)
    print(f"  PROCESS MONITOR  ─  {time.strftime('%H:%M:%S')}")
    print(sep)
    print(f"  {'acq_worker':^{half}}    {'parent':^{half}}")
    print(f"  {'PID  ' + str(child_pid):^{half}}    {'PID  ' + str(parent_pid):^{half}}")
    print(f"  {'CPU  ' + cpu_c:^{half}}    {'CPU  ' + cpu_p:^{half}}")
    print(f"  {'MEM  ' + mem_c:^{half}}    {'MEM  ' + mem_p:^{half}}")
    print(f"  {'État  ' + ic['status']:^{half}}    {'État  ' + ip['status']:^{half}}")
    print(f"  {'Threads  ' + str(ic['threads']):^{half}}    {'Threads  ' + str(ip['threads']):^{half}}")
    print(sep)


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

    try:
        while True:
            time.sleep(1.0)

            ic = _collect(pchild)
            ip = _collect(pparent)
            if ic is None or ip is None:
                who = "acq_worker" if ic is None else "parent"
                print(f"\n{who} terminé — fermeture du monitor dans 3 s.")
                time.sleep(3)
                break

            hist_cpu_c.append(ic["cpu"]);    hist_cpu_c.pop(0)
            hist_cpu_p.append(ip["cpu"]);    hist_cpu_p.pop(0)
            hist_mem_c.append(ic["mem_mb"]); hist_mem_c.pop(0)
            hist_mem_p.append(ip["mem_mb"]); hist_mem_p.pop(0)

            w, h = shutil.get_terminal_size((80, 24))
            available_h = max(10, h - _HEADER_LINES)

            plt.clf()
            plt.clt()

            _print_header(args.child_pid, args.parent_pid, ic, ip)

            plt.plotsize(w, available_h)
            plt.subplots(2, 1)

            plt.subplot(1, 1)
            plt.title("CPU %")
            plt.plot(xs, hist_cpu_c, label=f"acq_worker [{args.child_pid}]",  color="orange")
            plt.plot(xs, hist_cpu_p, label=f"parent     [{args.parent_pid}]", color="cyan")
            plt.ylim(0, 105)
            plt.xlabel(f"← {HISTORY_LEN} s")

            plt.subplot(2, 1)
            plt.title("Mémoire RSS (MB)")
            plt.plot(xs, hist_mem_c, label=f"acq_worker [{args.child_pid}]",  color="orange")
            plt.plot(xs, hist_mem_p, label=f"parent     [{args.parent_pid}]", color="cyan")
            plt.xlabel(f"← {HISTORY_LEN} s")

            plt.show()

    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
