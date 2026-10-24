import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import secret_store


class FakeKeyring:
    def __init__(self):
        self.values = {}

    def set_password(self, service, account, value):
        self.values[(service, account)] = value

    def get_password(self, service, account):
        return self.values.get((service, account))

    def delete_password(self, service, account):
        del self.values[(service, account)]


class SecretStoreTests(unittest.TestCase):
    def test_macos_uses_keychain_without_writing_a_file(self):
        keyring = FakeKeyring()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(secret_store.sys, "platform", "darwin"), patch.object(
                secret_store, "_mac_keyring", return_value=keyring
            ):
                self.assertIsNone(secret_store.load_key(root))
                secret_store.save_key(root, "  test-key  ")
                self.assertEqual(secret_store.load_key(root), "test-key")
                self.assertFalse(secret_store.key_path(root).exists())
                secret_store.delete_key(root)
                secret_store.delete_key(root)
                self.assertIsNone(secret_store.load_key(root))

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is unavailable")
    def test_windows_file_storage_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(secret_store, "_protect", side_effect=lambda data, decrypt=False: data[::-1]):
                secret_store.save_key(root, "test-key")
                self.assertTrue(secret_store.key_path(root).is_file())
                self.assertEqual(secret_store.load_key(root), "test-key")
                secret_store.delete_key(root)
                self.assertIsNone(secret_store.load_key(root))


if __name__ == "__main__":
    unittest.main()
