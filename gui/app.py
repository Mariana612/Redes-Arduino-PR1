import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from serial_transfer import SerialTransferWorker
from redes_arduino.messages import FileType, Speed
from redes_arduino.session import LinkConfig


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
        self.root.minsize(980, 700)
        self.root.configure(bg=BG)
        self.selected_file = None
        self.settings_open = False
        self.serial_connection = None
        self.protocol_worker = None
        self.transfer_running = False

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
        self.connection_indicator = self._label(header, "●  Sin conexión", bg=BG, fg=MUTED,
                                                font=("Helvetica", 9))
        self.connection_indicator.pack(side="right", padx=(0, 12))

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
        self._label(card, "Selecciona un archivo PDF, PNG o TXT para preparar la transferencia.",
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
        tk.Button(row, text="Probar reconstrucción", command=self.test_reconstruction,
                  bg="#e8f0fa", fg="#285d91", activebackground="#d9e7f5",
                  relief="flat", bd=0, padx=10, pady=7, font=("Helvetica", 9, "bold"),
                  cursor="hand2").pack(side="right")
        self.received = tk.Frame(card, bg=PANEL)
        self.received.pack(fill="both", expand=True, pady=(14, 0))
        self.received_placeholder = self._label(
            self.received, "Todavía no hay archivos recibidos", fg=MUTED,
            font=("Helvetica", 10)
        )
        self.received_placeholder.pack(anchor="w", pady=12)

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
                       font=("Helvetica", 9), command=self._settings_changed).pack(side="right")
        self.test_button = tk.Button(self.settings, text="Probar conexión",
                                     command=self.test_connection, bg="#e8f0fa", fg="#285d91",
                                     activebackground="#d9e7f5", relief="flat", bd=0,
                                     padx=12, pady=9, font=("Helvetica", 10, "bold"),
                                     cursor="hand2")
        self.test_button.pack(fill="x", pady=(16, 0))
        self.handshake_button = tk.Button(
            self.settings, text="Comprobar enlace UNO–Nano",
            command=self.start_handshake, bg="#e8f0fa", fg="#285d91",
            activebackground="#d9e7f5", relief="flat", bd=0,
            padx=12, pady=9, font=("Helvetica", 10, "bold"), cursor="hand2",
        )
        self.handshake_button.pack(fill="x", pady=(10, 0))
        self.connection_test_status = self._label(self.settings, "Prueba el enlace USB y la comunicación Uno–Nano.",
                                                   bg=PANEL, fg=MUTED, font=("Helvetica", 8),
                                                   wraplength=240, justify="left")
        self.connection_test_status.pack(anchor="w", pady=(8, 0))
        self.send_test_button = tk.Button(self.settings, text="Probar envío",
                                          command=self.test_send, bg="#e8f0fa", fg="#285d91",
                                          activebackground="#d9e7f5", relief="flat", bd=0,
                                          padx=12, pady=9, font=("Helvetica", 10, "bold"),
                                          cursor="hand2")
        self.send_test_button.pack(fill="x", pady=(12, 0))
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
        elif title == "Velocidad de transmisión":
            self.baud_choice = choice
        elif title == "Tamaño de carga útil":
            self.payload_choice = choice
        elif title == "Tamaño de ventana":
            self.window_choice = choice
        elif title == "Límite de espera":
            self.timeout_choice = choice
        choice.pack(fill="x", pady=(0, 16))
        choice.bind("<<ComboboxSelected>>", self._settings_changed)

    def _settings_changed(self, _event=None):
        if self.protocol_worker is None:
            return
        try:
            self.protocol_worker.update_config(self._current_config(), self._current_timeout())
        except (ValueError, AttributeError, KeyError):
            pass

    def toggle_settings(self):
        if self.settings_open:
            self.settings.pack_forget()
        else:
            self.settings.pack(side="right", fill="y", padx=(18, 0))
        self.settings_open = not self.settings_open

    def test_send(self):
        self.start_transfer()

    def test_connection(self):
        port = self.port_choice.get().strip()
        if not port:
            self.connection_test_status.config(text="Selecciona el puerto serial del Arduino.", fg="#b54747")
            return

        try:
            import serial

            config = self._current_config()
            timeout_seconds = self._current_timeout()
            if self.serial_connection is not None and self.serial_connection.is_open:
                if self.protocol_worker is not None:
                    self.protocol_worker.close()
                self.serial_connection.close()

            self.serial_connection = serial.Serial(
                port=port,
                baudrate=115200,
                timeout=0.05,
                write_timeout=1,
            )
            self.protocol_worker = SerialTransferWorker(
                self.serial_connection, config, timeout_seconds, self._protocol_event
            )
            self.connection_test_status.config(
                text=f"USB conectado a {port}; enlace listo para negociar.", fg=ACCENT
            )
            self.connection_indicator.config(text="●  Conectado", fg=ACCENT)
        except ImportError:
            self.serial_connection = None
            self.connection_test_status.config(
                text="Falta pyserial. Instálalo con: pip install pyserial", fg="#b54747"
            )
            self.connection_indicator.config(text="●  Sin conexión", fg=MUTED)
        except Exception as exc:
            self.serial_connection = None
            self.connection_test_status.config(text=f"No se pudo abrir el puerto: {exc}", fg="#b54747")
            self.connection_indicator.config(text="●  Sin conexión", fg=MUTED)

    def start_handshake(self):
        if self.protocol_worker is None:
            self.connection_test_status.config(
                text="Conecta primero el puerto USB del Arduino con «Probar conexión».",
                fg="#b54747",
            )
            return
        try:
            self.protocol_worker.update_config(self._current_config(), self._current_timeout())
            self.protocol_worker.check_config()
        except (ValueError, AttributeError) as exc:
            self.connection_test_status.config(text=f"Configuración inválida: {exc}", fg="#b54747")

    def _current_config(self):
        baudrate = int(self.baud_choice.get().split()[0])
        return LinkConfig(
            speed={9600: Speed.BPS_9600, 19200: Speed.BPS_19200}[baudrate],
            payload_size=int(self.payload_choice.get().split()[0]),
            window=int(self.window_choice.get().split()[0]),
            hamming=self.hamming_var.get(),
        )

    def _current_timeout(self):
        return int(self.timeout_choice.get().split()[0]) / 1000

    def _protocol_event(self, event, *values):
        self.root.after(0, self._apply_protocol_event, event, values)

    def _apply_protocol_event(self, event, values):
        if event == "connected":
            self.connection_test_status.config(text=values[0], fg=ACCENT)
            self.connection_indicator.config(text="●  UNO–Nano conectado", fg=ACCENT)
            self.transfer_status.config(text="Handshake correcto; parámetros compatibles.", fg=ACCENT)
        elif event == "status":
            self.transfer_status.config(text=values[0], fg=MUTED)
            self.connection_test_status.config(text=values[0], fg=MUTED)
        elif event == "error":
            self.transfer_running = False
            self.send_button.config(text="Enviar archivo", bg="#1769d2")
            self.transfer_status.config(text=values[0], fg="#b54747")
            self.connection_test_status.config(text=values[0], fg="#b54747")
        elif event == "progress":
            sent, received = values
            self.send_progress["value"] = int(sent * 100)
            self.send_percent.config(text=f"{int(sent * 100)}%")
            self.receive_progress["value"] = int(received * 100)
            self.receive_percent.config(text=f"{int(received * 100)}%")
        elif event == "sent":
            self.transfer_running = False
            self.send_button.config(text="Enviar archivo", bg="#1769d2")
            self.transfer_status.config(text=f"Archivo enviado correctamente: {Path(values[0]).name}", fg=ACCENT)
        elif event == "received":
            self._save_received_file(*values)

    def _save_received_file(self, data, extension, transfer_id):
        destination = filedialog.asksaveasfilename(
            title="Guardar archivo recibido",
            initialfile=f"recibido_{transfer_id:08X}.{extension}",
            defaultextension=f".{extension}",
            filetypes=[(extension.upper(), f"*.{extension}"), ("Todos los archivos", "*.*")],
        )
        if not destination:
            self.transfer_status.config(text="Transferencia recibida; el archivo no se guardó.", fg="#b54747")
            return
        try:
            Path(destination).write_bytes(data)
        except OSError as exc:
            self.transfer_status.config(text=f"No se pudo guardar el archivo: {exc}", fg="#b54747")
            return
        self.received_placeholder.pack_forget()
        self._label(self.received, Path(destination).name, fg=TEXT,
                    font=("Helvetica", 10)).pack(anchor="w", pady=6)
        self.transfer_status.config(text=f"Archivo recibido: {Path(destination).name}", fg=ACCENT)

    def choose_file(self):
        path = filedialog.askopenfilename(
            title="Seleccionar archivo",
            filetypes=[("Archivos permitidos", "*.pdf *.png *.txt"),
                       ("PDF", "*.pdf"), ("PNG", "*.png"), ("TXT", "*.txt")],
        )
        if path:
            self.selected_file = path
            self.file_label.config(text=path.rsplit("/", 1)[-1], fg=TEXT)
            self.transfer_status.config(text="Archivo listo para enviar.", fg=MUTED)

    def test_reconstruction(self):
        source_path = filedialog.askopenfilename(
            title="Seleccionar archivo para simular recepción",
            filetypes=[("Archivos PDF, PNG y TXT", "*.pdf *.png *.txt")],
        )
        if not source_path:
            return

        source = Path(source_path)
        extension = source.suffix.lower()
        if extension not in (".pdf", ".png", ".txt"):
            self.transfer_status.config(text="Solo se admiten archivos PDF, PNG y TXT.", fg="#b54747")
            return

        destination_path = filedialog.asksaveasfilename(
            title="Guardar archivo reconstruido",
            initialfile=f"reconstruido_{source.name}",
            defaultextension=extension,
            filetypes=[(f"Archivo {extension[1:].upper()}", f"*{extension}")],
        )
        if not destination_path:
            return

        try:
            payload_size = int(self.payload_choice.get().split()[0])
            with source.open("rb") as source_file:
                original_data = source_file.read()

            frames = [original_data[index:index + payload_size]
                      for index in range(0, len(original_data), payload_size)]
            if not frames:
                frames = [b""]

            print(f"\nPrueba de recepción: {source.name}")
            print(f"Carga útil configurada: {payload_size} bytes | Tramas recibidas: {len(frames)}")
            for index, frame in enumerate(frames, start=1):
                print(f"Trama recibida {index}/{len(frames)} ({len(frame)} bytes): {frame.hex(' ')}")

            reconstructed_data = b"".join(frames)
            with open(destination_path, "wb") as destination_file:
                destination_file.write(reconstructed_data)

            if reconstructed_data != original_data:
                raise OSError("La verificación del archivo reconstruido no coincide.")
        except (OSError, ValueError, AttributeError) as exc:
            self.transfer_status.config(text=f"Error al reconstruir: {exc}", fg="#b54747")
            return

        self.received_placeholder.pack_forget()
        self._label(self.received, Path(destination_path).name, fg=TEXT,
                    font=("Helvetica", 10)).pack(anchor="w", pady=6)
        print(f"Reconstrucción correcta: {destination_path} ({len(reconstructed_data)} bytes)\n")
        self.transfer_status.config(
            text=f"Archivo reconstruido correctamente: {Path(destination_path).name}", fg=ACCENT
        )

    def start_transfer(self):
        if not self.selected_file:
            self.transfer_status.config(text="Selecciona un archivo antes de enviar.", fg="#ffb86b")
            return
        if self.transfer_running:
            return

        if self.protocol_worker is None:
            self.transfer_status.config(text="Conecta el Arduino con «Probar conexión» primero.", fg="#b54747")
            return
        try:
            file_path = self.selected_file
            file_data = Path(file_path).read_bytes()
            if len(file_data) > 0xFFFFFFFF:
                raise ValueError("El protocolo admite archivos de hasta 4 GiB.")
            extension_types = {".txt": FileType.TXT, ".pdf": FileType.PDF, ".png": FileType.PNG}
            file_type = extension_types.get(Path(file_path).suffix.lower())
            if file_type is None:
                raise ValueError("Solo se admiten archivos TXT, PDF y PNG.")
            config = self._current_config()
            self.protocol_worker.update_config(config, self._current_timeout())
        except (OSError, ValueError, AttributeError, KeyError) as exc:
            self.transfer_status.config(text=f"No se pudo preparar el archivo: {exc}", fg="#b54747")
            return

        self.transfer_running = True
        self.send_button.config(text="Enviando...", bg="#62758a")
        self.send_progress["value"] = 0
        self.send_percent.config(text="0%")
        self.transfer_status.config(text="Verificando el enlace antes de enviar START…", fg=MUTED)
        self.protocol_worker.send_file(file_path, file_data, file_type)


if __name__ == "__main__":
    root = tk.Tk()
    FileTransferApp(root)
    root.mainloop()
