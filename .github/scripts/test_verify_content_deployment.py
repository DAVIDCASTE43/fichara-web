import importlib.util
import unittest
from pathlib import Path

MODULE = Path(__file__).with_name('verify_content_deployment.py')

class VerifyDeploymentTests(unittest.TestCase):
    def load(self):
        self.assertTrue(MODULE.exists(), 'Falta la verificación de publicación pública')
        spec = importlib.util.spec_from_file_location('verify_content_deployment', MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_requires_exact_public_bytes(self):
        verifier = self.load()
        calls = []
        def fetch(url):
            calls.append(url)
            return b'new article'
        self.assertTrue(verifier.verify('https://fichara.com/blog/test/', b'new article', fetch, attempts=1, pause=0))
        self.assertEqual(len(calls), 1)
        with self.assertRaises(RuntimeError):
            verifier.verify('https://fichara.com/blog/test/', b'new article', lambda url: b'old article', attempts=1, pause=0)

    def test_rejects_other_hosts_before_fetch(self):
        verifier = self.load()
        def forbidden(url):
            self.fail('No debe visitar otros destinos')
        with self.assertRaises(ValueError):
            verifier.verify('https://example.org/', b'x', forbidden, attempts=1, pause=0)

if __name__ == '__main__':
    unittest.main()
