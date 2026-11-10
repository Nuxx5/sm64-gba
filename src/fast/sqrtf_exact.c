/*
 * Correctly rounded single-precision square root without the bit-by-bit
 * loop: a 7-bit table of 1/sqrt, two Newton steps on the ARM's 32x32->64
 * multiplier, then an exact integer check that fixes the last bits and
 * rounds to nearest (a square root is never exactly halfway, so there is no
 * tie). Same results as the IEEE operation, bit for bit: src/test/sqrtf_check.c
 * compares it with the host's hardware sqrtf on all 2^32 inputs.
 *
 * Inputs that aren't positive finite numbers (negative, -0, infinity, NaN)
 * go to the original sqrtf, so their special results are the original's too.
 */
#include <stdint.h>

float __real_sqrtf(float x);

#ifdef __arm__
#define FAST __attribute__((section(".iwram"), noinline, target("arm")))
#else
#define FAST
#endif

/* round(2^31 / sqrt((i + 0.5) / 32)) for i = 32..127 */
static const uint32_t kRsqrt[96] = {
0x7f02f623, 0x7d19fca0, 0x7b466dd8, 0x7986c4e4, 0x77d9a26e, 0x763dc824, 0x74b214d4, 0x73358118, 0x71c71c72, 0x70660acc, 0x6f11824c, 0x6dc8c96e, 0x6c8b355b, 0x6b582874, 0x6a2f1107, 0x690f682b, 0x67f8b0c5, 0x66ea769b, 0x65e44d8c, 0x64e5d0da, 0x63eea287, 0x62fe6ac2, 0x6214d764, 0x61319b7c, 0x60546ee2, 0x5f7d0dd6, 0x5eab38ac, 0x5ddeb37a, 0x5d1745d1, 0x5c54ba7d, 0x5b96df46, 0x5add84bb, 0x5a287e03, 0x5977a0ac, 0x58cac480, 0x5821c364, 0x577c7930, 0x56dac38e, 0x563c81e0, 0x55a19522, 0x5509dfd0, 0x547545d0, 0x53e3ac5b, 0x5354f9e7, 0x52c91618, 0x523fe9ac, 0x51b95e6b, 0x51355f1a, 0x50b3d768, 0x5034b3e7, 0x4fb7e1fa, 0x4f3d4fcf, 0x4ec4ec4f, 0x4e4ea718, 0x4dda7073, 0x4d683948, 0x4cf7f31b, 0x4c899000, 0x4c1d0294, 0x4bb23df9, 0x4b4935cf, 0x4ae1de2a, 0x4a7c2b93, 0x4a1812fa, 0x49b589bb, 0x49548592, 0x48f4fc97, 0x4896e53d, 0x483a364d, 0x47dee6e1, 0x4784ee60, 0x472c447c, 0x46d4e130, 0x467ebcba, 0x4629cf98, 0x45d6128a, 0x45837e88, 0x45320cc8, 0x44e1b6b4, 0x449275ed, 0x44444444, 0x43f71bbf, 0x43aaf68f, 0x435fcf15, 0x43159fdc, 0x42cc6398, 0x42841527, 0x423caf8d, 0x41f62df2, 0x41b08ba2, 0x416bc40d, 0x4127d2c3, 0x40e4b374, 0x40a261ef, 0x4060da22, 0x40201814
};

FAST float __wrap_sqrtf(float x) {
    union { float f; uint32_t u; } v;
    uint32_t b, m, y, y2, ay2, q;
    int32_t e;
    uint64_t M, qq;
    v.f = x;
    b = v.u;
    if (b == 0) return x;                           /* +0 */
    if (b >= 0x7F800000u) return __real_sqrtf(x);   /* negative, -0, inf, NaN */
    e = (int32_t) (b >> 23);
    m = b & 0x7FFFFFu;
    if (e == 0) {                                   /* subnormal: normalize */
        e = 1;
        while (!(m & 0x800000u)) {
            m <<= 1;
            e--;
        }
    } else {
        m |= 0x800000u;
    }
    e -= 127;                                       /* x = m * 2^(e - 23), m in [2^23, 2^24) */
    if (e & 1) {                                    /* make the exponent even */
        m <<= 1;
        e--;
    }
    /* sqrt(x) = sqrt(M) * 2^((e - 46) / 2) with M = m * 2^23 in [2^46, 2^48):
     * q = floor(sqrt(M)) has 24 bits, the result's mantissa */
    y = kRsqrt[(m >> 18) - 32];                     /* 1/sqrt(m / 2^23), Q31 */
    y2 = (uint32_t) (((uint64_t) y * y) >> 31);
    ay2 = (uint32_t) (((uint64_t) m * y2) >> 23);
    y = (uint32_t) (((uint64_t) y * (0x180000000ull - ay2)) >> 32);
    y2 = (uint32_t) (((uint64_t) y * y) >> 31);
    ay2 = (uint32_t) (((uint64_t) m * y2) >> 23);
    y = (uint32_t) (((uint64_t) y * (0x180000000ull - ay2)) >> 32);
    q = (uint32_t) (((uint64_t) m * y) >> 31);      /* ~ sqrt(M), within a few units */
    M = (uint64_t) m << 23;
    qq = (uint64_t) q * q;
    while (qq > M) {
        q--;
        qq = (uint64_t) q * q;
    }
    while (qq + 2 * (uint64_t) q + 1 <= M) {
        q++;
        qq = (uint64_t) q * q;
    }
    /* nearest: round up when M - q^2 > q, i.e. M > (q + 1/2)^2 */
    v.u = ((uint32_t) (e / 2 + 127) << 23) + (q - 0x800000u) + (M - qq > q ? 1u : 0u);
    return v.f;
}
