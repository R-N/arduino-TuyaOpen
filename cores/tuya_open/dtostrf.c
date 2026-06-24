// Provide dtostrf() for libraries that use it; the standard lib on this
// toolchain does not. Pulls in the ArduinoCore-API emulation impl.
#include "api/deprecated-avr-comp/avr/dtostrf.c.impl"
