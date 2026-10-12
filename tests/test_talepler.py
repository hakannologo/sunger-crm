"""2. aşama: talep, hatırlatma, satışa çevirme, müşteri, rapor."""
import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.yardimci import bugun, tel_normal  # noqa: E402


class TalepTesti(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.TemporaryDirectory()
        self.app = create_app({"DATABASE": os.path.join(self.klasor.name, "t.sqlite3"), "SECRET_KEY": "t",
                               "SESSION_COOKIE_SECURE": False, "TESTING": True})
        self.c = self.app.test_client()
        tok = self.tok("/kurulum")
        self.c.post("/kurulum", data={"csrf_token": tok, "ad_soyad": "Hakan Admin", "kullanici_adi": "hakan",
                                      "sifre": "gizli123", "sifre2": "gizli123"})
        self.c.post("/yonetim/kullanicilar/yeni", data={"csrf_token": self.tok(), "ad_soyad": "Ali Satış",
                    "kullanici_adi": "ali", "rol": "kullanici", "sifre": "abc123", "sifre2": "abc123"})

    def tearDown(self):
        self.klasor.cleanup()

    def tok(self, yol="/"):
        return re.search(r'name="csrf_token" value="([^"]+)"', self.c.get(yol).get_data(as_text=True)).group(1)

    def giris(self, kadi, sifre):
        t = self.tok("/")
        self.c.post("/cikis", data={"csrf_token": t})
        t = self.tok("/giris")
        self.c.post("/giris", data={"csrf_token": t, "kullanici_adi": kadi, "sifre": sifre})

    def sorgu(self, sql, p=()):
        with self.app.app_context():
            from app.db import sorgu
            return sorgu(sql, p)

    def talep_ac(self, **ek):
        doblo = self.sorgu("SELECT id, marka_id FROM modeller WHERE ad = 'Doblo'")[0]
        urun = self.sorgu("SELECT id, ad FROM urunler WHERE kod = 'SM-FIAT-021'")[0]
        veri = {"csrf_token": self.tok("/talepler/yeni"), "kanal": "whatsapp", "ad": "Mehmet Yılmaz",
                "telefon": "0532 111 22 33", "marka_id": doblo["marka_id"], "model_id": doblo["id"],
                "fiyat_tipi": "perakende", "durum": "fiyat_verildi", "hatirlatma": "",
                "k_urun_id": [urun["id"], ""], "k_urun_adi": [urun["ad"], "Özel kesim minder"],
                "k_adet": ["2", "1"], "k_fiyat": ["1.450", "300,50"]}
        veri.update(ek)
        return self.c.post("/talepler/yeni", data=veri)

    def test_tel_normal(self):
        self.assertEqual(tel_normal("0 (532) 111 22 33"), "5321112233")
        self.assertEqual(tel_normal("+90 532 111 2233"), "5321112233")
        self.assertIsNone(tel_normal("abc"))

    def test_talep_hatirlatma_satis_akisi(self):
        self.giris("ali", "abc123")
        r = self.talep_ac()
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:500])
        t = self.sorgu("SELECT * FROM talepler")[0]
        self.assertEqual(t["telefon"], "5321112233")
        self.assertEqual(t["toplam_kurus"], 2 * 145000 + 30050)
        self.assertEqual(t["hatirlatma"], bugun(1))  # otomatik ertesi gün

        # Bugün listede yok, yarın tarihli; hatırlatmayı bugüne çekince ana sayfada görünür
        self.assertNotIn("Mehmet Yılmaz", self.c.get("/").get_data(as_text=True))
        self.c.post(f"/talepler/{t['id']}/takip", data={"csrf_token": self.tok(), "metin": "aradım",
                                                        "durum": "dusunuyor", "hatirlatma": bugun()})
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn("Mehmet Yılmaz", html)
        self.assertIn("aradım", html)

        # Admin de görür; başka kullanıcının paneline düşmez
        self.giris("hakan", "gizli123")
        self.assertIn("Mehmet Yılmaz", self.c.get("/").get_data(as_text=True))

        # Aynı numara tekrar sorarsa geçmiş gelir
        j = self.c.get("/talepler/api/kisi?tel=05321112233").get_json()
        self.assertEqual(len(j["talepler"]), 1)

        # Satışa çevir
        r = self.c.get(f"/talepler/{t['id']}/satis")
        self.assertEqual(r.status_code, 200)
        r = self.c.post(f"/talepler/{t['id']}/satis", data={"csrf_token": self.tok(), "ad": "Mehmet Yılmaz",
                        "telefon": "05321112233", "tip": "bireysel", "sehir": "Adana", "adres": "Seyhan, X sk. 5",
                        "odeme": "kapida", "takip_no": "", "notlar": ""})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:800])
        s = self.sorgu("SELECT * FROM satislar")[0]
        self.assertEqual(s["toplam_kurus"], t["toplam_kurus"])
        self.assertEqual(len(self.sorgu("SELECT * FROM satis_kalemleri")), 2)
        t2 = self.sorgu("SELECT * FROM talepler")[0]
        self.assertEqual(t2["durum"], "satis")
        self.assertIsNone(t2["hatirlatma"])
        self.assertNotIn("Mehmet Yılmaz", self.c.get("/").get_data(as_text=True))
        m = self.sorgu("SELECT * FROM musteriler")[0]
        self.assertEqual(m["telefon"], "5321112233")

        # Takip no girince kargoda olur
        self.c.post(f"/satislar/{s['id']}/guncelle", data={"csrf_token": self.tok(), "durum": "hazirlaniyor",
                    "takip_no": "1234567890", "odeme": "kapida"})
        self.assertEqual(self.sorgu("SELECT durum FROM satislar")[0]["durum"], "kargoda")
        html = self.c.get(f"/satislar/{s['id']}").get_data(as_text=True)
        self.assertIn("araskargo", html)

        # Aynı müşteri tekrar talep açarsa müşteri kaydına bağlanır, ikinci müşteri oluşmaz
        self.talep_ac()
        self.assertEqual(len(self.sorgu("SELECT * FROM musteriler")), 1)
        self.assertEqual(self.sorgu("SELECT musteri_id FROM talepler ORDER BY id DESC")[0]["musteri_id"], m["id"])

        for yol in ("/talepler/?kim=hepsi&durum=tumu", "/satislar/?durum=tumu", "/musteriler/",
                    f"/musteriler/{m['id']}", "/yonetim/rapor", f"/talepler/{t['id']}"):
            self.assertEqual(self.c.get(yol).status_code, 200, yol)
        rapor = self.c.get("/yonetim/rapor").get_data(as_text=True)
        self.assertIn("WhatsApp", rapor)
        self.assertIn("50%", rapor)

    def test_olmadi_ve_dogrulama(self):
        self.giris("ali", "abc123")
        r = self.talep_ac(kanal="", ad="", telefon="", k_urun_adi=["", ""])
        self.assertEqual(r.status_code, 400)
        html = r.get_data(as_text=True)
        self.assertIn("nereden geldiğini", html)
        self.assertIn("En az bir ürün", html)
        self.talep_ac(durum="olmadi", kayip_sebebi="Pahalı buldu")
        t = self.sorgu("SELECT * FROM talepler")[0]
        self.assertEqual(t["kayip_sebebi"], "Pahalı buldu")
        self.assertIsNone(t["hatirlatma"])
        # Kullanıcı rapora giremez
        self.assertEqual(self.c.get("/yonetim/rapor").status_code, 302)

    def test_urun_api(self):
        self.giris("ali", "abc123")
        doblo = self.sorgu("SELECT id, marka_id FROM modeller WHERE ad = 'Doblo'")[0]
        j = self.c.get(f"/talepler/api/urunler?marka={doblo['marka_id']}&model={doblo['id']}").get_json()
        self.assertTrue(any("Doblo" in u["ad"] for u in j))
        self.assertFalse(any("Egea" in u["ad"] for u in j))
        j = self.c.get("/talepler/api/urunler?q=şahin").get_json()
        self.assertTrue(j)


if __name__ == "__main__":
    unittest.main()
