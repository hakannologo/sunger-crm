"""Temel akış testleri. Çalıştırmak için: python3 -m unittest discover tests"""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.yardimci import tl_oku, tl_yaz  # noqa: E402


class ParaTesti(unittest.TestCase):
    def test_okuma(self):
        self.assertEqual(tl_oku("1250"), 125000)
        self.assertEqual(tl_oku("1.250"), 125000)
        self.assertEqual(tl_oku("1.250,50"), 125050)
        self.assertEqual(tl_oku("1250,5"), 125050)
        self.assertEqual(tl_oku("1250.50"), 125050)
        self.assertEqual(tl_oku("12,5"), 1250)
        self.assertEqual(tl_oku(" 950 ₺ "), 95000)
        self.assertIsNone(tl_oku(""))
        for bozuk in ("abc", "1,2,3", "-5", "1.2345"):
            with self.assertRaises(ValueError):
                tl_oku(bozuk)

    def test_yazma(self):
        self.assertEqual(tl_yaz(125050), "1.250,50 ₺")
        self.assertEqual(tl_yaz(5), "0,05 ₺")
        self.assertEqual(tl_yaz(None), "—")


class UygulamaTesti(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.TemporaryDirectory()
        self.app = create_app({
            "DATABASE": os.path.join(self.klasor.name, "test.sqlite3"),
            "SECRET_KEY": "test",
            "SESSION_COOKIE_SECURE": False,
            "TESTING": True,
        })
        self.c = self.app.test_client()

    def tearDown(self):
        self.klasor.cleanup()

    def csrf(self, yol):
        html = self.c.get(yol).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def kurulum_yap(self):
        token = self.csrf("/kurulum")
        return self.c.post("/kurulum", data={
            "csrf_token": token, "ad_soyad": "Hakan Şenocak", "kullanici_adi": "hakan",
            "sifre": "gizli123", "sifre2": "gizli123",
        }, follow_redirects=True)

    def test_urun_listesi_yuklendi(self):
        with self.app.app_context():
            from app.db import sorgu
            self.assertEqual(sorgu("SELECT COUNT(*) AS n FROM urunler", tek=True)["n"], 356)
            self.assertGreater(sorgu("SELECT COUNT(*) AS n FROM markalar", tek=True)["n"], 25)

    def test_kurulum_ve_giris(self):
        self.assertIn("/kurulum", self.c.get("/").headers["Location"])
        r = self.kurulum_yap()
        self.assertIn("Merhaba, Hakan", r.get_data(as_text=True))
        # Kurulum bir kere yapılır
        self.assertIn("/giris", self.c.get("/kurulum").headers["Location"])

        token = self.csrf("/")
        self.c.post("/cikis", data={"csrf_token": token})
        self.assertIn("/giris", self.c.get("/").headers["Location"])

        token = self.csrf("/giris")
        r = self.c.post("/giris", data={"csrf_token": token, "kullanici_adi": "hakan", "sifre": "yanlis"})
        self.assertEqual(r.status_code, 401)
        r = self.c.post("/giris", data={"csrf_token": token, "kullanici_adi": "HAKAN", "sifre": "gizli123"},
                        follow_redirects=True)
        self.assertIn("Merhaba", r.get_data(as_text=True))

    def test_csrf_olmadan_post_reddedilir(self):
        self.kurulum_yap()
        r = self.c.post("/yonetim/markalar", data={"ad": "Suzuki"})
        self.assertEqual(r.status_code, 400)

    def test_sayfalar_aciliyor(self):
        self.kurulum_yap()
        for yol in ("/", "/urunler/", "/urunler/?q=doblo+oturak", "/urunler/?marka=genel",
                    "/urunler/toplu-fiyat", "/urunler/toplu-fiyat?fiyat=eksik", "/urunler/yeni",
                    "/yonetim/kullanicilar", "/yonetim/kullanicilar/yeni", "/yonetim/markalar",
                    "/yonetim/islem-kaydi", "/sifre", "/urunler/1", "/urunler/1/duzenle", "/yonetim/markalar/1"):
            r = self.c.get(yol)
            self.assertEqual(r.status_code, 200, yol)

    def test_turkce_arama_ve_arac_filtresi(self):
        self.kurulum_yap()
        html = self.c.get("/urunler/?q=ŞAHİN").get_data(as_text=True)
        self.assertIn("Şahin Uyumlu Oturak Süngeri", html)
        with self.app.app_context():
            from app.db import sorgu
            fiat = sorgu("SELECT id FROM markalar WHERE ad = 'Fiat'", tek=True)["id"]
            doblo = sorgu("SELECT id FROM modeller WHERE ad = 'Doblo'", tek=True)["id"]
        html = self.c.get(f"/urunler/?marka={fiat}&model={doblo}").get_data(as_text=True)
        self.assertIn("Doblo Van Uyumlu Oturak Süngeri", html)
        self.assertNotIn("Fiat Egea", html)
        r = self.c.get(f"/urunler/api/modeller?marka_id={fiat}")
        self.assertIn("Doblo", [m["ad"] for m in r.get_json()])

    def test_toplu_fiyat(self):
        self.kurulum_yap()
        yol = "/urunler/toplu-fiyat?kategori=Fiat+Grubu&tip=Oturak"
        html = self.c.get(yol).get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        idler = re.findall(r'name="id" value="(\d+)"', html)
        veri = {"csrf_token": token, "id": idler}
        for i in idler:
            veri[f"p_{i}"] = "1.250"
            veri[f"t_{i}"] = "1000,50"
        r = self.c.post(yol, data=veri, follow_redirects=True)
        self.assertIn(f"{len(idler)} ürünün fiyatı kaydedildi", r.get_data(as_text=True))
        html = self.c.get(f"/urunler/{idler[0]}").get_data(as_text=True)
        self.assertIn("1.250,00 ₺", html)
        self.assertIn("1.000,50 ₺", html)

        # Hatalı tutar: hiçbir şey kaydedilmez
        veri[f"p_{idler[0]}"] = "abc"
        veri[f"p_{idler[1]}"] = "999"
        r = self.c.post(yol, data=veri)
        self.assertIn("Hiçbir şey kaydedilmedi", r.get_data(as_text=True))
        self.assertIn("1.250,00 ₺", self.c.get(f"/urunler/{idler[1]}").get_data(as_text=True))

    def test_urun_ve_uyumluluk(self):
        self.kurulum_yap()
        token = self.csrf("/urunler/yeni")
        r = self.c.post("/urunler/yeni", data={
            "csrf_token": token, "kod": "sm-test-001", "ad": "Test Oturak", "kategori": "Test Grubu",
            "parca_tipi": "Oturak", "perakende": "500", "toptan": "", "aktif": "1",
        })
        self.assertEqual(r.status_code, 302)
        uid = r.headers["Location"].rstrip("/").split("/")[-1]
        # Aynı kod ikinci kez eklenemez
        r = self.c.post("/urunler/yeni", data={
            "csrf_token": token, "kod": "SM-TEST-001", "ad": "X", "kategori": "Test", "parca_tipi": "Oturak",
        })
        self.assertIn("başka bir üründe", r.get_data(as_text=True))

        with self.app.app_context():
            from app.db import sorgu
            ford = sorgu("SELECT id FROM markalar WHERE ad = 'Ford'", tek=True)["id"]
            connect = sorgu("SELECT id FROM modeller WHERE ad = 'Connect'", tek=True)["id"]
        r = self.c.post(f"/urunler/{uid}/uyumluluk", data={"csrf_token": token, "marka_id": ford, "model_id": connect},
                        follow_redirects=True)
        self.assertIn("Ford Connect eklendi", r.get_data(as_text=True))
        r = self.c.post(f"/urunler/{uid}/uyumluluk", data={"csrf_token": token, "marka_id": ford, "model_id": connect},
                        follow_redirects=True)
        self.assertIn("zaten listede", r.get_data(as_text=True))
        html = self.c.get("/yonetim/islem-kaydi").get_data(as_text=True)
        self.assertIn("SM-TEST-001", html)

    def test_kullanici_yonetimi_ve_yetki(self):
        self.kurulum_yap()
        token = self.csrf("/yonetim/kullanicilar/yeni")
        r = self.c.post("/yonetim/kullanicilar/yeni", data={
            "csrf_token": token, "ad_soyad": "Mehmet Yılmaz", "kullanici_adi": "mehmet", "rol": "kullanici",
            "sifre": "abc123", "sifre2": "abc123",
        }, follow_redirects=True)
        self.assertIn("Mehmet Yılmaz eklendi", r.get_data(as_text=True))

        # Kendi yetkisini kaldıramaz
        r = self.c.post("/yonetim/kullanicilar/1", data={"csrf_token": token, "ad_soyad": "Hakan", "rol": "kullanici",
                                                         "aktif": "1"})
        self.assertIn("Kendi yönetici yetkinizi", r.get_data(as_text=True))

        # Normal kullanıcı yönetim sayfalarına giremez, fiyat düzenleyemez
        self.c.post("/cikis", data={"csrf_token": token})
        token = self.csrf("/giris")
        self.c.post("/giris", data={"csrf_token": token, "kullanici_adi": "mehmet", "sifre": "abc123"})
        self.assertEqual(self.c.get("/urunler/").status_code, 200)
        for yol in ("/yonetim/kullanicilar", "/urunler/toplu-fiyat", "/urunler/1/duzenle", "/yonetim/islem-kaydi"):
            self.assertEqual(self.c.get(yol).status_code, 302, yol)

        # Pasife alınan kullanıcının oturumu kapanır
        with self.app.app_context():
            from app.db import baglanti
            db = baglanti()
            db.execute("UPDATE kullanicilar SET aktif = 0 WHERE kullanici_adi = 'mehmet'")
            db.commit()
        self.assertIn("/giris", self.c.get("/urunler/").headers["Location"])

    def test_giris_kilidi(self):
        self.kurulum_yap()
        token = self.csrf("/")
        self.c.post("/cikis", data={"csrf_token": token})
        token = self.csrf("/giris")
        for _ in range(5):
            self.c.post("/giris", data={"csrf_token": token, "kullanici_adi": "hakan", "sifre": "x"})
        r = self.c.post("/giris", data={"csrf_token": token, "kullanici_adi": "hakan", "sifre": "gizli123"})
        self.assertEqual(r.status_code, 429)


if __name__ == "__main__":
    unittest.main()
