#pragma once

#include <stddef.h>
#include <stdbool.h>

// Arduino PSRAM API. The tuya_open core does not ship esp32-hal-psram, so
// sketches had to call IDF heap_caps directly; these wrap MALLOC_CAP_SPIRAM.
#ifdef __cplusplus
extern "C" {
#endif

bool psramInit(void);
bool psramFound(void);
void *ps_malloc(size_t size);
void *ps_calloc(size_t n, size_t size);
void *ps_realloc(void *ptr, size_t size);

#ifdef __cplusplus
}
#endif
