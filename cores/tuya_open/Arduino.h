#ifndef ARDUINO_H
#define ARDUINO_H

#include "pins_arduino.h"
#include "api/ArduinoAPI.h"

// Common.h mandates the core define interrupts() / noInterrupts().
#ifdef __cplusplus
extern "C" {
#endif
void interrupts(void);
void noInterrupts(void);
#ifdef __cplusplus
}
#endif

#include "esp32-hal-psram.h"

#if defined(__cplusplus) && !defined(c_plusplus)

using namespace arduino;

#include "SerialUART.h"
#define Serial _SerialUART0_

#endif // __cplusplus

#endif // ARDUINO_H
