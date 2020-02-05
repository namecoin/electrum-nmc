from . import bitcoin
from .bitcoin import public_key_to_p2pkh
from .util import BitcoinException, bfh

def xpubkey_to_address(x_pubkey):
    if x_pubkey[0:2] == 'fd':
        address = bitcoin.script_to_address(x_pubkey[2:])
        return x_pubkey, address
    if x_pubkey[0:2] in ['02', '03', '04']:
        pubkey = x_pubkey
    elif x_pubkey[0:2] == 'ff':
        xpub, s = BIP32_KeyStore.parse_xpubkey(x_pubkey)
        pubkey = BIP32_KeyStore.get_pubkey_from_xpub(xpub, s)
    elif x_pubkey[0:2] == 'fe':
        mpk, s = Old_KeyStore.parse_xpubkey(x_pubkey)
        pubkey = Old_KeyStore.get_pubkey_from_mpk(mpk, s[0], s[1])
    else:
        raise BitcoinException("Cannot parse pubkey. prefix: {}"
                               .format(x_pubkey[0:2]))
    if pubkey:
        address = public_key_to_p2pkh(bfh(pubkey))
    return pubkey, address

def xpubkey_to_pubkey(x_pubkey):
    pubkey, address = xpubkey_to_address(x_pubkey)
    return pubkey
