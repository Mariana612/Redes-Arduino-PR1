#include <SoftwareSerial.h>

SoftwareSerial enlace(8, 9); // RX, TX

void setup() {
  enlace.begin(9600);
}

void loop() {
  if (enlace.available()) {
    String mensaje = enlace.readStringUntil('\n');
    mensaje.trim();

    if (mensaje.length() > 0) {
      enlace.println("Hola Uno, mensaje recibido!");
    }
  }
}