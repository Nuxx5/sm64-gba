/* Exhaustive check of src/fast/sqrtf_exact.c: every 32-bit pattern, against
 * the host's IEEE sqrtf (SSE sqrtss: correctly rounded). Build: see the
 * Makefile's sqrtf-check target. */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

float __wrap_sqrtf(float x);
float __real_sqrtf(float x) { return sqrtf(x); }

int main(void) {
    uint64_t i, bad = 0;
    for (i = 0; i <= 0xFFFFFFFFull; i++) {
        uint32_t b = (uint32_t) i, r1, r2;
        float x, a, c;
        memcpy(&x, &b, 4);
        a = __wrap_sqrtf(x);
        c = sqrtf(x);
        memcpy(&r1, &a, 4);
        memcpy(&r2, &c, 4);
        if (r1 != r2 && !(isnan(a) && isnan(c))) {
            if (bad < 10) printf("MISMATCH %08x: %08x vs %08x\n", b, r1, r2);
            bad++;
        }
    }
    printf("%s: %llu mismatches over 2^32 inputs\n", bad ? "FAIL" : "PASS", (unsigned long long) bad);
    return bad != 0;
}
