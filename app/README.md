# DUINO Transfer — consola

La misma consola puede enviar o recibir archivos entre dos computadoras conectadas a un Arduino UNO y un Arduino Nano.

## Preparar

Carga el sketch puente actual en cada Arduino. Conecta D9 TX de cada placa a D8 RX de la otra y une los GND. Conecta cada Arduino por USB a su computadora.

Instala la dependencia:

```bash
python -m pip install -r app/requirements.txt
```

Se requiere Python 3.10 o posterior.

## Ejecutar

En ambas computadoras:

```bash
python app/main.py
```

En la computadora que recibirá, selecciona **r** (receptor) y deja la consola abierta. En la computadora que enviará, selecciona **e**, introduce la ruta del archivo y confirma el puerto serial que aparece en la lista. El receptor guarda los archivos en `received_files/`.

Selecciona los mismos valores de velocidad, carga útil, ventana Go-Back-N, Hamming y espera en ambos equipos. El programa compara la configuración antes de START; después transfiere con DATA/ACK y termina con FIN/FIN_ACK. Se admiten archivos TXT, PDF y PNG.

El USB del Arduino se abre a 115200 baudios; la velocidad elegida en la consola configura el enlace RX/TX entre placas.
