# GUI de DUINO Transfer

## Requirimientos

- Python v3.14+
- Tkinter
- Arduino UNO
- Arduino Nano

## Instalacion

1. Crear ambiente de entorno virtual
```bash
python -m venv .venv
```

2. Activar el entorno
```bash
# Windows
.venv\Scripts\activate

# MacOS / Linux
source .venv/Scripts/activate
```

3. Instalar dependencias
```bash
pip install requirements.txt
```

## Envío entre dos computadoras

1. Carga `sketches_ArduinoIDE/SketchTestConnection/sketch_uno/sketch_uno.ino` en el UNO y
   `sketches_ArduinoIDE/SketchTestConnection/sketch_nano/sketch_nano.ino` en el Nano.
2. Conecta D9 TX de cada placa a D8 RX de la otra y une GND. Conecta cada placa por USB
   a su computadora.
3. En cada aplicación, selecciona el puerto USB del Arduino y pulsa **Probar conexión**.
   La conexión USB usa 115200 baudios; la aplicación negocia la velocidad del enlace RX/TX.
4. Selecciona el archivo y pulsa **Enviar archivo**. Antes de START, la aplicación compara
   velocidad, tamaño de carga útil, ventana y Hamming. Si no coinciden, no envía el archivo.
5. Al completar FIN/FIN_ACK y verificar el tamaño y SHA-256, la aplicación receptora pide
   dónde guardar el archivo.

Las tramas usan delimitador `0x7E`, escape de `0x7E` y `0x7D`, checksum y el Hamming
configurado. Los tipos de control son DATA `0x01`, ACK `0x02`, START `0x03`, FIN `0x04`,
ABORT `0x05`, START_ACK `0x06` y FIN_ACK `0x07`.
