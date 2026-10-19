"""Trendyol / Hepsiburada / N11 siparişleri, sahte telefon engeli ve eski sahte numaralı kayıtların ayrılması."""
import os
import re
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db as dbmod  # noqa: E402


class PazaryeriTesti(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.TemporaryDirectory()
        self.app = create_app({"DATABASE": os.path.join(self.klasor.name, "t.sqlite3"), "SECRET_KEY": "t",
                               "SESSION_COOKIE_SECURE": False, "TESTING": True})
        self.c = self.app.test_client()
        t = self.tok("/kurulum")
        self.c.post("/kurulum", data={"csrf_token": t, "ad_soyad": "Hakan Admin", "kullanici_adi": "hakan",
                                      "sifre": "gizli123", "sifre2": "gizli123"})

    def tearDown(self):
        self.klasor.cleanup()

    def tok(self, yol="/"):
        return re.search(r'name="csrf_token" value="([^"]+)"', self.c.get(yol).get_data(as_text=True)).group(1)

    def q(self, sql, p=()):
        with self.app.app_context():
            from app.db import sorgu
            return sorgu(sql, p)

    def talep(self, **ek):
        veri = {"csrf_token": self.tok("/talepler/yeni"), "kanal": "trendyol", "ad": "Ayşe Yılmaz", "telefon": "",
                "siparis_no": "TY-1001", "fiyat_tipi": "perakende", "durum": "fiyat_verildi", "k_urun_id": [""],
                "k_urun_adi": ["Oturak"], "k_adet": ["1"], "k_fiyat": ["1.500"]}
        veri.update(ek)
        return self.c.post("/talepler/yeni", data=veri)

    def pazaryeri_satis(self, ad="Ayşe Yılmaz", siparis_no="TY-1001"):
        r = self.talep(ad=ad, siparis_no=siparis_no)
        self.assertEqual(r.status_code, 302)
        tid = self.q("SELECT MAX(id) AS i FROM talepler")[0]["i"]
        self.assertIn(f"/talepler/{tid}/satis", r.headers["Location"])
        html = self.c.get(f"/talepler/{tid}/satis").get_data(as_text=True)
        self.assertIn("Trendyol siparişi", html)
        self.assertIn('value="pazaryeri" checked', html)
        r = self.c.post(f"/talepler/{tid}/satis", data={"csrf_token": self.tok(), "ad": ad, "telefon": "",
                        "tip": "bireysel", "adres": "", "odeme": "pazaryeri", "kargo_firma": "Trendyol Express",
                        "siparis_no": siparis_no})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:800])
        return tid, self.q("SELECT MAX(id) AS i FROM satislar")[0]["i"]

    def test_pazaryeri_siparisi_telefonsuz(self):
        tid, sid = self.pazaryeri_satis()
        t = self.q("SELECT * FROM talepler WHERE id = ?", (tid,))[0]
        self.assertEqual((t["durum"], t["hatirlatma"], t["siparis_no"], t["telefon"]), ("satis", None, "TY-1001", None))
        s = self.q("SELECT * FROM satislar WHERE id = ?", (sid,))[0]
        self.assertEqual((s["odeme"], s["kargo_firma"], s["siparis_no"], s["vade_tarihi"]),
                         ("pazaryeri", "Trendyol Express", "TY-1001", None))
        # İkinci sipariş ayrı müşteri olur
        _, sid2 = self.pazaryeri_satis("Ali Kaya", "TY-1002")
        self.assertEqual(self.q("SELECT COUNT(*) AS n FROM musteriler")[0]["n"], 2)
        # Satış sayfası, alacaklar, arama
        html = self.c.get(f"/satislar/{sid}").get_data(as_text=True)
        self.assertIn("Trendyol&#39;dan para geldi", html)
        self.assertIn("TY-1001", html)
        html = self.c.get("/alacaklar/").get_data(as_text=True)
        self.assertIn("Pazaryerinden beklenen", html)
        self.assertIn("Ali Kaya", html)
        self.assertIn("Ali Kaya", self.c.get("/satislar/?q=TY-1002&durum=tumu").get_data(as_text=True))
        self.assertIn("Pazaryerinden beklenen", self.c.get("/").get_data(as_text=True))
        # Beklenen tarih elle girilir, takvimde görünür
        tk = self.tok()
        self.c.post(f"/satislar/{sid}/guncelle", data={"csrf_token": tk, "durum": "kargoda", "odeme": "pazaryeri",
                    "kargo_firma": "Trendyol Express", "takip_no": "7330001", "beklenen_tarih": "2026-11-05"})
        s = self.q("SELECT * FROM satislar WHERE id = ?", (sid,))[0]
        self.assertEqual((s["vade_tarihi"], s["takip_no"]), ("2026-11-05", "7330001"))
        self.assertNotIn("Aras&#39;ta aç", self.c.get(f"/satislar/{sid}").get_data(as_text=True))
        self.assertIn("Ayşe Yılmaz", self.c.get("/alacaklar/takvim?ay=2026-11").get_data(as_text=True))
        # Para geldi
        self.c.post(f"/satislar/{sid}/tahsilat", data={"csrf_token": tk, "yontem": "pazaryeri"})
        r = self.q("SELECT s.toplam_kurus - o.odenen AS k FROM satislar s JOIN satis_odeme o ON o.satis_id = s.id "
                   "WHERE s.id = ?", (sid,))
        self.assertEqual(r[0]["k"], 0)

    def test_sahte_numara_engellenir(self):
        for tel in ("00000000000", "11111111111", "0555 555 55 55"):
            r = self.talep(kanal="telefon", telefon=tel)
            self.assertEqual(r.status_code, 400, tel)
            self.assertIn("gerçek bir numara değil", r.get_data(as_text=True))
        self.assertIsNone(self.c.get("/talepler/api/kisi?tel=00000000000").get_json()["musteri"])

    def test_normal_satista_telefon_hala_zorunlu(self):
        r = self.talep(kanal="telefon", telefon="", siparis_no="")
        self.assertEqual(r.status_code, 302)
        tid = self.q("SELECT MAX(id) AS i FROM talepler")[0]["i"]
        self.assertIsNotNone(self.q("SELECT hatirlatma FROM talepler WHERE id = ?", (tid,))[0]["hatirlatma"])
        r = self.c.post(f"/talepler/{tid}/satis", data={"csrf_token": self.tok(), "ad": "X", "telefon": "",
                        "tip": "bireysel", "adres": "A", "odeme": "kapida"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("Kargo için telefon", r.get_data(as_text=True))


class SahteNumaraAyirmaTesti(unittest.TestCase):
    """3. aşamada 0'larla girilip tek müşteride birleşmiş satışlar yükseltmede ayrılmalı."""

    def test_ayir(self):
        with tempfile.TemporaryDirectory() as k:
            yol = os.path.join(k, "eski.sqlite3")
            eski = dbmod.GOCLER
            try:
                dbmod.GOCLER = eski[:3]
                dbmod.guncelle(yol)
            finally:
                dbmod.GOCLER = eski
            c = sqlite3.connect(yol)
            z = "2026-10-15 12:00:00"
            c.execute("INSERT INTO kullanicilar (kullanici_adi, ad_soyad, sifre_hash, rol, olusturma) VALUES ('a','A','x','admin',?)", (z,))
            c.execute("INSERT INTO musteriler (ad, telefon, tip, olusturma, guncelleme) VALUES ('Son Giren','0000000000','bireysel',?,?)", (z, z))
            c.execute("INSERT INTO musteriler (ad, telefon, tip, olusturma, guncelleme) VALUES ('Gerçek','5321112233','bireysel',?,?)", (z, z))
            for i, (ad, adres, mid) in enumerate([("Ayşe", "Ankara", 1), ("Ali", "İzmir", 1), ("Gerçek", "Bursa", 2)], 1):
                c.execute("""INSERT INTO talepler (kanal, ad, telefon, durum, toplam_kurus, kullanici_id, musteri_id, satis_id,
                             olusturma, guncelleme) VALUES ('diger', ?, ?, 'satis', 10000, 1, ?, ?, ?, ?)""",
                          (ad, "0000000000" if mid == 1 else "5321112233", mid, i, z, z))
                c.execute("""INSERT INTO satislar (talep_id, musteri_id, kullanici_id, odeme, adres, toplam_kurus, olusturma, guncelleme)
                             VALUES (?, ?, 1, 'havale', ?, 10000, ?, ?)""", (i, mid, adres, z, z))
                c.execute("""INSERT INTO tahsilatlar (musteri_id, satis_id, tutar_kurus, yontem, tarih, olusturma)
                             VALUES (?, ?, 10000, 'havale', '2026-10-15', ?)""", (mid, i, z))
            c.execute("""INSERT INTO talepler (kanal, ad, telefon, durum, toplam_kurus, kullanici_id, musteri_id, olusturma, guncelleme)
                         VALUES ('telefon', 'Soran', '11111111111', 'fiyat_verildi', 0, 1, 1, ?, ?)""", (z, z))
            c.commit()
            c.close()

            dbmod.guncelle(yol)
            c = sqlite3.connect(yol)
            c.row_factory = sqlite3.Row
            m = {r["ad"]: r for r in c.execute("SELECT * FROM musteriler")}
            self.assertEqual(sorted(m), ["Ali", "Ayşe", "Gerçek"])          # birleşik kayıt silindi
            self.assertIsNone(m["Ayşe"]["telefon"])
            self.assertEqual(m["Ayşe"]["adres"], "Ankara")
            self.assertEqual(m["Gerçek"]["telefon"], "5321112233")          # gerçek numaraya dokunulmadı
            s = {r["id"]: r for r in c.execute("SELECT * FROM satislar")}
            self.assertEqual(s[1]["musteri_id"], m["Ayşe"]["id"])
            self.assertEqual(s[2]["musteri_id"], m["Ali"]["id"])
            self.assertEqual(s[3]["musteri_id"], m["Gerçek"]["id"])
            t = {r["satis_id"]: r["musteri_id"] for r in c.execute("SELECT * FROM tahsilatlar")}
            self.assertEqual(t[2], m["Ali"]["id"])
            self.assertEqual(c.execute("SELECT SUM(tutar_kurus) FROM tahsilatlar").fetchone()[0], 30000)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM talepler WHERE telefon IN ('0000000000', '11111111111')").fetchone()[0], 0)
            self.assertIsNone(c.execute("SELECT musteri_id FROM talepler WHERE ad = 'Soran'").fetchone()[0])
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
            c.close()


if __name__ == "__main__":
    unittest.main()
