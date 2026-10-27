#include <SoftwareSerial.h>

SoftwareSerial enlace(8, 9); // RX, TX

void setup() {
  Serial.begin(9600);
  enlace.begin(9600);

  Serial.println("Arduino Uno listo!");
  Serial.println("Escribe un mensaje para el Nano:");
}

void loop() {
  // La aplicación del computador Uno inicia el handshake por USB.
  if (Serial.available()) {
    String mensaje = Serial.readStringUntil('\n');
    mensaje.trim();
    if (mensaje.startsWith("DUINO_HELLO:")) {
      enlace.println(mensaje);
    }
  }

  // El Nano devuelve el token solo si recibió el mensaje por RX/TX.
  if (enlace.available()) {
    String respuesta = enlace.readStringUntil('\n');
    respuesta.trim();
    if (respuesta.startsWith("DUINO_HELLO:")) {
      String token = respuesta.substring(String("DUINO_HELLO:").length());
      enlace.print("DUINO_ACK:");
      enlace.println(token);
      Serial.print("DUINO_CONNECTED:");
      Serial.println(token);
    } else if (respuesta.startsWith("DUINO_ACK:")) {
      Serial.println(respuesta);
    }
  }
}
