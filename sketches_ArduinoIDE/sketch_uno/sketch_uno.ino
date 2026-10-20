#include <SoftwareSerial.h>

SoftwareSerial enlace(8, 9); // RX, TX

void setup() {
  Serial.begin(9600);
  enlace.begin(9600);

  Serial.println("Arduino Uno listo!");
  Serial.println("Escribe un mensaje para el Nano:");
}

void loop() {
  // Enviar mensajes de laptop al Nano
  if (Serial.available()) {
    String mensaje = Serial.readStringUntil('\n');
    mensaje.trim();

    if (mensaje.length() > 0) {
      Serial.print("Enviando: ");
      Serial.println(mensaje);

      enlace.println(mensaje);
    }
  }

  // Recibir respuestas del Nano
  if (enlace.available()) {
    String respuesta = enlace.readStringUntil('\n');
    respuesta.trim();

    Serial.print("Respuesta del Nano: ");
    Serial.println(respuesta);
  }
}