"""Console sender/receiver for Arduino-to-Arduino file transfers."""

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "gui"))

import serial  # noqa: E402
from serial.tools import list_ports  # noqa: E402
from serial_transfer import SerialTransferWorker  # noqa: E402

from redes_arduino.messages import FileType, Speed  # noqa: E402
from redes_arduino.session import LinkConfig  # noqa: E402


FILE_TYPES = {
    ".txt": FileType.TXT,
    ".pdf": FileType.PDF,
    ".png": FileType.PNG,
}


def choose_port() -> str:
    ports = list(list_ports.comports())
    if not ports:
        raise RuntimeError("No se detectaron puertos seriales. Conecta el Arduino e inténtalo de nuevo.")

    print("\nPuertos seriales disponibles:")
    for index, port in enumerate(ports, start=1):
        description = f" — {port.description}" if port.description else ""
        print(f"  {index}. {port.device}{description}")

    while True:
        selected = input("Selecciona un número de puerto (o escribe el nombre del puerto): ").strip()
        if selected.isdigit() and 1 <= int(selected) <= len(ports):
            return ports[int(selected) - 1].device
        if selected in {port.device for port in ports}:
            return selected
        print("Selección inválida. Elige un número de la lista o escribe un puerto mostrado.")


def ask_choice(prompt: str, options: dict[str, object], default: str):
    available = "/".join(options)
    while True:
        value = input(f"{prompt} ({available}) [{default}]: ").strip() or default
        if value in options:
            return options[value]
        print(f"Elige una de estas opciones: {available}.")


def ask_config() -> tuple[LinkConfig, float]:
    baud = ask_choice("Velocidad del enlace Arduino–Arduino", {"9600": Speed.BPS_9600, "19200": Speed.BPS_19200}, "9600")
    payload = ask_choice("Tamaño de carga útil por trama", {"500": 500, "900": 900}, "500")
    window = ask_choice("Tamaño de la ventana Go-Back-N", {"4": 4, "6": 6, "8": 8}, "4")
    hamming = ask_choice("¿Activar Hamming?", {"s": True, "n": False, "S": True, "N": False}, "n")
    timeout_ms = ask_choice(
        "Espera antes de retransmitir (ms)",
        {"250": 250, "500": 500, "1000": 1000, "2000": 2000, "5000": 5000},
        "1000",
    )
    return LinkConfig(baud, payload, window, hamming), timeout_ms / 1000


def console_notify(done: threading.Event, state: dict, output_dir: Path, role: str):
    def notify(event: str, *values):
        if event == "status":
            print(f"\n{values[0]}")
        elif event == "connected":
            print(f"\n{values[0]}")
        elif event == "ack_sent":
            print(f"\n{values[0]}")
        elif event == "peer_mismatch":
            print(f"\n{values[0]}")
        elif event == "error":
            print(f"\nERROR: {values[0]}")
            state["result"] = False
            done.set()
        elif event == "progress":
            sent, received = values
            percent = int((received if role == "receive" else sent) * 100)
            label = "Recepción" if role == "receive" else "Envío"
            print(f"\r{label}: {percent:3d}%", end="", flush=True)
        elif event == "sent":
            print(f"\nArchivo enviado correctamente: {Path(values[0]).name}")
            state["result"] = True
            done.set()
        elif event == "received":
            data, extension, transfer_id = values
            output_dir.mkdir(parents=True, exist_ok=True)
            destination = output_dir / f"recibido_{transfer_id:08X}.{extension}"
            suffix = 1
            while destination.exists():
                destination = output_dir / f"recibido_{transfer_id:08X}_{suffix}.{extension}"
                suffix += 1
            try:
                destination.write_bytes(data)
            except OSError as exc:
                print(f"\nNo se pudo guardar el archivo recibido: {exc}")
                return
            print(f"\nArchivo recibido y guardado en: {destination.resolve()}")
            state["received"] = destination

    return notify


def main() -> int:
    print("DUINO Transfer — consola")
    role = ask_choice("Modo", {"e": "send", "r": "receive", "E": "send", "R": "receive"}, "e")
    config, timeout = ask_config()
    port = choose_port()
    output_dir = ROOT / "received_files"
    done = threading.Event()
    state = {"result": None}
    serial_port = None
    worker = None

    try:
        serial_port = serial.Serial(port=port, baudrate=115200, timeout=0.05, write_timeout=1)
        print(f"Puerto abierto: {port} (USB a 115200 baudios). Esperando el reinicio del Arduino…")
        worker = SerialTransferWorker(
            serial_port, config, timeout, console_notify(done, state, output_dir, role)
        )

        if role == "send":
            file_path = Path(input("Ruta del archivo TXT, PDF o PNG que deseas enviar: ").strip().strip('"'))
            if not file_path.is_file():
                raise FileNotFoundError(f"No se encontró el archivo: {file_path}")
            file_type = FILE_TYPES.get(file_path.suffix.lower())
            if file_type is None:
                raise ValueError("El protocolo solo admite archivos TXT, PDF y PNG.")
            data = file_path.read_bytes()
            if len(data) > 0xFFFFFFFF:
                raise ValueError("El protocolo admite archivos de hasta 4 GiB.")
            worker.send_file(str(file_path), data, file_type)
            print("El handshake comparará la configuración con el equipo receptor antes de enviar START.")
            done.wait()
            return 0 if state["result"] else 1

        print(f"Modo receptor activo. Los archivos se guardarán en: {output_dir.resolve()}")
        print("Deja esta consola abierta mientras el otro equipo envía. Pulsa Ctrl+C para salir.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nCerrando receptor.")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    finally:
        if worker is not None:
            worker.close()
        if serial_port is not None and serial_port.is_open:
            serial_port.close()


if __name__ == "__main__":
    raise SystemExit(main())
