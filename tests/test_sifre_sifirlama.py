"""Sunucu dosyasıyla şifre sıfırlama testi."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402


class SifreSifirlamaTesti(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.klasor.name, "crm.sqlite3")
        self.ayar = {"DATABASE": self.db, "SECRET_KEY": "t", "SESSION_COOKIE_SECURE": False, "TESTING": True}
        app = create_app(self.ayar)
        c = app.test_client()
        c.get("/kurulum")
        with c.session_transaction() as s:
            token = s["csrf"]
        c.post("/kurulum", data={"csrf_token": token, "ad_soyad": "Hakan Ş", "kullanici_adi": "hakan",
                                 "sifre": "eskisifre1", "sifre2": "eskisifre1"})

    def tearDown(self):
        self.klasor.cleanup()

    def dosya(self, icerik):
        with open(os.path.join(self.klasor.name, "sifre_sifirla.txt"), "w", encoding="utf-8") as f:
            f.write(icerik)

    def sonuc(self):
        with open(os.path.join(self.klasor.name, "sifre_sifirlama_sonucu.txt"), encoding="utf-8") as f:
            return f.read()

    def giris(self, app, kadi, sifre):
        c = app.test_client()
        c.get("/giris")
        with c.session_transaction() as s:
            token = s["csrf"]
        r = c.post("/giris", data={"csrf_token": token, "kullanici_adi": kadi, "sifre": sifre})
        return r.status_code

    def test_yonetici_sifirlama(self):
        self.dosya("﻿yenisifre9\r\n")
        app = create_app(self.ayar)
        self.assertFalse(os.path.exists(os.path.join(self.klasor.name, "sifre_sifirla.txt")))
        self.assertIn("TAMAM", self.sonuc())
        self.assertIn("hakan", self.sonuc())
        self.assertEqual(self.giris(app, "hakan", "yenisifre9"), 302)
        self.assertEqual(self.giris(app, "hakan", "eskisifre1"), 401)

    def test_kisa_sifre_ve_yanlis_kullanici(self):
        self.dosya("123")
        app = create_app(self.ayar)
        self.assertIn("HATA", self.sonuc())
        self.assertEqual(self.giris(app, "hakan", "eskisifre1"), 302)
        self.dosya("yok_boyle biriki345")
        create_app(self.ayar)
        self.assertIn("bulunamadı", self.sonuc())


if __name__ == "__main__":
    unittest.main()
