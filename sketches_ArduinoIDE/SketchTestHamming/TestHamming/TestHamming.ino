#include "Hamming.h"

Hamming hamming;

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("====================================");
  Serial.println("       PRUEBAS HAMMING SECDED");
  Serial.println("====================================");

  testBasico();
  testErrorUnBit();
  testErrorParidadGlobal();
  testErrorDosBits();
}

void loop() {
  // Las pruebas se ejecutan una sola vez.
}


// ============================================================
// TEST 1: Codificar y decodificar sin errores
// ============================================================

void testBasico() {
  Serial.println();
  Serial.println("--- TEST 1: SIN ERRORES ---");

  unsigned char data = 0xA5;

  int code = hamming.code_hamming(data);

  Serial.print("Dato original:      ");
  Hamming::printBin(data, 8);

  Serial.print("Codigo Hamming:     ");
  Hamming::printBin(code, 13);

  int result = hamming.decode_hamming(code);

  Serial.print("Sindrome/resultado: ");
  Serial.println(result);

  Serial.print("Dato decodificado:  ");
  Hamming::printBin(hamming.decodedByte(), 8);

  if (result == 0 && hamming.decodedByte() == data) {
    Serial.println("RESULTADO: PASS");
  } else {
    Serial.println("RESULTADO: FAIL");
  }
}


// ============================================================
// TEST 2: Introducir error en un bit del Hamming(12,8)
// ============================================================

void testErrorUnBit() {
  Serial.println();
  Serial.println("--- TEST 2: ERROR DE 1 BIT ---");

  unsigned char data = 0xA5;

  int code = hamming.code_hamming(data);

  // Alteramos el bit de indice 4.
  // Indice 4 = posicion Hamming 5.
  int corrupted = code ^ (1 << 4);

  Serial.print("Original:            ");
  Hamming::printBin(code, 13);

  Serial.print("Con error:           ");
  Hamming::printBin(corrupted, 13);

  hamming.resetCounters();

  int result = hamming.decode_hamming(corrupted);

  Serial.print("Error detectado pos: ");
  Serial.println(result);

  Serial.print("Dato decodificado:   ");
  Hamming::printBin(hamming.decodedByte(), 8);

  Serial.print("Errores de 1 bit:    ");
  Serial.println(hamming.singleBitErrors());

  if (result == 5) {
    Serial.println("DETECCION: PASS");
  } else {
    Serial.println("DETECCION: FAIL");
  }

  // Corregimos usando la posicion indicada por decode_hamming()
  if (result > 0) {
    int corrected = corrupted ^ (1 << (result - 1));

    Serial.print("Codigo corregido:    ");
    Hamming::printBin(corrected, 13);

    int result2 = hamming.decode_hamming(corrected);

    Serial.print("Dato recuperado:     ");
    Hamming::printBin(hamming.decodedByte(), 8);

    if (result2 == 0 && hamming.decodedByte() == data) {
      Serial.println("CORRECCION: PASS");
    } else {
      Serial.println("CORRECCION: FAIL");
    }
  }
}


// ============================================================
// TEST 3: Error solamente en la paridad global
// ============================================================

void testErrorParidadGlobal() {
  Serial.println();
  Serial.println("--- TEST 3: ERROR EN PARIDAD GLOBAL ---");

  unsigned char data = 0xA5;

  int code = hamming.code_hamming(data);

  // El bit 12 es el bit de paridad global
  int corrupted = code ^ (1 << 12);

  Serial.print("Original:            ");
  Hamming::printBin(code, 13);

  Serial.print("Con error global:    ");
  Hamming::printBin(corrupted, 13);

  hamming.resetCounters();

  int result = hamming.decode_hamming(corrupted);

  Serial.print("Resultado:           ");
  Serial.println(result);

  Serial.print("Errores paridad:     ");
  Serial.println(hamming.globalParityErrors());

  Serial.print("Dato decodificado:   ");
  Hamming::printBin(hamming.decodedByte(), 8);

  if (result == 0 &&
      hamming.globalParityErrors() == 1 &&
      hamming.decodedByte() == data) {
    Serial.println("RESULTADO: PASS");
  } else {
    Serial.println("RESULTADO: FAIL");
  }
}


// ============================================================
// TEST 4: Introducir dos errores
// ============================================================

void testErrorDosBits() {
  Serial.println();
  Serial.println("--- TEST 4: ERROR DE 2 BITS ---");

  unsigned char data = 0xA5;

  int code = hamming.code_hamming(data);

  // Alteramos dos bits
  int corrupted = code ^ (1 << 2) ^ (1 << 5);

  Serial.print("Original:            ");
  Hamming::printBin(code, 13);

  Serial.print("Con dos errores:     ");
  Hamming::printBin(corrupted, 13);

  hamming.resetCounters();

  int result = hamming.decode_hamming(corrupted);

  Serial.print("Resultado:           ");
  Serial.println(result);

  Serial.print("Errores de 2 bits:   ");
  Serial.println(hamming.twoBitErrors());

  if (result == -1 && hamming.twoBitErrors() == 1) {
    Serial.println("RESULTADO: PASS");
  } else {
    Serial.println("RESULTADO: FAIL");
  }
}