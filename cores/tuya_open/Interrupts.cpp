#include "Arduino.h"

#include "tkl_gpio.h"
#include "freertos/FreeRTOS.h"

// Global IRQ enable/disable. ESP32 is SMP, so a portMUX spinlock gives a
// critical section that also guards against the other core.
static portMUX_TYPE s_irq_mux = portMUX_INITIALIZER_UNLOCKED;

extern "C" void noInterrupts(void)
{
    portENTER_CRITICAL(&s_irq_mux);
}

extern "C" void interrupts(void)
{
    portEXIT_CRITICAL(&s_irq_mux);
}

void attachInterrupt(pin_size_t interruptNumber, voidFuncPtr callback, PinStatus mode)
{
    TUYA_GPIO_IRQ_T irqConfig;
    irqConfig.cb = (TUYA_GPIO_IRQ_CB)callback;
    irqConfig.arg = NULL;

    switch (mode) {
        case FALLING:
            irqConfig.mode = TUYA_GPIO_IRQ_FALL;
        break;
        case RISING:
            irqConfig.mode = TUYA_GPIO_IRQ_RISE;
        break;
        default : return;
    }

    tkl_gpio_irq_init((TUYA_GPIO_NUM_E)interruptNumber, &irqConfig);
    tkl_gpio_irq_enable((TUYA_GPIO_NUM_E)interruptNumber);

    return;
}
void attachInterruptParam(pin_size_t interruptNumber, voidFuncPtrParam callback, PinStatus mode, void* param)
{
    TUYA_GPIO_IRQ_T irqConfig;
    irqConfig.cb = (TUYA_GPIO_IRQ_CB)callback;
    irqConfig.arg = param;

    switch (mode) {
        case FALLING:
            irqConfig.mode = TUYA_GPIO_IRQ_FALL;
        break;
        case RISING:
            irqConfig.mode = TUYA_GPIO_IRQ_RISE;
        break;
        default : return;
    }

    tkl_gpio_irq_init((TUYA_GPIO_NUM_E)interruptNumber, &irqConfig);
    tkl_gpio_irq_enable((TUYA_GPIO_NUM_E)interruptNumber);

    return;
}
void detachInterrupt(pin_size_t interruptNumber)
{
    tkl_gpio_irq_disable((TUYA_GPIO_NUM_E)interruptNumber);

    return;
}
