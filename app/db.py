"""Veritabanı bağlantısı ve sürüm yönetimi (SQLite).

Tablolar sırayla uygulanan "göç" (migration) adımlarıyla oluşturulur. Veritabanının
hangi adımda olduğu PRAGMA user_version içinde tutulur. Yeni bir özellik tablo
değişikliği gerektirdiğinde GOCLER listesinin sonuna yeni bir adım eklenir;
mevcut veriler korunur.
"""
import csv
import os
import sqlite3

from flask import current_app, g

from .yardimci import simdi


def baglanti():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=15)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        # SQLite'ın kendi LIKE'ı Türkçe harflerde büyük/küçük ayrımı yapar; aramada bunu kullanırız.
        g.db.create_function("tr_kucuk", 1, tr_kucuk, deterministic=True)
    return g.db


def tr_kucuk(metin):
    if metin is None:
        return None
    return str(metin).replace("I", "ı").replace("İ", "i").lower()


def kapat(_hata=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def sorgu(sql, parametreler=(), tek=False):
    cur = baglanti().execute(sql, parametreler)
    sonuc = cur.fetchall()
    cur.close()
    return (sonuc[0] if sonuc else None) if tek else sonuc


# --------------------------------------------------------------------------- #
# Göç adımları
# --------------------------------------------------------------------------- #

def _goc_1_temel_tablolar(db):
    # BEGIN ile başlıyoruz ki tablolar ve ilk veriler tek işlemde (ya hep ya hiç) yazılsın.
    db.executescript(
        """
        BEGIN;
        CREATE TABLE kullanicilar (
            id INTEGER PRIMARY KEY,
            kullanici_adi TEXT NOT NULL UNIQUE COLLATE NOCASE,
            ad_soyad TEXT NOT NULL,
            sifre_hash TEXT NOT NULL,
            rol TEXT NOT NULL CHECK (rol IN ('admin', 'kullanici')),
            aktif INTEGER NOT NULL DEFAULT 1,
            olusturma TEXT NOT NULL,
            son_giris TEXT
        );

        CREATE TABLE giris_denemeleri (
            id INTEGER PRIMARY KEY,
            kullanici_adi TEXT NOT NULL COLLATE NOCASE,
            ip TEXT,
            zaman TEXT NOT NULL
        );
        CREATE INDEX ix_giris_denemeleri ON giris_denemeleri (kullanici_adi, zaman);

        CREATE TABLE markalar (
            id INTEGER PRIMARY KEY,
            ad TEXT NOT NULL UNIQUE COLLATE NOCASE
        );

        CREATE TABLE modeller (
            id INTEGER PRIMARY KEY,
            marka_id INTEGER NOT NULL REFERENCES markalar (id) ON DELETE CASCADE,
            ad TEXT NOT NULL COLLATE NOCASE,
            UNIQUE (marka_id, ad)
        );

        CREATE TABLE urunler (
            id INTEGER PRIMARY KEY,
            kod TEXT NOT NULL UNIQUE COLLATE NOCASE,
            orijinal_kod TEXT,
            ad TEXT NOT NULL,
            kategori TEXT NOT NULL,
            parca_tipi TEXT NOT NULL,
            perakende_kurus INTEGER,
            toptan_kurus INTEGER,
            aktif INTEGER NOT NULL DEFAULT 1,
            olusturma TEXT NOT NULL,
            guncelleme TEXT NOT NULL
        );
        CREATE INDEX ix_urunler_kategori ON urunler (kategori);

        CREATE TABLE urun_uyumluluk (
            id INTEGER PRIMARY KEY,
            urun_id INTEGER NOT NULL REFERENCES urunler (id) ON DELETE CASCADE,
            marka_id INTEGER NOT NULL REFERENCES markalar (id),
            model_id INTEGER REFERENCES modeller (id)
        );
        CREATE INDEX ix_uyum_urun ON urun_uyumluluk (urun_id);
        CREATE INDEX ix_uyum_marka_model ON urun_uyumluluk (marka_id, model_id);

        CREATE TABLE islem_kaydi (
            id INTEGER PRIMARY KEY,
            zaman TEXT NOT NULL,
            kullanici_id INTEGER REFERENCES kullanicilar (id),
            islem TEXT NOT NULL,
            detay TEXT
        );
        CREATE INDEX ix_islem_zaman ON islem_kaydi (zaman);
        """
    )
    _urun_listesini_yukle(db)


def _urun_listesini_yukle(db):
    """İlk kurulumda hazır ürün listesini (app/data/urunler.csv) yükler."""
    yol = os.path.join(os.path.dirname(__file__), "data", "urunler.csv")
    if not os.path.exists(yol):
        return
    zaman = simdi()
    marka_idler = {}
    model_idler = {}

    def marka_id(ad):
        if ad not in marka_idler:
            cur = db.execute("INSERT INTO markalar (ad) VALUES (?)", (ad,))
            marka_idler[ad] = cur.lastrowid
        return marka_idler[ad]

    def model_id(marka, ad):
        anahtar = (marka, ad)
        if anahtar not in model_idler:
            cur = db.execute("INSERT INTO modeller (marka_id, ad) VALUES (?, ?)", (marka_id(marka), ad))
            model_idler[anahtar] = cur.lastrowid
        return model_idler[anahtar]

    with open(yol, encoding="utf-8") as f:
        for satir in csv.DictReader(f):
            cur = db.execute(
                """INSERT INTO urunler (kod, orijinal_kod, ad, kategori, parca_tipi, olusturma, guncelleme)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (satir["kod"], satir["orijinal_kod"] or None, satir["ad"], satir["kategori"],
                 satir["parca_tipi"], zaman, zaman),
            )
            urun_id = cur.lastrowid
            for parca in filter(None, satir["uyumluluk"].split(";")):
                marka, model = parca.split("|")
                db.execute(
                    "INSERT INTO urun_uyumluluk (urun_id, marka_id, model_id) VALUES (?, ?, ?)",
                    (urun_id, marka_id(marka), model_id(marka, model) if model else None),
                )


def _goc_2_talep_satis_musteri(db):
    db.executescript(
        """
        BEGIN;
        CREATE TABLE musteriler (
            id INTEGER PRIMARY KEY,
            ad TEXT NOT NULL,
            telefon TEXT,                 -- sadece rakam, 10 hane (5xx...)
            sosyal TEXT,                  -- Instagram/Facebook kullanıcı adı
            tip TEXT NOT NULL DEFAULT 'bireysel' CHECK (tip IN ('bireysel', 'toptan')),
            firma_adi TEXT,
            vergi_no TEXT,
            vergi_dairesi TEXT,
            sehir TEXT,
            adres TEXT,
            notlar TEXT,
            olusturan_id INTEGER REFERENCES kullanicilar (id),
            olusturma TEXT NOT NULL,
            guncelleme TEXT NOT NULL
        );
        CREATE INDEX ix_musteri_telefon ON musteriler (telefon);

        CREATE TABLE talepler (
            id INTEGER PRIMARY KEY,
            kanal TEXT NOT NULL CHECK (kanal IN ('telefon', 'whatsapp', 'instagram', 'facebook', 'diger')),
            ad TEXT,
            telefon TEXT,
            sosyal TEXT,
            marka_id INTEGER REFERENCES markalar (id),
            model_id INTEGER REFERENCES modeller (id),
            arac_notu TEXT,
            fiyat_tipi TEXT NOT NULL DEFAULT 'perakende' CHECK (fiyat_tipi IN ('perakende', 'toptan')),
            durum TEXT NOT NULL DEFAULT 'fiyat_verildi'
                CHECK (durum IN ('fiyat_verildi', 'dusunuyor', 'satis', 'olmadi')),
            kayip_sebebi TEXT,
            hatirlatma TEXT,              -- YYYY-AA-GG, boşsa hatırlatma yok
            notlar TEXT,
            toplam_kurus INTEGER NOT NULL DEFAULT 0,
            kullanici_id INTEGER NOT NULL REFERENCES kullanicilar (id),
            musteri_id INTEGER REFERENCES musteriler (id),
            satis_id INTEGER,
            olusturma TEXT NOT NULL,
            guncelleme TEXT NOT NULL
        );
        CREATE INDEX ix_talep_hatirlatma ON talepler (kullanici_id, hatirlatma);
        CREATE INDEX ix_talep_telefon ON talepler (telefon);
        CREATE INDEX ix_talep_olusturma ON talepler (olusturma);

        CREATE TABLE talep_kalemleri (
            id INTEGER PRIMARY KEY,
            talep_id INTEGER NOT NULL REFERENCES talepler (id) ON DELETE CASCADE,
            urun_id INTEGER REFERENCES urunler (id),
            urun_adi TEXT NOT NULL,
            adet INTEGER NOT NULL DEFAULT 1,
            birim_kurus INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX ix_talep_kalem ON talep_kalemleri (talep_id);

        CREATE TABLE talep_notlari (
            id INTEGER PRIMARY KEY,
            talep_id INTEGER NOT NULL REFERENCES talepler (id) ON DELETE CASCADE,
            kullanici_id INTEGER REFERENCES kullanicilar (id),
            zaman TEXT NOT NULL,
            metin TEXT NOT NULL
        );
        CREATE INDEX ix_talep_not ON talep_notlari (talep_id);

        CREATE TABLE satislar (
            id INTEGER PRIMARY KEY,
            talep_id INTEGER REFERENCES talepler (id),
            musteri_id INTEGER NOT NULL REFERENCES musteriler (id),
            kullanici_id INTEGER NOT NULL REFERENCES kullanicilar (id),
            durum TEXT NOT NULL DEFAULT 'hazirlaniyor'
                CHECK (durum IN ('hazirlaniyor', 'kargoda', 'teslim', 'iade')),
            odeme TEXT NOT NULL CHECK (odeme IN ('nakit', 'kart', 'havale', 'kapida')),
            fiyat_tipi TEXT NOT NULL DEFAULT 'perakende',
            adres TEXT,
            sehir TEXT,
            kargo_firma TEXT NOT NULL DEFAULT 'Aras Kargo',
            takip_no TEXT,
            toplam_kurus INTEGER NOT NULL DEFAULT 0,
            notlar TEXT,
            olusturma TEXT NOT NULL,
            guncelleme TEXT NOT NULL
        );
        CREATE INDEX ix_satis_musteri ON satislar (musteri_id);
        CREATE INDEX ix_satis_olusturma ON satislar (olusturma);

        CREATE TABLE satis_kalemleri (
            id INTEGER PRIMARY KEY,
            satis_id INTEGER NOT NULL REFERENCES satislar (id) ON DELETE CASCADE,
            urun_id INTEGER REFERENCES urunler (id),
            urun_adi TEXT NOT NULL,
            adet INTEGER NOT NULL DEFAULT 1,
            birim_kurus INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX ix_satis_kalem ON satis_kalemleri (satis_id);
        """
    )


def _goc_3_tahsilat(db):
    # satislar.odeme'deki CHECK kısıtına 'vadeli' eklemek için tablo yeniden kurulur
    # (SQLite kısıt değiştirmeye izin vermez). Yabancı anahtar denetimi göç sırasında kapalıdır.
    db.executescript(
        """
        BEGIN;
        ALTER TABLE musteriler ADD COLUMN vade_gun INTEGER;

        CREATE TABLE satislar_yeni (
            id INTEGER PRIMARY KEY,
            talep_id INTEGER REFERENCES talepler (id),
            musteri_id INTEGER NOT NULL REFERENCES musteriler (id),
            kullanici_id INTEGER NOT NULL REFERENCES kullanicilar (id),
            durum TEXT NOT NULL DEFAULT 'hazirlaniyor'
                CHECK (durum IN ('hazirlaniyor', 'kargoda', 'teslim', 'iade')),
            odeme TEXT NOT NULL CHECK (odeme IN ('nakit', 'kart', 'havale', 'kapida', 'vadeli')),
            fiyat_tipi TEXT NOT NULL DEFAULT 'perakende',
            adres TEXT,
            sehir TEXT,
            kargo_firma TEXT NOT NULL DEFAULT 'Aras Kargo',
            takip_no TEXT,
            toplam_kurus INTEGER NOT NULL DEFAULT 0,
            notlar TEXT,
            teslim_tarihi TEXT,
            vade_tarihi TEXT,             -- paranın beklendiği gün (kapıda: teslim+3, vadeli: satış+vade)
            olusturma TEXT NOT NULL,
            guncelleme TEXT NOT NULL
        );
        INSERT INTO satislar_yeni (id, talep_id, musteri_id, kullanici_id, durum, odeme, fiyat_tipi, adres, sehir,
                                   kargo_firma, takip_no, toplam_kurus, notlar, olusturma, guncelleme)
            SELECT id, talep_id, musteri_id, kullanici_id, durum, odeme, fiyat_tipi, adres, sehir,
                   kargo_firma, takip_no, toplam_kurus, notlar, olusturma, guncelleme FROM satislar;
        DROP TABLE satislar;
        ALTER TABLE satislar_yeni RENAME TO satislar;
        CREATE INDEX ix_satis_musteri ON satislar (musteri_id);
        CREATE INDEX ix_satis_olusturma ON satislar (olusturma);
        CREATE INDEX ix_satis_vade ON satislar (vade_tarihi);

        CREATE TABLE tahsilatlar (
            id INTEGER PRIMARY KEY,
            musteri_id INTEGER NOT NULL REFERENCES musteriler (id),
            satis_id INTEGER REFERENCES satislar (id),   -- boşsa avans / hesaba ödeme
            tutar_kurus INTEGER NOT NULL CHECK (tutar_kurus > 0),
            yontem TEXT NOT NULL,
            tarih TEXT NOT NULL,          -- YYYY-AA-GG
            aciklama TEXT,
            kullanici_id INTEGER REFERENCES kullanicilar (id),
            olusturma TEXT NOT NULL
        );
        CREATE INDEX ix_tahsilat_satis ON tahsilatlar (satis_id);
        CREATE INDEX ix_tahsilat_musteri ON tahsilatlar (musteri_id, tarih);

        CREATE VIEW satis_odeme AS
            SELECT s.id AS satis_id,
                   COALESCE((SELECT SUM(t.tutar_kurus) FROM tahsilatlar t WHERE t.satis_id = s.id), 0) AS odenen
            FROM satislar s;

        -- Mevcut satışlar: peşin ödenenler tahsil edilmiş sayılır
        INSERT INTO tahsilatlar (musteri_id, satis_id, tutar_kurus, yontem, tarih, aciklama, kullanici_id, olusturma)
            SELECT musteri_id, id, toplam_kurus, odeme, substr(olusturma, 1, 10), 'Satışta peşin alındı',
                   kullanici_id, olusturma
            FROM satislar WHERE odeme IN ('nakit', 'kart', 'havale') AND toplam_kurus > 0;
        UPDATE satislar SET vade_tarihi = substr(olusturma, 1, 10) WHERE odeme IN ('nakit', 'kart', 'havale');
        -- Teslim edilmiş kapıda ödemeliler: para teslimden 3 gün sonra beklenir
        UPDATE satislar SET teslim_tarihi = substr(guncelleme, 1, 10),
                            vade_tarihi = date(substr(guncelleme, 1, 10), '+3 day')
            WHERE odeme = 'kapida' AND durum = 'teslim';
        """
    )


GOCLER = [
    _goc_1_temel_tablolar,
    _goc_2_talep_satis_musteri,
    _goc_3_tahsilat,
]


def guncelle(yol):
    """Veritabanını en son sürüme getirir. Her uygulama açılışında çalışır."""
    klasor = os.path.dirname(yol)
    if klasor:
        os.makedirs(klasor, exist_ok=True)
    db = sqlite3.connect(yol, timeout=15)
    try:
        # Göçlerde tablo yeniden kurulurken bağlı kayıtlar silinmesin diye kapalı.
        db.execute("PRAGMA foreign_keys = OFF")
        surum = db.execute("PRAGMA user_version").fetchone()[0]
        for numara, adim in enumerate(GOCLER[surum:], start=surum + 1):
            with db:
                adim(db)
                db.execute(f"PRAGMA user_version = {numara}")
    finally:
        db.close()
