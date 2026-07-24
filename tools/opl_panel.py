"""
opl_panel.py
============
Panel cyberpunk (Tkinter) para "SUBIR OPL" — disparador APARTE del panel WMS.

Sube los correos OPL (carpeta EasyGo) de una fecha a 'BASE DATOS OPL' y carga los
subordenes (col B) en la pestaña "Que va quedando Easy". NO toca WMS ni Render.

Robustez (clave): el panel (GUI) corre con pythonw (sin consola), pero lanza el
trabajo real como SUBPROCESO bajo **python.exe** + CREATE_NO_WINDOW. Bajo pythonw el
`append` de OPL a Google Sheets falla en silencio; bajo python.exe sube bien.

Se lanza sin consola con pythonw.exe (ver "Subir OPL.bat").
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import messagebox, scrolledtext

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUSH_SCRIPT = PROJECT_ROOT / "tools" / "push_to_wms_sheet.py"   # orquestador; aquí se usa --opl-only


def _console_python() -> str:
    """Devuelve un Python de CONSOLA (python.exe), NUNCA pythonw.exe.

    El panel se lanza con pythonw.exe (sin consola). Si el trabajo pesado hereda
    pythonw, el `append` real a Google Sheets de OPL FALLA EN SILENCIO. Forzamos
    python.exe (probado para esa escritura) y ocultamos la consola con CREATE_NO_WINDOW.
    """
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        cand = exe[:-len("pythonw.exe")] + "python.exe"
        if Path(cand).exists():
            return cand
    return exe


# ── Paleta cyberpunk (igual que push_panel) ───────────────────────────────────
BG       = "#0a0a12"
PANEL    = "#12121f"
EDGE     = "#1f2740"
CYAN     = "#00fff7"
MAGENTA  = "#ff2bd6"
GREEN    = "#39ff14"
YELLOW   = "#f7ff00"
DIM      = "#5b6688"
TXT      = "#c8d3f5"
FONT     = ("Consolas", 11)
FONT_B   = ("Consolas", 11, "bold")
FONT_BIG = ("Consolas", 30, "bold")
FONT_TTL = ("Consolas", 17, "bold")


class OplPanel:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self.proc: subprocess.Popen | None = None
        self.running = False
        self._opl_error = False

        root.title("SUBIR OPL")
        root.configure(bg=BG)
        root.geometry("820x600")
        root.minsize(720, 540)

        self._build_header()
        self._build_controls()
        self._build_metrics()
        self._build_log()
        self._build_footer()

        self.root.after(80, self._poll)

    # ── UI ────────────────────────────────────────────────────────────────────
    def _build_header(self):
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=18, pady=(16, 6))
        tk.Label(head, text="▓▒░ SUBIR OPL ░▒▓", bg=BG, fg=YELLOW,
                 font=FONT_TTL).pack(side="left")
        self.status = tk.Label(head, text="◢◤ ONLINE", bg=BG, fg=GREEN, font=FONT_B)
        self.status.pack(side="right")
        tk.Frame(self.root, bg=YELLOW, height=2).pack(fill="x", padx=18)

    def _build_controls(self):
        ctl = tk.Frame(self.root, bg=BG)
        ctl.pack(fill="x", padx=18, pady=12)

        tk.Label(ctl, text="FECHA ▸", bg=BG, fg=MAGENTA, font=FONT_B).pack(side="left")
        self.fecha = tk.Entry(ctl, bg=PANEL, fg=CYAN, insertbackground=CYAN,
                              font=FONT_B, width=14, relief="flat",
                              highlightthickness=1, highlightbackground=EDGE,
                              highlightcolor=CYAN, justify="center")
        self.fecha.insert(0, date.today().strftime("%d-%m-%Y"))
        self.fecha.pack(side="left", padx=(8, 18), ipady=5)

        self.btn_prev = self._neon_button(ctl, "⟳ VISTA PREVIA", CYAN,
                                          lambda: self._run(dry_run=True))
        self.btn_prev.pack(side="left", padx=4)
        self.btn_push = self._neon_button(ctl, "▲ SUBIR OPL", YELLOW,
                                          self._confirm_push)
        self.btn_push.pack(side="left", padx=4)

    def _neon_button(self, parent, text, color, cmd):
        b = tk.Button(parent, text=text, command=cmd, font=FONT_B,
                      bg=PANEL, fg=color, activebackground=color,
                      activeforeground=BG, relief="flat", bd=0,
                      highlightthickness=1, highlightbackground=color,
                      padx=14, pady=7, cursor="hand2")
        b.bind("<Enter>", lambda e: b.config(bg=color, fg=BG) if b["state"] == "normal" else None)
        b.bind("<Leave>", lambda e: b.config(bg=PANEL, fg=color))
        return b

    def _build_metrics(self):
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill="x", padx=18, pady=(0, 10))
        self.m_filas = self._tile(wrap, "FILAS OPL", YELLOW, 0)
        self.m_subs = self._tile(wrap, "SUBORDENES → EASY", CYAN, 1)
        for i in range(2):
            wrap.columnconfigure(i, weight=1, uniform="m")

    def _tile(self, parent, label, color, col):
        f = tk.Frame(parent, bg=PANEL, highlightthickness=1,
                     highlightbackground=EDGE)
        f.grid(row=0, column=col, sticky="nsew", padx=5, ipady=6)
        val = tk.Label(f, text="—", bg=PANEL, fg=color, font=FONT_BIG)
        val.pack(pady=(8, 0))
        tk.Label(f, text=label, bg=PANEL, fg=DIM, font=FONT_B).pack(pady=(0, 6))
        return val

    def _build_log(self):
        box = tk.Frame(self.root, bg=EDGE, highlightthickness=1,
                       highlightbackground=EDGE)
        box.pack(fill="both", expand=True, padx=18, pady=(0, 8))
        self.log = scrolledtext.ScrolledText(
            box, bg="#070710", fg=TXT, insertbackground=CYAN, font=("Consolas", 10),
            relief="flat", bd=0, wrap="word", state="disabled", height=14,
        )
        self.log.pack(fill="both", expand=True, padx=2, pady=2)
        self.log.tag_config("ok", foreground=GREEN)
        self.log.tag_config("warn", foreground=YELLOW)
        self.log.tag_config("err", foreground=MAGENTA)
        self.log.tag_config("hl", foreground=CYAN)
        self.log.tag_config("dim", foreground=DIM)

    def _build_footer(self):
        self.footer = tk.Label(self.root, text="Listo.", bg=BG, fg=DIM,
                               font=("Consolas", 9), anchor="w")
        self.footer.pack(fill="x", padx=18, pady=(0, 10))

    # ── Log helpers ─────────────────────────────────────────────────────────────
    def _append(self, line: str):
        tag = None
        low = line.lower()
        if line.startswith("##SUMMARY##") or line.startswith("##OPL_SUMMARY##"):
            return  # no mostrar líneas técnicas
        if "agregad" in low or "[ok]" in low or "filas con id" in low:
            tag = "ok"
        elif "!!" in line or "error" in low or "falló" in low or "no se complet" in low:
            tag = "err"
        elif line.strip().startswith("- ") or "se omite" in low or "dry-run" in low or "duplicad" in low:
            tag = "warn"
        elif line.startswith(">>"):
            tag = "hl"
        self.log.config(state="normal")
        self.log.insert("end", line + ("\n" if not line.endswith("\n") else ""), tag)
        self.log.see("end")
        self.log.config(state="disabled")

    def _set_metrics(self, filas, subs, opl_error=False):
        self.m_filas.config(text=str(filas), fg=(MAGENTA if opl_error else YELLOW))
        self.m_subs.config(text=str(subs))

    # ── Run ──────────────────────────────────────────────────────────────────────
    def _confirm_push(self):
        f = self.fecha.get().strip()
        if messagebox.askyesno(
            "Confirmar subida OPL",
            f"¿Subir los OPL de {f}?\n\n"
            "Esto va a:\n"
            "  • Escribir en el Google Sheet 'BASE DATOS OPL'\n"
            "  • Cargar los subordenes en 'Que va quedando Easy' (al final)\n\n"
            "NO toca WMS ni Render.",
            icon="warning",
        ):
            self._run(dry_run=False)

    def _run(self, dry_run: bool):
        if self.running:
            return
        f = self.fecha.get().strip()
        self.running = True
        self._opl_error = False
        self.btn_prev.config(state="disabled")
        self.btn_push.config(state="disabled")
        self._set_metrics("…", "…")
        self.status.config(text="◢◤ PROCESANDO", fg=YELLOW)
        self.footer.config(text=("Vista previa (dry-run)…" if dry_run else "Subiendo OPL + subordenes a Easy…"))
        self.log.config(state="normal"); self.log.delete("1.0", "end"); self.log.config(state="disabled")
        self._append(f">> {'VISTA PREVIA' if dry_run else 'SUBIDA REAL'} OPL · fecha {f}")

        # SIEMPRE python.exe de consola (oculto con CREATE_NO_WINDOW): bajo pythonw el
        # append de OPL falla en silencio.
        py = _console_python()
        cmd = [py, str(PUSH_SCRIPT), "--fecha", f, "--opl-only"]
        if dry_run:
            cmd.append("--dry-run")
        threading.Thread(target=self._worker, args=(cmd,), daemon=True).start()

    def _worker(self, cmd):
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=str(PROJECT_ROOT), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", creationflags=flags,
            )
            for line in self.proc.stdout:
                self.q.put(("line", line.rstrip("\n")))
            self.proc.wait()
            self.q.put(("done", self.proc.returncode))
        except Exception as e:
            self.q.put(("line", f"!! Error lanzando el proceso: {e}"))
            self.q.put(("done", -1))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "line":
                    if payload.startswith("##SUMMARY##"):
                        try:
                            data = json.loads(payload[len("##SUMMARY##"):].strip())
                            self._opl_error = bool(data.get("opl_error", False))
                            self._set_metrics(data.get("opl_filas", 0),
                                              data.get("opl_subordenes", 0),
                                              opl_error=self._opl_error)
                        except Exception:
                            pass
                    self._append(payload)
                elif kind == "done":
                    self._finish(payload)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _finish(self, code):
        self.running = False
        self.proc = None
        self.btn_prev.config(state="normal")
        self.btn_push.config(state="normal")
        if self._opl_error:
            self.status.config(text="◢◤ OPL FALLÓ", fg=MAGENTA)
            self.footer.config(text="⚠ La subida OPL FALLÓ (FILAS OPL en rojo). Los correos no se "
                                     "marcaron como procesados; vuelve a ejecutar.")
            self._append("!! La subida de OPL falló. Revisa el log; se reintentará en la próxima corrida.")
        elif code == 0:
            self.status.config(text="◢◤ ONLINE", fg=GREEN)
            self.footer.config(text="Listo. ✓")
        else:
            self.status.config(text="◢◤ ERROR", fg=MAGENTA)
            self.footer.config(text=f"Terminó con código {code}.")
        if self.m_filas["text"] in ("…", "—"):
            self._set_metrics(0, 0)


def main():
    root = tk.Tk()
    OplPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
