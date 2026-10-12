"""3. aşama: tahsilat, kapıda ödeme, vadeli cari, takvim, dışa aktarma, eski veriden yükseltme."""
import os
import re
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db as dbmod  # noqa: E402
from app.yardimci import bugun, gun_ekle  # noqa: E402


class TahsilatTesti(unittest.TestCase):
    def setUp(self):
        self.klasor = tempfile.TemporaryDirectory()
        self.yol = os.path.join(self.klasor.name, "t.sqlite3")
        self.app = create_app({"DATABASE": self.yol, "SECRET_KEY": "t", "SESSION_COOKIE_SECURE": False,
                               "TESTING": True})
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

    def satis(self, odeme, telefon="05321112233", ad="Mehmet", fiyat="1.000", adet="2", tip="bireysel"):
        tk = self.tok("/talepler/yeni")
        self.c.post("/talepler/yeni", data={"csrf_token": tk, "kanal": "telefon", "ad": ad, "telefon": telefon,
                    "fiyat_tipi": "perakende", "durum": "fiyat_verildi", "k_urun_id": [""], "k_urun_adi": ["Oturak"],
                    "k_adet": [adet], "k_fiyat": [fiyat]})
        tid = self.q("SELECT MAX(id) AS i FROM talepler")[0]["i"]
        r = self.c.post(f"/talepler/{tid}/satis", data={"csrf_token": tk, "ad": ad, "telefon": telefon, "tip": tip,
                        "adres": "Adres", "odeme": odeme})
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:600])
        return self.q("SELECT MAX(id) AS i FROM satislar")[0]["i"]

    def kalan(self, sid):
        r = self.q("SELECT s.toplam_kurus - o.odenen AS k FROM satislar s JOIN satis_odeme o ON o.satis_id = s.id WHERE s.id = ?", (sid,))
        return r[0]["k"]

    def test_pesin_otomatik_tahsil(self):
        sid = self.satis("havale")
        self.assertEqual(self.kalan(sid), 0)
        t = self.q("SELECT * FROM tahsilatlar")[0]
        self.assertEqual((t["tutar_kurus"], t["yontem"]), (200000, "havale"))
        self.assertIn("Ödendi", self.c.get(f"/satislar/{sid}").get_data(as_text=True))

    def test_kapida_akisi(self):
        sid = self.satis("kapida")
        self.assertEqual(self.kalan(sid), 200000)
        # Teslimden önce alacak listesinde "yolda"
        html = self.c.get("/alacaklar/").get_data(as_text=True)
        self.assertIn("Yolda", html)
        self.assertIsNone(self.q("SELECT vade_tarihi FROM satislar")[0]["vade_tarihi"])
        # Teslim edildi -> 3 gün sonra beklenir
        tk = self.tok()
        self.c.post(f"/satislar/{sid}/guncelle", data={"csrf_token": tk, "durum": "teslim", "odeme": "kapida"})
        self.assertEqual(self.q("SELECT vade_tarihi FROM satislar")[0]["vade_tarihi"], gun_ekle(bugun(), 3))
        self.assertIn("Para geldi", self.c.get("/alacaklar/").get_data(as_text=True))
        # Para geldi
        self.c.post(f"/satislar/{sid}/tahsilat", data={"csrf_token": tk, "yontem": "kapida"})
        self.assertEqual(self.kalan(sid), 0)
        self.assertEqual(self.q("SELECT yontem FROM tahsilatlar")[0]["yontem"], "kapida")

    def test_kapida_gecikme_ve_iade(self):
        sid = self.satis("kapida")
        with self.app.app_context():
            from app.db import baglanti
            d = baglanti()
            d.execute("UPDATE satislar SET durum='teslim', teslim_tarihi=?, vade_tarihi=? WHERE id=?",
                      (gun_ekle(bugun(), -5), gun_ekle(bugun(), -2), sid))
            d.commit()
        html = self.c.get("/").get_data(as_text=True)
        self.assertIn("Vadesi geçen alacak (1)", html)
        # İade: alacak düşer
        self.c.post(f"/satislar/{sid}/guncelle", data={"csrf_token": self.tok(), "durum": "iade", "odeme": "kapida"})
        self.assertIn("Vadesi geçen alacak (0)", self.c.get("/").get_data(as_text=True))

    def test_vadeli_cari_ve_dagitim(self):
        s1 = self.satis("vadeli", telefon="05001112233", ad="Usta Döşeme", fiyat="1.000", adet="3", tip="toptan")
        mid = self.q("SELECT musteri_id FROM satislar WHERE id = ?", (s1,))[0]["musteri_id"]
        tk = self.tok()
        self.c.post(f"/musteriler/{mid}", data={"csrf_token": tk, "ad": "Usta Döşeme", "telefon": "05001112233",
                    "tip": "toptan", "vade_gun": "45"})
        s2 = self.satis("vadeli", telefon="05001112233", ad="Usta Döşeme", fiyat="500", adet="2", tip="toptan")
        v1, v2 = (self.q("SELECT vade_tarihi FROM satislar WHERE id = ?", (i,))[0]["vade_tarihi"] for i in (s1, s2))
        self.assertEqual(v1, gun_ekle(bugun(), 30))   # ilk satışta varsayılan 30 gün
        self.assertEqual(v2, gun_ekle(bugun(), 45))   # müşteri vadesi 45 gün
        # 3.500 TL ödeme: önce 3.000 (satış 1), sonra 500 (satış 2) — en eski borçtan
        r = self.c.post(f"/musteriler/{mid}/tahsilat", data={"csrf_token": tk, "tutar": "3.500", "yontem": "havale"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.kalan(s1), 0)
        self.assertEqual(self.kalan(s2), 50000)
        html = self.c.get(f"/musteriler/{mid}").get_data(as_text=True)
        self.assertIn("Hesap ekstresi", html)
        self.assertIn("500,00 ₺", html)
        # Fazla ödeme hesaba yazılır
        self.c.post(f"/musteriler/{mid}/tahsilat", data={"csrf_token": tk, "tutar": "800", "yontem": "nakit"})
        self.assertEqual(self.kalan(s2), 0)
        avans = self.q("SELECT * FROM tahsilatlar WHERE satis_id IS NULL")
        self.assertEqual(avans[0]["tutar_kurus"], 30000)
        self.assertIn("Alacaklı", self.c.get(f"/musteriler/{mid}").get_data(as_text=True))
        # Takvim, alacaklar, dışa aktarma
        for yol in ("/alacaklar/", "/alacaklar/takvim", "/alacaklar/takvim?ay=2026-12", "/alacaklar/takvim?ay=xx",
                    "/musteriler/"):
            self.assertEqual(self.c.get(yol).status_code, 200, yol)
        for tur in ("satislar", "musteriler", "alacaklar"):
            r = self.c.get(f"/disa-aktar/{tur}.csv")
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.data.startswith("﻿".encode()))
            if tur != "alacaklar":  # hepsi ödendiği için alacak listesi boş olmalı
                self.assertIn("Usta Döşeme", r.get_data(as_text=True))

    def test_tahsilat_sil_sadece_admin(self):
        sid = self.satis("nakit")
        tid = self.q("SELECT id FROM tahsilatlar")[0]["id"]
        tk = self.tok()
        self.c.post("/yonetim/kullanicilar/yeni", data={"csrf_token": tk, "ad_soyad": "Ali", "kullanici_adi": "ali",
                    "rol": "kullanici", "sifre": "abc123", "sifre2": "abc123"})
        self.c.post("/cikis", data={"csrf_token": tk})
        tk = self.tok("/giris")
        self.c.post("/giris", data={"csrf_token": tk, "kullanici_adi": "ali", "sifre": "abc123"})
        tk = self.tok()
        self.c.post(f"/tahsilatlar/{tid}/sil", data={"csrf_token": tk})
        self.assertEqual(len(self.q("SELECT * FROM tahsilatlar")), 1)
        self.assertEqual(self.c.get("/disa-aktar/satislar.csv").status_code, 302)
        # Kullanıcı tahsilat girebilir
        sid2 = self.satis("kapida", telefon="05551112233")
        self.c.post(f"/satislar/{sid2}/tahsilat", data={"csrf_token": tk, "tutar": "500", "yontem": "nakit"})
        self.assertEqual(self.kalan(sid2), 150000)
        self.assertEqual(self.kalan(sid), 0)


class YukseltmeTesti(unittest.TestCase):
    """2. aşama verisi olan veritabanı 3. aşamaya geçince satışlar ve kalemler korunmalı."""

    def test_eski_veriden_yukselt(self):
        with tempfile.TemporaryDirectory() as k:
            yol = os.path.join(k, "eski.sqlite3")
            eski = dbmod.GOCLER
            try:
                dbmod.GOCLER = eski[:2]
                dbmod.guncelle(yol)
            finally:
                dbmod.GOCLER = eski
            c = sqlite3.connect(yol)
            c.execute("INSERT INTO kullanicilar (kullanici_adi, ad_soyad, sifre_hash, rol, olusturma) VALUES ('a','A','x','admin','2026-10-01 10:00:00')")
            c.execute("INSERT INTO musteriler (ad, telefon, tip, olusturma, guncelleme) VALUES ('M','5320000000','bireysel','2026-10-01','2026-10-01')")
            for i, (odeme, durum) in enumerate([("nakit", "teslim"), ("kapida", "teslim"), ("kapida", "kargoda")], 1):
                c.execute("""INSERT INTO satislar (musteri_id, kullanici_id, durum, odeme, toplam_kurus, olusturma, guncelleme)
                             VALUES (1, 1, ?, ?, 10000, '2026-10-05 12:00:00', '2026-10-07 09:00:00')""", (durum, odeme))
                c.execute("INSERT INTO satis_kalemleri (satis_id, urun_adi, adet, birim_kurus) VALUES (?, 'X', 1, 10000)", (i,))
            c.commit()
            c.close()
            dbmod.guncelle(yol)
            c = sqlite3.connect(yol)
            c.row_factory = sqlite3.Row
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], len(dbmod.GOCLER))
            self.assertEqual(c.execute("SELECT COUNT(*) FROM satis_kalemleri").fetchone()[0], 3)
            s = {r["id"]: r for r in c.execute("SELECT s.*, o.odenen FROM satislar s JOIN satis_odeme o ON o.satis_id = s.id")}
            self.assertEqual(s[1]["odenen"], 10000)          # nakit -> tahsil edildi
            self.assertEqual(s[2]["odenen"], 0)              # kapıda, teslim -> bekliyor
            self.assertEqual(s[2]["vade_tarihi"], "2026-10-10")
            self.assertIsNone(s[3]["vade_tarihi"])           # kapıda, yolda
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
            c.close()


if __name__ == "__main__":
    unittest.main()
