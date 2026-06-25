#include "esp32-hal-psram.h"
#include "esp_heap_caps.h"

// Backed by the IDF SPIRAM heap. When PSRAM is not enabled/initialized the
// SPIRAM capability has zero total size, so psramFound() is false and the
// ps_*alloc() helpers return NULL — callers must check, as with malloc().

bool psramInit(void)
{
    return heap_caps_get_total_size(MALLOC_CAP_SPIRAM) > 0;
}

bool psramFound(void)
{
    return heap_caps_get_total_size(MALLOC_CAP_SPIRAM) > 0;
}

void *ps_malloc(size_t size)
{
    return heap_caps_malloc(size, MALLOC_CAP_SPIRAM);
}

void *ps_calloc(size_t n, size_t size)
{
    return heap_caps_calloc(n, size, MALLOC_CAP_SPIRAM);
}

void *ps_realloc(void *ptr, size_t size)
{
    return heap_caps_realloc(ptr, size, MALLOC_CAP_SPIRAM);
}
