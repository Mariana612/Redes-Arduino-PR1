
import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports


class ArduinoTerminal:
    def __init__(self, root):
        self.root = root
        self.root.title("Arduino Serial Terminal")
        self.root.geometry("720x520")

        self.connection = None
        self.rx_buffer = bytearray()
        self.after_id = None

        self.build_ui()
        self.refresh_ports()

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.poll_serial()

    def build_ui(self):
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(
            main, text="Comunicación Arduino",
            font=("Arial", 16, "bold")
        ).pack(anchor="w", pady=(0, 12))

        ttk.Label(main, text="Arduino conectado a esta computadora").pack(
            anchor="w"
        )

        port_frame = ttk.Frame(main)
        port_frame.pack(fill="x", pady=5)

        self.port_combo = ttk.Combobox(
            port_frame, state="readonly"
        )
        self.port_combo.pack(side="left", fill="x", expand=True)

        ttk.Button(
            port_frame, text="Actualizar",
            command=self.refresh_ports
        ).pack(side="left", padx=5)

        self.connect_button = ttk.Button(
            port_frame, text="Conectar",
            command=self.connect
        )
        self.connect_button.pack(side="left")

        self.status = ttk.Label(
            main, text="Estado: Desconectado"
        )
        self.status.pack(anchor="w", pady=5)

        ttk.Label(main, text="Mensaje para enviar").pack(
            anchor="w", pady=(10, 0)
        )

        send_frame = ttk.Frame(main)
        send_frame.pack(fill="x", pady=5)

        self.message_entry = ttk.Entry(send_frame)
        self.message_entry.pack(side="left", fill="x", expand=True)
        self.message_entry.bind(
            "<Return>", lambda event: self.send_message()
        )

        self.send_button = ttk.Button(
            send_frame, text="Enviar",
            command=self.send_message,
            state="disabled"
        )
        self.send_button.pack(side="left", padx=5)

        ttk.Label(main, text="Registro de comunicación").pack(
            anchor="w", pady=(10, 0)
        )

        self.log = tk.Text(
            main, height=16, state="disabled",
            wrap="word"
        )
        self.log.pack(fill="both", expand=True, pady=5)

        ttk.Button(
            main, text="Limpiar registro",
            command=self.clear_log
        ).pack(anchor="e")

    def refresh_ports(self):
        ports = list(serial.tools.list_ports.comports())
        port_names = [port.device for port in ports]

        self.port_combo["values"] = port_names

        if port_names:
            current = self.port_combo.get()
            if current not in port_names:
                self.port_combo.set(port_names[0])
        else:
            self.port_combo.set("")

        self.write_log(
            "Puertos detectados: "
            + (", ".join(port_names) if port_names else "ninguno")
        )

    def connect(self):
        if self.connection and self.connection.is_open:
            self.disconnect()
            return

        port_name = self.port_combo.get()

        if not port_name:
            messagebox.showwarning(
                "Puerto requerido",
                "Selecciona el puerto de tu Arduino."
            )
            return

        try:
            self.connection = serial.Serial(
                port=port_name,
                baudrate=9600,
                timeout=0
            )

            self.status.config(
                text=f"Estado: Conectado a {port_name}"
            )
            self.connect_button.config(text="Desconectar")
            self.send_button.config(state="normal")

            self.write_log(f"Conectado a {port_name} a 9600 bps.")

        except (serial.SerialException, OSError) as error:
            self.connection = None
            messagebox.showerror(
                "Error de conexión",
                str(error)
            )

    def disconnect(self):
        if self.connection:
            try:
                self.connection.close()
            except (serial.SerialException, OSError):
                pass

        self.connection = None
        self.status.config(text="Estado: Desconectado")
        self.connect_button.config(text="Conectar")
        self.send_button.config(state="disabled")
        self.write_log("Conexión cerrada.")

    def send_message(self):
        if not self.connection or not self.connection.is_open:
            messagebox.showwarning(
                "Sin conexión",
                "Conecta primero tu Arduino."
            )
            return

        message = self.message_entry.get()

        if not message:
            return

        try:
            data = (message + "\n").encode("utf-8")
            self.connection.write(data)

            self.write_log(f"TX: {message}")
            self.message_entry.delete(0, tk.END)

        except (serial.SerialException, OSError) as error:
            self.write_log(f"Error de envío: {error}")
            self.disconnect()

    
    def poll_serial(self):
        if self.connection and self.connection.is_open:
            try:
                available = self.connection.in_waiting

                if available:
                    data = self.connection.read(available)
                    self.rx_buffer.extend(data)

                    # Procesar únicamente mensajes completos
                    while b"\n" in self.rx_buffer:
                        message, _, remaining = self.rx_buffer.partition(b"\n")
                        self.rx_buffer = bytearray(remaining)

                        # Eliminar el retorno de carro si existe
                        message = message.rstrip(b"\r")

                        text = message.decode(
                            "utf-8", errors="replace"
                        )

                        self.write_log(f"RX: {text}")

            except (serial.SerialException, OSError) as error:
                self.write_log(f"Error de recepción: {error}")
                self.disconnect()

        self.after_id = self.root.after(30, self.poll_serial)


    def write_log(self, message, newline=True):
        self.log.configure(state="normal")
        self.log.insert(
            tk.END, message + ("\n" if newline else "")
        )
        self.log.see(tk.END)
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", tk.END)
        self.log.configure(state="disabled")

    def close(self):
        if self.after_id is not None:
            self.root.after_cancel(self.after_id)

        self.disconnect()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = ArduinoTerminal(root)
    root.mainloop()
