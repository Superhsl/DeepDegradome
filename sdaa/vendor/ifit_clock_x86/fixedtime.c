/* Diagnostic control of time-based RNG initialization; not production code. */
#include <stdio.h>
#include <time.h>
static unsigned long calls;
time_t time(time_t *result) {
    const time_t epoch = 1700000123;
    ++calls;
    if (result) *result = epoch;
    return epoch;
}
__attribute__((destructor)) static void report_time_calls(void) {
    fprintf(stderr, "DD_FIXED_TIME epoch=1700000123 time_calls=%lu\n", calls);
}
