"""Telefona yüklenebilir uygulama (PWA) dosyaları."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402


class PwaTesti(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.TemporaryDirectory()
        self.app = create_app({"DATABASE": os.path.join(self.klasor.name, "t.sqlite3"), "SECRET_KEY": "t",
                               "SESSION_COOKIE_SECURE": False, "TESTING": True})
        self.c = self.app.test_client()

    def tearDown(self):
        self.klasor.cleanup()

    def test_manifest_girissiz_ve_kurulumdan_once(self):
        # Henüz yönetici yokken bile (kurulum yönlendirmesi olmadan) gelmeli
        r = self.c.get("/manifest.webmanifest")
        self.assertEqual(r.status_code, 200)
        self.assertIn("application/manifest+json", r.headers["Content-Type"])
        m = json.loads(r.get_data(as_text=True))
        self.assertEqual(m["name"], "Sünger CRM")
        self.assertEqual(m["display"], "standalone")
        boyutlar = {i["sizes"] for i in m["icons"]}
        self.assertTrue({"192x192", "512x512"} <= boyutlar)
        self.assertTrue(any(i["purpose"] == "maskable" for i in m["icons"]))
        for i in m["icons"]:
            self.assertEqual(self.c.get(i["src"]).status_code, 200, i["src"])

    def test_service_worker_ve_cevrimdisi(self):
        r = self.c.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertIn("javascript", r.headers["Content-Type"])
        self.assertEqual(r.headers["Service-Worker-Allowed"], "/")
        self.assertIn("/cevrimdisi", r.get_data(as_text=True))
        r = self.c.get("/cevrimdisi")
        self.assertEqual(r.status_code, 200)
        self.assertIn("İnternet bağlantısı yok", r.get_data(as_text=True))

    def test_sayfalarda_manifest_baglantisi(self):
        html = self.c.get("/kurulum").get_data(as_text=True)
        self.assertIn('rel="manifest"', html)
        self.assertIn('name="theme-color"', html)


if __name__ == "__main__":
    unittest.main()
