#include "intro_codec.h"

int intro_decode(const unsigned short *source, unsigned sourceWords,
                 volatile unsigned short *destination, unsigned words) {
    unsigned at = 0, out = 0;
    while (at < sourceWords) {
        unsigned command = source[at++], count = command & 0x3FFF;
        unsigned kind = command >> 14;
        if (command == 0) return out == words && at == sourceWords;
        if (!count || count > words - out || kind == 3) return 0;
        if (kind == 0) {
            unsigned end;
            if (count > sourceWords - at) return 0;
            end = out + count;
            while (out < end) destination[out++] = source[at++];
        } else if (kind == 1) {
            unsigned value, end;
            if (at == sourceWords) return 0;
            value = source[at++];
            end = out + count;
            while (out < end) destination[out++] = value;
        } else {
            out += count;
        }
    }
    return 0;
}
