"""Public DH-parameter validation required by Telegram before native key exchange.

The native engine owns random private exponents, shared keys and media encryption.
This module never receives those secrets. Successful checks are bounded and cached.
"""
from functools import lru_cache
import secrets

# Telegram explicitly recommends embedding a prevalidated public safe prime so
# the first call on a slow device avoids repeated primality work. The generator
# is still checked on every cache miss; any other prime receives full validation.
# Source: https://core.telegram.org/mtproto/security_guidelines
TELEGRAM_SAFE_PRIME = bytes.fromhex('''
C71CAEB9C6B1C9048E6C522F70F13F73980D40238E3E21C14934D037563D930F
48198A0AA7C14058229493D22530F4DBFA336F6E0AC925139543AED44CCE7C37
20FD51F69458705AC68CD4FE6B6B13ABDC9746512969328454F18FAF8C595F6424
77FE96BB2A941D5BCD1D4AC8CC49880708FA9B378E3C4F3A9060BEE67CF9A4A4
A695811051907E162753B56B0F6B410DBA74D8A84B2A14B3144E0EF1284754
FD17ED950D5965B4B9DD46582DB1178D169C6BC465B0D6FF9CA3928FEF5B9AE4
E418FC15E83EBEA0F87FA9FF5EED70050DED2849F47BF959D956850CE929851F
0D8115F635B105EE2E4E15D04B2454BF6F4FADF034B10403119CD8E3B92FCC5B
''')


def _probable_prime(number, rounds=64):
    if number < 2:
        return False
    for divisor in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if number % divisor == 0:
            return number == divisor
    odd, shifts = number - 1, 0
    while not odd & 1:
        shifts += 1
        odd >>= 1
    for _ in range(rounds):
        value = pow(secrets.randbelow(number - 3) + 2, odd, number)
        if value in (1, number - 1):
            continue
        for _ in range(shifts - 1):
            value = value * value % number
            if value == number - 1:
                break
        else:
            return False
    return True


@lru_cache(maxsize=4)
def validate_dh(generator, prime):
    """Validate a safe 2048-bit prime and generator, off the asyncio/UI threads.

64 independent Miller-Rabin rounds give a <=2^-128 false-prime bound per
candidate. Both p and (p-1)/2 are checked, as specified by Telegram.
"""
    if not isinstance(prime, bytes) or len(prime) != 256:
        raise ValueError('Invalid call encryption parameters')
    number = int.from_bytes(prime, 'big')
    if number.bit_length() != 2048 or generator not in range(2, 8):
        raise ValueError('Invalid call encryption parameters')
    residues = {2: (8, (7,)), 3: (3, (2,)), 4: (1, (0,)),
                5: (5, (1, 4)), 6: (24, (19, 23)), 7: (7, (3, 5, 6))}
    modulus, allowed = residues[generator]
    if number % modulus not in allowed:
        raise ValueError('Invalid call encryption generator')
    if prime == TELEGRAM_SAFE_PRIME:
        return True
    if not _probable_prime(number) or not _probable_prime((number - 1) // 2):
        raise ValueError('Unsafe call encryption parameters')
    return True
