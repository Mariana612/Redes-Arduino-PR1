import tkinter as tk
from tkinter import filedialog, ttk


BG = "#f7f8fa"
PANEL = "#ffffff"
PANEL_LIGHT = "#f0f2f5"
TEXT = "#20252b"
MUTED = "#707982"
ACCENT = "#287d68"
BLUE = "#52759d"


class FileTransferApp:
    def __init__(self, root):
        self.root = root
        self.root.title("DUINO Transfer")
        self.root.geometry("980x700")
        self.root.minsize(820, 600)
        self.root.configure(bg=BG)
        self.selected_file = None
        self.settings_open = False

        self._style()
        self._build()

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL,
                        foreground=TEXT, arrowcolor=MUTED, bordercolor="#dfe3e8",
                        lightcolor=PANEL, darkcolor=PANEL, padding=7)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL_LIGHT)],
                  foreground=[("readonly", TEXT)])
        style.configure("Horizontal.TProgressbar", troughcolor="#e8ebef",
                        background=ACCENT, bordercolor="#e8ebef", lightcolor=ACCENT,
                        darkcolor=ACCENT, thickness=9)

    def _label(self, parent, text, **kwargs):
        return tk.Label(parent, text=text, bg=kwargs.pop("bg", PANEL), fg=kwargs.pop("fg", TEXT),
                        font=kwargs.pop("font", ("Helvetica", 11)), **kwargs)

    def _build(self):
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=32, pady=(22, 18))
        self._label(header, "DUINO Transfer", bg=BG,
                    font=("Helvetica", 17, "bold")).pack(side="left")
        tk.Button(header, text="⚙  Configuración", command=self.toggle_settings,
                  bg=BG, fg=TEXT, activebackground="#e9ecef", activeforeground=TEXT,
                  relief="flat", bd=0, padx=12, pady=8, font=("Helvetica", 10),
                  cursor="hand2").pack(side="right")
        self._label(header, "●  Sin conexión", bg=BG, fg=MUTED,
                    font=("Helvetica", 9)).pack(side="right", padx=(0, 12))

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=32, pady=(0, 22))
        self.main = tk.Frame(body, bg=BG)
        self.main.pack(side="left", fill="both", expand=True)
        self.settings = tk.Frame(body, bg=PANEL, width=280, padx=20, pady=20,
                                 highlightthickness=1, highlightbackground="#e5e8ec")

        self._label(self.main, "Transferencia de archivos", bg=BG,
                    font=("Helvetica", 21, "bold")).pack(anchor="w")
        self._label(self.main, "Selecciona un archivo y consulta el progreso.",
                    bg=BG, fg=MUTED, font=("Helvetica", 10)).pack(anchor="w", pady=(5, 18))

        self._build_send_card()
        self._build_progress_card()
        self._build_received_card()
        self._build_settings()

        footer = tk.Frame(self.root, bg=BG, height=34)
        footer.pack(fill="x", side="bottom")
       
    def _card(self, parent, **kwargs):
        return tk.Frame(parent, bg=PANEL, padx=18, pady=15,
                        highlightthickness=1, highlightbackground="#e5e8ec", **kwargs)

    def _build_send_card(self):
        card = self._card(self.main)
        card.pack(fill="x", pady=(0, 14))
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        self._label(row, "Enviar archivo", font=("Helvetica", 14, "bold")).pack(side="left")
        self._label(card, "Selecciona un archivo para preparar la transferencia.",
                    fg=MUTED, font=("Helvetica", 10)).pack(anchor="w", pady=(8, 15))
        controls = tk.Frame(card, bg=PANEL)
        controls.pack(fill="x")
        tk.Button(controls, text="Elegir archivo", command=self.choose_file,
                  bg=PANEL_LIGHT, fg=TEXT, activebackground="#e5e8ec", activeforeground=TEXT,
                  relief="flat", bd=0, padx=14, pady=9, font=("Helvetica", 10),
                  cursor="hand2").pack(side="left")
        self.send_button = tk.Label(controls, text="Enviar archivo", bg="#1769d2", fg="#ffffff",
                                    padx=20, pady=11, font=("Helvetica", 10, "bold"),
                                    cursor="hand2")
        self.send_button.pack(side="right")
        self.send_button.bind("<Button-1>", lambda _event: self.start_transfer())
        self.send_button.bind("<Enter>", lambda _event: self.send_button.config(bg="#1255ad"))
        self.send_button.bind("<Leave>", lambda _event: self.send_button.config(bg="#1769d2"))
        self.file_label = self._label(card, "Ningún archivo seleccionado", fg=MUTED,
                                      font=("Helvetica", 9))
        self.file_label.pack(anchor="w", pady=(11, 0))

    def _build_progress_card(self):
        card = self._card(self.main)
        card.pack(fill="x", pady=(0, 14))
        self._label(card, "Progreso", font=("Helvetica", 14, "bold")).pack(anchor="w", pady=(0, 16))
        self._progress_row(card, "Enviado", "send_progress", "send_percent", BLUE)
        tk.Frame(card, bg="#e8ebef", height=1).pack(fill="x", pady=13)
        self._progress_row(card, "Recibido", "receive_progress", "receive_percent", ACCENT)
        self.transfer_status = self._label(card, "Esperando una transferencia.", fg=MUTED,
                                           font=("Helvetica", 9))
        self.transfer_status.pack(anchor="w", pady=(17, 0))

    def _progress_row(self, parent, label, bar_name, percent_name, color):
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x")
        self._label(row, label, font=("Helvetica", 10, "bold")).pack(side="left")
        percent = self._label(row, "0%", fg=color, font=("Helvetica", 10, "bold"))
        percent.pack(side="right")
        bar = ttk.Progressbar(parent, style="Horizontal.TProgressbar", maximum=100, value=0)
        bar.pack(fill="x", pady=(10, 0))
        setattr(self, bar_name, bar)
        setattr(self, percent_name, percent)

    def _build_received_card(self):
        card = self._card(self.main)
        card.pack(fill="both", expand=True)
        row = tk.Frame(card, bg=PANEL)
        row.pack(fill="x")
        self._label(row, "Archivos recibidos", font=("Helvetica", 14, "bold")).pack(side="left")
        self.received = tk.Frame(card, bg=PANEL)
        self.received.pack(fill="both", expand=True, pady=(14, 0))
        self._label(self.received, "Todavía no hay archivos recibidos", fg=MUTED,
                    font=("Helvetica", 10)).pack(anchor="w", pady=12)

    def _build_settings(self):
        self._label(self.settings, "Configuración", bg=PANEL,
                    font=("Helvetica", 16, "bold")).pack(anchor="w")
        self._label(self.settings, "Parámetros del enlace", bg=PANEL, fg=MUTED,
                    font=("Helvetica", 9)).pack(anchor="w", pady=(5, 21))
        self._setting_choice("Puerto serial", "", self._serial_ports(), editable=True)
        self._setting_choice("Velocidad de transmisión", "9600 bps",
                             ["9600 bps", "19200 bps"])
        self._setting_choice("Tamaño de carga útil", "500 bytes", ["500 bytes", "900 bytes"])
        self._setting_choice("Tamaño de ventana", "4 tramas", ["4 tramas", "6 tramas", "8 tramas"])
        self._setting_choice("Límite de espera", "1000 ms", ["250 ms", "500 ms", "1000 ms", "2000 ms", "5000 ms"])
        tk.Frame(self.settings, bg="#e8ebef", height=1).pack(fill="x", pady=16)
        row = tk.Frame(self.settings, bg=PANEL)
        row.pack(fill="x")
        group = tk.Frame(row, bg=PANEL)
        group.pack(side="left")
        self._label(group, "Hamming code", bg=PANEL, font=("Helvetica", 10, "bold")).pack(anchor="w")
        self._label(group, "Corrección de errores", bg=PANEL, fg=MUTED,
                    font=("Helvetica", 9)).pack(anchor="w", pady=(4, 0))
        self.hamming_var = tk.BooleanVar(value=False)
        tk.Checkbutton(row, variable=self.hamming_var, text="Activado", bg=PANEL, fg=TEXT,
                       activebackground=PANEL, activeforeground=TEXT, selectcolor=PANEL_LIGHT,
                       font=("Helvetica", 9)).pack(side="right")
        self._label(self.settings, "Los cambios se aplican a la próxima transferencia.",
                    bg=PANEL, fg=MUTED, font=("Helvetica", 8), wraplength=240,
                    justify="left").pack(anchor="w", pady=(22, 0))

    def _serial_ports(self):
        try:
            from serial.tools import list_ports
            return [port.device for port in list_ports.comports()]
        except ImportError:
            return []

    def _setting_choice(self, title, default, values, editable=False):
        self._label(self.settings, title, bg=PANEL, fg="#4d5660",
                    font=("Helvetica", 9, "bold")).pack(anchor="w", pady=(0, 7))
        choice = ttk.Combobox(self.settings, values=values,
                              state="normal" if editable else "readonly")
        if default:
            choice.set(default)
        if title == "Puerto serial":
            self.port_choice = choice
        choice.pack(fill="x", pady=(0, 16))

    def toggle_settings(self):
        if self.settings_open:
            self.settings.pack_forget()
        else:
            self.settings.pack(side="right", fill="y", padx=(18, 0))
        self.settings_open = not self.settings_open

    def choose_file(self):
        path = filedialog.askopenfilename(title="Seleccionar archivo")
        if path:
            self.selected_file = path
            self.file_label.config(text=path.rsplit("/", 1)[-1], fg=TEXT)
            self.transfer_status.config(text="Archivo listo para enviar.", fg=MUTED)

    def start_transfer(self):
        if not self.selected_file:
            self.transfer_status.config(text="Selecciona un archivo antes de enviar.", fg="#ffb86b")
            return
        self.transfer_status.config(text="Interfaz preparada; conecta el módulo de transferencia para enviar.",
                                    fg="#ffb86b")


if __name__ == "__main__":
    root = tk.Tk()
    FileTransferApp(root)
    root.mainloop()
