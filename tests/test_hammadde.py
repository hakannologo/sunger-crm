"""Hammadde maliyeti: kilolar, kur (TCMB / elle), hesap, yetki, ürün adı düzeltmeleri."""
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, hammadde  # noqa: E402


class HammaddeTesti(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.TemporaryDirectory()
        self.app = create_app({"DATABASE": os.path.join(self.klasor.name, "t.sqlite3"), "SECRET_KEY": "t",
                               "SESSION_COOKIE_SECURE": False, "TESTING": True})
        self.c = self.app.test_client()
        t = self.tok("/kurulum")
        self.c.post("/kurulum", data={"csrf_token": t, "ad_soyad": "Hakan Admin", "kullanici_adi": "hakan",
                                      "sifre": "gizli123", "sifre2": "gizli123"})
        self.tcmb = mock.patch.object(hammadde, "tcmb_euro", return_value=(50.0, "16.11.2026"))
        self.tcmb_mock = self.tcmb.start()

    def tearDown(self):
        self.tcmb.stop()
        self.klasor.cleanup()

    def tok(self, yol="/"):
        return re.search(r'name="csrf_token" value="([^"]+)"', self.c.get(yol).get_data(as_text=True)).group(1)

    def q(self, sql, p=()):
        with self.app.app_context():
            from app.db import sorgu
            return sorgu(sql, p)

    def test_veriler_yuklendi_ve_adlar_duzeldi(self):
        self.assertEqual(self.q("SELECT COUNT(*) AS n FROM urunler WHERE hammadde_kg IS NOT NULL")[0]["n"], 320)
        u = self.q("SELECT * FROM urunler WHERE ad LIKE 'Toyota Corolla (2013%'")[0]
        self.assertEqual(u["hammadde_kg"], 1.25)
        self.assertEqual(self.q("SELECT COUNT(*) AS n FROM urunler WHERE ad LIKE 'WW %' OR ad LIKE '%Kango %' "
                                "OR ad LIKE '%Coralla%' OR ad LIKE '%Sucuto%' OR ad LIKE '%Dally%'")[0]["n"], 0)
        self.assertTrue(self.q("SELECT 1 FROM urunler WHERE ad = 'VW Polo Uyumlu Oturak Süngeri'"))

    def test_varsayilan_sabit_kur_60(self):
        # Corolla oturak 1,25 kg × 2,60 € × 60 ₺ = 195,00 ₺; KDV %20 dahil 234,00 ₺
        html = self.c.get("/hammadde/?q=Corolla+(2013").get_data(as_text=True)
        self.assertIn("1,25 kg", html)
        self.assertIn("195,00", html)
        self.assertIn("234,00", html)
        self.assertIn("60,0000 ₺", html)
        self.assertIn("Sabit kur", html)
        self.assertEqual(self.tcmb_mock.call_count, 0)      # sabit kurda TCMB'ye gidilmez

    def test_tcmb_kuruna_gecis(self):
        tk = self.tok("/hammadde/")
        self.c.post("/hammadde/ayarlar", data={"csrf_token": tk, "tcmb": "1"})
        html = self.c.get("/hammadde/?q=Corolla+(2013").get_data(as_text=True)
        self.assertIn("162,50", html)                       # 1,25 × 2,60 × 50
        self.assertIn("Merkez Bankası döviz satış", html)
        self.c.get("/hammadde/")
        self.assertEqual(self.tcmb_mock.call_count, 1)      # gün içinde bir kez alınır

    def test_marka_model_filtresi(self):
        with self.app.app_context():
            from app.db import sorgu
            m = sorgu("SELECT mo.id AS model, ma.id AS marka FROM modeller mo JOIN markalar ma ON ma.id = mo.marka_id "
                      "WHERE ma.ad = 'Volkswagen' AND mo.ad = 'Polo'", tek=True)
        html = self.c.get(f"/hammadde/?marka={m['marka']}&model={m['model']}&tip=Oturak").get_data(as_text=True)
        self.assertIn("VW Polo Uyumlu Oturak", html)
        self.assertNotIn("VW Polo Uyumlu Sırt", html)
        self.assertNotIn("Corolla", html)

    def test_ayarlar_ve_elle_kur(self):
        tk = self.tok("/hammadde/")
        self.c.post("/hammadde/ayarlar", data={"csrf_token": tk, "eur_kg": "3,00", "kdv": "20", "kur": "40"})
        html = self.c.get("/hammadde/?q=Corolla+(2013").get_data(as_text=True)
        self.assertIn("Sabit kur", html)
        self.assertIn("150,00", html)                       # 1,25 × 3 × 40
        self.assertEqual(self.tcmb_mock.call_count, 0)
        self.c.post("/hammadde/ayarlar", data={"csrf_token": tk, "tcmb": "1"})
        self.assertIn("187,50", self.c.get("/hammadde/?q=Corolla+(2013").get_data(as_text=True))  # 1,25×3×50

    def test_kur_alinamazsa(self):
        self.tcmb_mock.side_effect = OSError("ağ yok")
        self.c.post("/hammadde/ayarlar", data={"csrf_token": self.tok("/hammadde/"), "tcmb": "1"})
        html = self.c.get("/hammadde/").get_data(as_text=True)
        self.assertIn("Merkez Bankası kuru alınamadı", html)
        self.assertIn("60,0000 ₺", html)                    # son bilinen kur kullanılmaya devam eder
        self.c.get("/hammadde/")
        self.assertEqual(self.tcmb_mock.call_count, 1)      # bir saat içinde tekrar denenmez

    def test_urun_formunda_kilo(self):
        u = self.q("SELECT * FROM urunler WHERE hammadde_kg IS NULL LIMIT 1")[0]
        tk = self.tok(f"/urunler/{u['id']}/duzenle")
        r = self.c.post(f"/urunler/{u['id']}/duzenle", data={"csrf_token": tk, "kod": u["kod"], "ad": u["ad"],
                        "kategori": u["kategori"], "parca_tipi": u["parca_tipi"], "perakende": "", "toptan": "",
                        "hammadde_kg": "0,75", "aktif": "1"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.q("SELECT hammadde_kg FROM urunler WHERE id = ?", (u["id"],))[0]["hammadde_kg"], 0.75)
        self.assertIn("0,75 kg", self.c.get(f"/urunler/{u['id']}").get_data(as_text=True))

    def test_sadece_admin(self):
        tk = self.tok("/yonetim/kullanicilar/yeni")
        r = self.c.post("/yonetim/kullanicilar/yeni", data={"csrf_token": tk, "ad_soyad": "Personel", "kullanici_adi": "personel1",
                    "rol": "kullanici", "sifre": "gizli123", "sifre2": "gizli123", "aktif": "1"})
        self.assertEqual(r.status_code, 302, re.findall(r"alan-hata[^<]*<[^>]*>([^<]+)", r.get_data(as_text=True)))
        self.assertTrue(self.q("SELECT 1 FROM kullanicilar WHERE kullanici_adi = 'personel1' AND rol != 'admin'"))
        self.c.post("/cikis", data={"csrf_token": tk})
        tk = self.tok("/giris")
        self.c.post("/giris", data={"csrf_token": tk, "kullanici_adi": "personel1", "sifre": "gizli123"})
        self.assertIn("Personel", self.c.get("/").get_data(as_text=True))   # gerçekten giriş yaptı
        self.assertNotIn("Hammadde maliyeti", self.c.get("/").get_data(as_text=True))
        self.assertIn(self.c.get("/hammadde/").status_code, (302, 403))
        u = self.q("SELECT id FROM urunler WHERE hammadde_kg IS NOT NULL LIMIT 1")[0]
        self.assertNotIn("Hammadde", self.c.get(f"/urunler/{u['id']}").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
