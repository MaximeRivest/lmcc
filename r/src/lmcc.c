/* The three things base R cannot do exactly (kernel §3a, §7a):
 *  - read a decimal as binary64, correctly rounded (R's own as.numeric is
 *    not: "1.00000000000000011102230246251565404236316680908203125" reads as
 *    the next double up); C's strtod is correctly rounded on glibc, macOS
 *    and Windows' UCRT;
 *  - spell a double by ECMAScript Number::toString (shortest round-trip
 *    digits, found with %.*e and checked with strtod);
 *  - SHA-256 of UTF-8 bytes (FIPS 180-4).
 * R keeps LC_NUMERIC at "C", so strtod and printf use '.'. */
#include <R.h>
#include <Rinternals.h>
#include <R_ext/Rdynload.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <math.h>

SEXP lmcc_strtod(SEXP x) {
    const char *s = CHAR(STRING_ELT(x, 0));
    return ScalarReal(strtod(s, NULL));
}

/* Shortest decimal digits d1..dk and n with |v| = 0.d1..dk x 10^n. */
static void shortest(double v, char *digits, int *n) {
    char buf[40];
    for (int p = 0; p <= 16; p++) {
        snprintf(buf, sizeof buf, "%.*e", p, v);
        if (strtod(buf, NULL) == v) break;
    }
    char *e = strchr(buf, 'e');
    int exp10 = atoi(e + 1);
    int k = 0;
    for (char *c = buf; c < e; c++) if (*c >= '0' && *c <= '9') digits[k++] = *c;
    while (k > 1 && digits[k - 1] == '0') k--;
    digits[k] = '\0';
    *n = exp10 + 1;
}

SEXP lmcc_format_number(SEXP x) {
    double v = REAL(x)[0];
    char out[400], digits[24];
    if (v == 0) return mkString("0");
    int n, pos = 0;
    if (v < 0) { out[pos++] = '-'; v = -v; }
    shortest(v, digits, &n);
    int k = (int) strlen(digits);
    if (k <= n && n <= 21) {
        memcpy(out + pos, digits, k); pos += k;
        for (int i = 0; i < n - k; i++) out[pos++] = '0';
    } else if (0 < n && n <= 21) {
        memcpy(out + pos, digits, n); pos += n;
        out[pos++] = '.';
        memcpy(out + pos, digits + n, k - n); pos += k - n;
    } else if (-6 < n && n <= 0) {
        out[pos++] = '0'; out[pos++] = '.';
        for (int i = 0; i < -n; i++) out[pos++] = '0';
        memcpy(out + pos, digits, k); pos += k;
    } else {
        int e = n - 1;
        out[pos++] = digits[0];
        if (k > 1) { out[pos++] = '.'; memcpy(out + pos, digits + 1, k - 1); pos += k - 1; }
        pos += snprintf(out + pos, sizeof out - pos, "e%c%d", e >= 0 ? '+' : '-', e >= 0 ? e : -e);
    }
    out[pos] = '\0';
    return mkString(out);
}

/* The shortest digits and n, for the reference's repr in hints. */
SEXP lmcc_shortest(SEXP x) {
    char digits[24];
    int n;
    shortest(fabs(REAL(x)[0]), digits, &n);
    SEXP out = PROTECT(allocVector(VECSXP, 2));
    SET_VECTOR_ELT(out, 0, mkString(digits));
    SET_VECTOR_ELT(out, 1, ScalarInteger(n));
    UNPROTECT(1);
    return out;
}

static const uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void block(uint32_t h[8], const unsigned char *p) {
    uint32_t w[64];
    for (int t = 0; t < 16; t++)
        w[t] = ((uint32_t) p[4 * t] << 24) | ((uint32_t) p[4 * t + 1] << 16) | ((uint32_t) p[4 * t + 2] << 8) | p[4 * t + 3];
    for (int t = 16; t < 64; t++) {
        uint32_t s0 = ROR(w[t - 15], 7) ^ ROR(w[t - 15], 18) ^ (w[t - 15] >> 3);
        uint32_t s1 = ROR(w[t - 2], 17) ^ ROR(w[t - 2], 19) ^ (w[t - 2] >> 10);
        w[t] = w[t - 16] + s0 + w[t - 7] + s1;
    }
    uint32_t a = h[0], b = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
    for (int t = 0; t < 64; t++) {
        uint32_t t1 = hh + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + K[t] + w[t];
        uint32_t t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));
        hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
}

SEXP lmcc_sha256(SEXP raw) {
    const unsigned char *p = RAW(raw);
    uint64_t len = (uint64_t) XLENGTH(raw);
    uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    uint64_t full = len / 64;
    for (uint64_t i = 0; i < full; i++) block(h, p + 64 * i);
    unsigned char tail[128];
    size_t rem = (size_t) (len - 64 * full);
    memset(tail, 0, sizeof tail);
    memcpy(tail, p + 64 * full, rem);
    tail[rem] = 0x80;
    size_t total = rem + 1 + 8 <= 64 ? 64 : 128;
    uint64_t bits = len * 8;
    for (int i = 0; i < 8; i++) tail[total - 1 - i] = (unsigned char) (bits >> (8 * i));
    block(h, tail);
    if (total == 128) block(h, tail + 64);
    char hex[65];
    for (int i = 0; i < 8; i++) snprintf(hex + 8 * i, 9, "%08x", h[i]);
    return mkString(hex);
}

static const R_CallMethodDef calls[] = {
    {"lmcc_strtod", (DL_FUNC) &lmcc_strtod, 1},
    {"lmcc_format_number", (DL_FUNC) &lmcc_format_number, 1},
    {"lmcc_shortest", (DL_FUNC) &lmcc_shortest, 1},
    {"lmcc_sha256", (DL_FUNC) &lmcc_sha256, 1},
    {NULL, NULL, 0}};

void R_init_lmcc(DllInfo *dll) {
    R_registerRoutines(dll, NULL, calls, NULL, NULL);
    R_useDynamicSymbols(dll, FALSE);
    R_forceSymbols(dll, TRUE);
}
