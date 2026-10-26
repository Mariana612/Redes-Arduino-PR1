#ifndef HAMMING_H
#define HAMMING_H

#include <Arduino.h>

class Hamming {
public:
  Hamming() {
    resetCounters();
    _decodedByte = 0;
  }

  // Codifica un byte en 13 bits (Hamming(12,8) + paridad global)
  int code_hamming(unsigned char data) {
    int hammingCode = 0;
    int powIndex = 0;
    int dataIndex = 0;
    int parity_bit;

    unsigned char parity_bits = get_hamming_bits(data);

    for (int i = 0; i < 12; i++) {
      if ((1 << powIndex) == i + 1) {
        parity_bit = parity_bits & 1;
        parity_bits >>= 1;
        powIndex++;
      } else {
        parity_bit = (data >> dataIndex) & 1;
        dataIndex++;
      }
      hammingCode |= parity_bit << i;
    }

    // Bit de paridad global
    hammingCode |= (__builtin_popcount(hammingCode) % 2) << 12;
    return hammingCode;
  }

  // Decodifica un código de 13 bits.
  // Retorna: 0 sin error (o error solo en paridad global),
  //          posición del error si fue 1 bit, -1 si fueron 2 errores.
  int decode_hamming(int code) {
    unsigned char parity_bits = 0;
    int powIndex = 0;
    int parityIndex = 0;
    int dataIndex = 0;

    _code = code;
    _decodedByte = 0;

    for (int i = 0; i < 12; i++) {
      if ((1 << powIndex) == i + 1) {
        parity_bits |= ((code >> i) & 1) << parityIndex;
        parityIndex++;
        powIndex++;
      } else {
        _decodedByte |= ((code >> i) & 1) << dataIndex;
        dataIndex++;
      }
    }

    unsigned char calculated = get_hamming_bits(_decodedByte);

    int syndrome = calculated ^ parity_bits;
    bool global_parity = (__builtin_popcount(code & 8191) % 2) == 0;

    return check(syndrome, global_parity);
  }

  // Getters
  int decodedByte() const { return _decodedByte; }
  int singleBitErrors() const { return _singleBitErrors; }
  int twoBitErrors() const { return _twoBitErrors; }
  int globalParityErrors() const { return _globalParityErrors; }

  void resetCounters() {
    _singleBitErrors = 0;
    _twoBitErrors = 0;
    _globalParityErrors = 0;
  }

  // Imprime en binario con ceros a la izquierda
  static void printBin(unsigned int value, int bits) {
    for (int i = bits - 1; i >= 0; i--) {
      Serial.print((value >> i) & 1);
    }
    Serial.println();
  }

private:
  int _code;
  int _decodedByte;
  int _singleBitErrors;
  int _twoBitErrors;
  int _globalParityErrors;

  unsigned char get_hamming_bits(unsigned char data) {
    const unsigned char masks[] = {91, 109, 142, 240};
    unsigned char response = 0;

    for (int i = 0; i < 4; i++) {
      response |= (__builtin_popcount(masks[i] & data) % 2) << i;
    }
    return response;
  }

  int check(int syndrome, bool global_parity) {
    if (!syndrome && global_parity) {
      return 0;                    // sin errores
    } else if (syndrome && !global_parity) {
      _singleBitErrors++;
      return syndrome;             // 1 error
    } else if (!syndrome && !global_parity) {
      _globalParityErrors++;       // error solo en el bit de paridad global
      return 0;
    } else {
      _twoBitErrors++;             // 2 errores, no corregible
      return -1;
    }
  }
};

#endif
