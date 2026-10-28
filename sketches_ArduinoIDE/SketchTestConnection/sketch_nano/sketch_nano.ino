#include <SoftwareSerial.h>

// SoftwareSerial(RX, TX): Nano D8 recibe del UNO D9; Nano D9 transmite al UNO D8.
SoftwareSerial enlace(8, 9);
const long USB_BAUD = 115200;
long linkBaud = 9600;
bool usbInFrame = false;
bool linkInFrame = false;
String usbLine;
String linkLine;

void setLinkBaudFromCommand(String &line) {
  if (!line.startsWith("DUINO_CONFIG|") && !line.startsWith("DUINO_CONFIG_ACK|")) return;
  int first = line.indexOf('|');
  int second = line.indexOf('|', first + 1);
  int third = line.indexOf('|', second + 1);
  if (second < 0 || third < 0) return;
  long requested = line.substring(second + 1, third).toInt();
  if (requested == 9600 || requested == 19200) {
    linkBaud = requested;
    enlace.end();
    enlace.begin(linkBaud);
  }
}

void inspectByte(uint8_t value, bool &inFrame, String &line) {
  if (value == 0x7E) {
    inFrame = !inFrame;
    line = "";
    return;
  }
  if (inFrame) return;
  if (value == '\n') {
    setLinkBaudFromCommand(line);
    line = "";
  } else if (value != '\r' && line.length() < 100) {
    line += (char)value;
  } else if (line.length() >= 100) {
    line = "";
  }
}

void setup() {
  Serial.begin(USB_BAUD);
  enlace.begin(linkBaud);
}

void loop() {
  while (Serial.available()) {
    uint8_t value = Serial.read();
    enlace.write(value);
    inspectByte(value, usbInFrame, usbLine);
  }
  while (enlace.available()) {
    uint8_t value = enlace.read();
    Serial.write(value);
    inspectByte(value, linkInFrame, linkLine);
  }
}
