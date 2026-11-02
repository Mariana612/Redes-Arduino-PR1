#include <AltSoftSerial.h>

// ============================================================
// Endpoint Arduino Full Duplex
// PC <-> Arduino: Serial (USB)
// Arduino <-> Arduino: AltSoftSerial (ATmega328P: RX=D8, TX=D9)
// ============================================================

AltSoftSerial enlace;

static const uint8_t FLAG = 0x7E;
static const uint8_t ESC = 0x7D;
static const uint8_t ESC_XOR = 0x20;

static const uint8_t USB_LOCAL_DATA = 0x31;
static const uint8_t USB_LOCAL_ACK = 0x32;
static const uint8_t USB_LOCAL_CONFIG = 0x33;
static const uint8_t USB_LOCAL_CONFIG_ACK = 0x34;
static const uint8_t USB_CHUNK_SIZE = 16;

static const uint8_t TYPE_HAMMING_STATS = 0x08;
static const uint8_t SEQ_CONTROL = 0xFF;
static const uint8_t ACK_NONE = 0xFF;

static bool hammingEnabled = true;
static uint32_t currentBaud = 9600;
static uint8_t pcTxSequence = 0;

// ---------- parser transporte local USB ----------
struct UsbParser {
  bool receiving = false;
  bool escaped = false;
  uint8_t buffer[USB_CHUNK_SIZE + 4];
  uint8_t length = 0;
};
UsbParser usbParser;

// ---------- estado recepción física ----------
bool phyInFrame = false;
bool phyEscaped = false;
bool phyDropFrame = false;
bool haveFirstHammingByte = false;
uint8_t firstHammingByte = 0;

// ---------- buffer PC de salida ----------
uint8_t pcChunk[USB_CHUNK_SIZE];
uint8_t pcChunkLen = 0;

// ---------- estadísticas Hamming ----------
uint32_t rxFrameId = 0;
uint32_t totalCorrected = 0;
uint32_t totalGlobalParity = 0;
uint32_t totalDouble = 0;
uint16_t frameBlocks = 0;
uint16_t frameCorrected = 0;
uint16_t frameGlobalParity = 0;
uint16_t frameDouble = 0;
uint16_t lastErrorBlock = 0;
uint8_t lastErrorStatus = 0;
uint8_t lastErrorPosition = 0;
uint16_t lastErrorWord = 0;

// ============================================================
// Utilidades USB local
// ============================================================

uint8_t usbChecksum(const uint8_t *data, uint8_t len) {
  uint8_t c = 0;
  for (uint8_t i = 0; i < len; ++i) c ^= data[i];
  return c;
}

void writeUsbEscaped(uint8_t b) {
  if (b == FLAG || b == ESC) {
    Serial.write(ESC);
    Serial.write(b ^ ESC_XOR);
  } else {
    Serial.write(b);
  }
}

void sendUsbPacket(uint8_t kind, uint8_t sequence, const uint8_t *payload, uint8_t len) {
  uint8_t checksum = kind ^ sequence ^ len;
  Serial.write(FLAG);
  writeUsbEscaped(kind);
  writeUsbEscaped(sequence);
  writeUsbEscaped(len);
  for (uint8_t i = 0; i < len; ++i) {
    checksum ^= payload[i];
    writeUsbEscaped(payload[i]);
  }
  writeUsbEscaped(checksum);
  Serial.write(FLAG);
}

void sendUsbAck(uint8_t sequence, bool configAck = false) {
  sendUsbPacket(configAck ? USB_LOCAL_CONFIG_ACK : USB_LOCAL_ACK, sequence, nullptr, 0);
}

void flushPcChunk() {
  if (!pcChunkLen) return;
  sendUsbPacket(USB_LOCAL_DATA, pcTxSequence++, pcChunk, pcChunkLen);
  pcChunkLen = 0;
}

void queueByteToPc(uint8_t b) {
  pcChunk[pcChunkLen++] = b;
  if (pcChunkLen >= USB_CHUNK_SIZE) flushPcChunk();
}

// ============================================================
// Checksum de trama lógica
// ============================================================

uint16_t checksum16UpdateWords(const uint8_t *data, uint16_t len) {
  uint32_t total = 0;
  uint16_t i = 0;
  while (i + 1 < len) {
    total += ((uint16_t)data[i] << 8) | data[i + 1];
    total = (total & 0xFFFFUL) + (total >> 16);
    i += 2;
  }
  if (i < len) {
    total += ((uint16_t)data[i] << 8);
    total = (total & 0xFFFFUL) + (total >> 16);
  }
  return (uint16_t)(~total);
}

void writeLogicalEscapedToPc(uint8_t b) {
  if (b == FLAG || b == ESC) {
    queueByteToPc(ESC);
    queueByteToPc(b ^ ESC_XOR);
  } else {
    queueByteToPc(b);
  }
}

void sendStatsFrameToPc() {
  uint8_t payload[30];
  uint8_t p = 0;
  auto put32 = [&](uint32_t v) {
    payload[p++] = (uint8_t)(v >> 24); payload[p++] = (uint8_t)(v >> 16);
    payload[p++] = (uint8_t)(v >> 8);  payload[p++] = (uint8_t)v;
  };
  auto put16 = [&](uint16_t v) {
    payload[p++] = (uint8_t)(v >> 8); payload[p++] = (uint8_t)v;
  };

  put32(rxFrameId);
  put32(totalCorrected);
  put32(totalGlobalParity);
  put32(totalDouble);
  put16(frameBlocks);
  put16(frameCorrected);
  put16(frameGlobalParity);
  put16(frameDouble);
  put16(lastErrorBlock);
  payload[p++] = lastErrorStatus;
  payload[p++] = lastErrorPosition;
  put16(lastErrorWord);

  uint8_t protectedBytes[5 + 30];
  protectedBytes[0] = TYPE_HAMMING_STATS;
  protectedBytes[1] = SEQ_CONTROL;
  protectedBytes[2] = ACK_NONE;
  protectedBytes[3] = 0;
  protectedBytes[4] = 30;
  memcpy(protectedBytes + 5, payload, 30);
  uint16_t check = checksum16UpdateWords(protectedBytes, sizeof(protectedBytes));

  queueByteToPc(FLAG);
  for (uint8_t i = 0; i < sizeof(protectedBytes); ++i) writeLogicalEscapedToPc(protectedBytes[i]);
  writeLogicalEscapedToPc((uint8_t)(check >> 8));
  writeLogicalEscapedToPc((uint8_t)check);
  queueByteToPc(FLAG);
  flushPcChunk();
}

// ============================================================
// Hamming extendido (13,8) SECDED
// posiciones 1..12 = Hamming; posición 13 = paridad global
// ============================================================

bool getBit16(uint16_t word, uint8_t pos) {
  return (word >> (pos - 1)) & 1U;
}

void setBit16(uint16_t &word, uint8_t pos, bool value) {
  uint16_t mask = (uint16_t)1U << (pos - 1);
  if (value) word |= mask; else word &= ~mask;
}

uint16_t hammingEncode(uint8_t data) {
  static const uint8_t dataPos[8] = {3,5,6,7,9,10,11,12};
  uint16_t word = 0;
  for (uint8_t i = 0; i < 8; ++i) setBit16(word, dataPos[i], (data >> i) & 1U);

  const uint8_t parityPos[4] = {1,2,4,8};
  for (uint8_t k = 0; k < 4; ++k) {
    uint8_t pp = parityPos[k];
    bool parity = false;
    for (uint8_t pos = 1; pos <= 12; ++pos) {
      if ((pos & pp) && pos != pp) parity ^= getBit16(word, pos);
    }
    setBit16(word, pp, parity); // paridad par
  }

  bool global = false;
  for (uint8_t pos = 1; pos <= 12; ++pos) global ^= getBit16(word, pos);
  setBit16(word, 13, global);
  return word;
}

// status: 0 sin error, 1 corregido, 2 error bit paridad global, 3 doble error
uint8_t hammingDecode(uint16_t input, uint8_t &data, uint8_t &position) {
  uint16_t word = input & 0x1FFF;
  uint8_t syndrome = 0;
  const uint8_t parityPos[4] = {1,2,4,8};
  for (uint8_t k = 0; k < 4; ++k) {
    uint8_t pp = parityPos[k];
    bool parity = false;
    for (uint8_t pos = 1; pos <= 12; ++pos) {
      if (pos & pp) parity ^= getBit16(word, pos);
    }
    if (parity) syndrome |= pp;
  }

  bool overall = false;
  for (uint8_t pos = 1; pos <= 13; ++pos) overall ^= getBit16(word, pos);

  uint8_t status = 0;
  position = 0;
  if (syndrome != 0 && overall) {
    if (syndrome <= 12) {
      setBit16(word, syndrome, !getBit16(word, syndrome));
      position = syndrome;
      status = 1;
    } else {
      status = 3;
      position = syndrome;
    }
  } else if (syndrome == 0 && overall) {
    setBit16(word, 13, !getBit16(word, 13));
    position = 13;
    status = 2;
  } else if (syndrome != 0 && !overall) {
    position = syndrome;
    status = 3;
  }

  if (status != 3) {
    static const uint8_t dataPos[8] = {3,5,6,7,9,10,11,12};
    data = 0;
    for (uint8_t i = 0; i < 8; ++i) if (getBit16(word, dataPos[i])) data |= (1U << i);
  }
  return status;
}

// ============================================================
// Transmisión física hacia el Arduino remoto
// ============================================================

void writePhyEscaped(uint8_t b) {
  if (b == FLAG || b == ESC) {
    enlace.write(ESC);
    enlace.write(b ^ ESC_XOR);
  } else {
    enlace.write(b);
  }
}

void sendLogicalByteToRemote(uint8_t b) {
  if (b == FLAG) {
    enlace.write(FLAG); // delimitadores físicos sin Hamming
    return;
  }
  if (!hammingEnabled) {
    enlace.write(b); // ya viene escapado por la capa de enlace de la PC
    return;
  }
  uint16_t word = hammingEncode(b);
  writePhyEscaped((uint8_t)(word >> 8));
  writePhyEscaped((uint8_t)word);
}

// ============================================================
// Recepción física desde Arduino remoto
// ============================================================

void resetFrameStats() {
  frameBlocks = frameCorrected = frameGlobalParity = frameDouble = 0;
  lastErrorBlock = 0;
  lastErrorStatus = 0;
  lastErrorPosition = 0;
  lastErrorWord = 0;
}

void beginIncomingFrame() {
  phyInFrame = true;
  phyEscaped = false;
  phyDropFrame = false;
  haveFirstHammingByte = false;
  resetFrameStats();
  ++rxFrameId;
  queueByteToPc(FLAG);
}

void endIncomingFrame() {
  if (!phyInFrame) return;
  // Siempre cerrar el parser de la PC. Si hubo doble error, el byte faltante
  // hará fallar longitud/checksum y la trama será descartada.
  queueByteToPc(FLAG);
  flushPcChunk();
  sendStatsFrameToPc();
  phyInFrame = false;
  phyEscaped = false;
  haveFirstHammingByte = false;
}

void processDecodedPhysicalByte(uint8_t b) {
  if (!hammingEnabled) {
    queueByteToPc(b);
    return;
  }

  if (!haveFirstHammingByte) {
    firstHammingByte = b;
    haveFirstHammingByte = true;
    return;
  }

  uint16_t word = ((uint16_t)firstHammingByte << 8) | b;
  haveFirstHammingByte = false;
  ++frameBlocks;
  uint8_t decoded = 0, position = 0;
  uint8_t status = hammingDecode(word, decoded, position);
  if (status == 1) { ++frameCorrected; ++totalCorrected; }
  else if (status == 2) { ++frameGlobalParity; ++totalGlobalParity; }
  else if (status == 3) { ++frameDouble; ++totalDouble; phyDropFrame = true; }

  if (status != 0) {
    lastErrorBlock = frameBlocks;
    lastErrorStatus = status;
    lastErrorPosition = position;
    lastErrorWord = word;
  }

  if (status != 3 && !phyDropFrame) queueByteToPc(decoded);
}

void processPhysicalByte(uint8_t b) {
  if (b == FLAG) {
    if (!phyInFrame) beginIncomingFrame();
    else endIncomingFrame();
    return;
  }
  if (!phyInFrame) return;

  if (!hammingEnabled) {
    queueByteToPc(b);
    return;
  }

  if (phyEscaped) {
    processDecodedPhysicalByte(b ^ ESC_XOR);
    phyEscaped = false;
  } else if (b == ESC) {
    phyEscaped = true;
  } else {
    processDecodedPhysicalByte(b);
  }
}

// ============================================================
// Configuración proveniente de la PC
// payload: [baud_code, hamming]
// ============================================================

void applyConfig(const uint8_t *payload, uint8_t len) {
  if (len != 2) return;
  uint32_t requestedBaud = payload[0] == 0x02 ? 19200UL : 9600UL;
  bool requestedHamming = payload[1] != 0;

  if (requestedBaud != currentBaud) {
    enlace.end();
    delay(2);
    enlace.begin(requestedBaud);
    currentBaud = requestedBaud;
  }
  hammingEnabled = requestedHamming;

  // Reiniciar estados de decodificación al cambiar la capa física.
  phyInFrame = false;
  phyEscaped = false;
  haveFirstHammingByte = false;
  pcChunkLen = 0;
}

// ============================================================
// Parser del protocolo local USB
// ============================================================

void handleUsbPacket(const uint8_t *packet, uint8_t len) {
  if (len < 4) return;
  uint8_t kind = packet[0];
  uint8_t sequence = packet[1];
  uint8_t payloadLen = packet[2];
  if (payloadLen > USB_CHUNK_SIZE || len != (uint8_t)(4 + payloadLen)) return;
  if (usbChecksum(packet, len - 1) != packet[len - 1]) return;

  const uint8_t *payload = packet + 3;
  if (kind == USB_LOCAL_DATA) {
    // ACK local solamente después de haber entregado el fragmento al enlace.
    for (uint8_t i = 0; i < payloadLen; ++i) sendLogicalByteToRemote(payload[i]);
    sendUsbAck(sequence, false);
  } else if (kind == USB_LOCAL_CONFIG) {
    applyConfig(payload, payloadLen);
    sendUsbAck(sequence, true);
  }
}

void processUsbByte(uint8_t b) {
  if (b == FLAG) {
    if (!usbParser.receiving) {
      usbParser.receiving = true;
      usbParser.escaped = false;
      usbParser.length = 0;
      return;
    }
    if (usbParser.length > 0) handleUsbPacket(usbParser.buffer, usbParser.length);
    usbParser.receiving = true; // este FLAG también deja listo el siguiente paquete
    usbParser.escaped = false;
    usbParser.length = 0;
    return;
  }
  if (!usbParser.receiving) return;
  if (usbParser.escaped) {
    b ^= ESC_XOR;
    usbParser.escaped = false;
  } else if (b == ESC) {
    usbParser.escaped = true;
    return;
  }

  if (usbParser.length < sizeof(usbParser.buffer)) {
    usbParser.buffer[usbParser.length++] = b;
  } else {
    usbParser.receiving = false;
    usbParser.length = 0;
  }
}

// ============================================================
// Arduino
// ============================================================

void setup() {
  Serial.begin(9600);       // USB PC<->Arduino se mantiene a 9600 al arrancar
  enlace.begin(currentBaud);
}

void loop() {
  // Alternar continuamente ambos sentidos. AltSoftSerial gestiona RX/TX por
  // interrupciones y permite que ACK y DATA circulen mientras el otro sentido
  // sigue activo.
  while (Serial.available() > 0) processUsbByte((uint8_t)Serial.read());
  while (enlace.available() > 0) processPhysicalByte((uint8_t)enlace.read());
  flushPcChunk();
}
