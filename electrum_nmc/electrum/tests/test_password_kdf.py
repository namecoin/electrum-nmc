import base64
import os
import tempfile
import unittest
import zlib

from electrum import ecc
from electrum.crypto import (PW_HASH_VERSION_LATEST, pw_decode,
                             pw_decode_with_version_and_mac, pw_encode,
                             pw_encode_with_version_and_mac)
from electrum.storage import StorageEncryptionVersion, WalletStorage
from electrum.util import InvalidPassword, bfh


class TestPasswordKDF(unittest.TestCase):

    def test_legacy_keystore_ciphertext(self):
        # Generated with password hash version 1. Keep this decryption path
        # working so existing wallets remain readable.
        ciphertext = 'DvDyFwEpHqEHPLvZzHXFKttG7b7Ge7qTAlVSUNuwgapjwIOW9rvqqCJzSRCl0ler'
        self.assertEqual('legacy plaintext',
                         pw_decode(ciphertext, 'password', version=1))

    def test_keystore_uses_versioned_salted_scrypt(self):
        ciphertext = pw_encode_with_version_and_mac(b'secret', 'password')
        raw = base64.b64decode(ciphertext)
        self.assertEqual(2, PW_HASH_VERSION_LATEST)
        self.assertEqual(2, raw[0])
        self.assertEqual(b'secret', pw_decode_with_version_and_mac(ciphertext, 'password'))
        with self.assertRaises(InvalidPassword):
            pw_decode_with_version_and_mac(ciphertext, 'wrong password')

    def test_keystore_salts_are_random(self):
        first = base64.b64decode(pw_encode(b'secret', 'password', version=2))
        second = base64.b64decode(pw_encode(b'secret', 'password', version=2))
        self.assertNotEqual(first[:16], second[:16])
        self.assertEqual('secret', pw_decode(base64.b64encode(first).decode(), 'password', version=2))

    def test_storage_legacy_bie1_roundtrip(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            storage = WalletStorage(path)
            key = storage.get_eckey_from_password('legacy')
            storage.raw = ecc.ECPubkey(bfh(key.get_public_key_hex())).encrypt_message(
                zlib.compress(b'{"legacy": true}'), b'BIE1').decode()
            storage._encryption_version = StorageEncryptionVersion.USER_PASSWORD
            storage.decrypt('legacy')
            self.assertEqual('{"legacy": true}', storage.read())
        finally:
            os.unlink(path)

    def test_storage_legacy_bie2_roundtrip(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            storage = WalletStorage(path)
            key = storage.get_eckey_from_password('hardware-wallet-password')
            storage.raw = ecc.ECPubkey(bfh(key.get_public_key_hex())).encrypt_message(
                zlib.compress(b'{"legacy": "BIE2"}'), b'BIE2').decode()
            storage._encryption_version = StorageEncryptionVersion.XPUB_PASSWORD
            storage.decrypt('hardware-wallet-password')
            self.assertEqual('{"legacy": "BIE2"}', storage.read())
        finally:
            os.unlink(path)

    def test_storage_bie3_roundtrip_and_wrong_password(self):
        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            storage = WalletStorage(path)
            storage.set_password('correct horse', StorageEncryptionVersion.USER_PASSWORD)
            storage.write('{"seed_version": 13}')
            with open(path) as f:
                raw = base64.b64decode(f.read())
            self.assertEqual(b'BIE3', raw[:4])
            self.assertEqual(16, len(raw[4:20]))

            reopened = WalletStorage(path)
            with self.assertRaises(InvalidPassword):
                reopened.decrypt('wrong password')
            reopened = WalletStorage(path)
            reopened.decrypt('correct horse')
            self.assertEqual('{"seed_version": 13}', reopened.read())

            # Re-saving a decrypted wallet must retain the salt needed to
            # derive the same private key.
            reopened.write('{"seed_version": 13, "saved": true}')
            again = WalletStorage(path)
            again.decrypt('correct horse')
            self.assertEqual('{"seed_version": 13, "saved": true}', again.read())
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
