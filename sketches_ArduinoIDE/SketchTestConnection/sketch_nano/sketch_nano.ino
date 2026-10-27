#include <SoftwareSerial.h>

SoftwareSerial enlace(8, 9); // RX, TX

void setup() {
  Serial.begin(9600);
  enlace.begin(9600);
}

void loop() {
  if (Serial.available()) {
    String mensajePc = Serial.readStringUntil('\n');
    mensajePc.trim();
    if (mensajePc.startsWith("DUINO_HELLO:")) {
      enlace.println(mensajePc);
    }
  }

  if (enlace.available()) {
    String mensaje = enlace.readStringUntil('\n');
    mensaje.trim();
    if (mensaje.startsWith("DUINO_HELLO:")) {
      String token = mensaje.substring(String("DUINO_HELLO:").length());
      enlace.print("DUINO_ACK:");
      enlace.println(token);
      Serial.print("DUINO_CONNECTED:");
      Serial.println(token);
    } else if (mensaje.startsWith("DUINO_ACK:")) {
      Serial.println(mensaje);
    }
  }
}
