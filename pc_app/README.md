# pc_app — lado PC del Proyecto 1 (IC-7602 Redes, Grupo 01)

Lógica de protocolo según el informe de la Etapa 1: Hamming (13,8), escape y delimitadores 0x7E,
Checksum de 16 bits, tramas Go-Back-N, mensajes de control y segmentación en paquetes.

```bash
cd pc_app
uv sync                 # crea .venv e instala pytest, ruff, mypy
uv run pytest           # todos los tests
uv run ruff check . && uv run mypy
uv run python -m redes_arduino.demo ARCHIVO [--payload 500|900] [--no-hamming] [--ber 0.0005]
```

| Módulo | Capa | Qué hace |
|---|---|---|
| `hamming.py` | Física | Codificar/decodificar (13,8) SECDED, 2 bytes por byte |
| `framing.py` | Física | Escape 0x7D/XOR 0x20, delimitadores 0x7E, `Deframer` por flujo |
| `checksum.py` | Enlace | Checksum 16 bits complemento a uno |
| `frame.py` | Enlace | Trama `ctrl|seq|ack|len|carga|checksum` y validaciones |
| `messages.py` | Enlace | Cargas de START, START_ACK, ACK, FIN, FIN_ACK, ABORT |
| `packets.py` | Red | Paquetes de 500/900 bytes, reensamblado, SHA-256 |
| `demo.py` | — | Archivo de punta a punta sobre un canal con ruido simulado |

Go-Back-N, el protocolo USB con el Arduino y la interfaz gráfica todavía no están.
