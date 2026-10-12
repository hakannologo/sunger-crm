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


GOCLER = [
    _goc_1_temel_tablolar,
]


def guncelle(yol):
    """Veritabanını en son sürüme getirir. Her uygulama açılışında çalışır."""
    klasor = os.path.dirname(yol)
    if klasor:
        os.makedirs(klasor, exist_ok=True)
    db = sqlite3.connect(yol, timeout=15)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        surum = db.execute("PRAGMA user_version").fetchone()[0]
        for numara, adim in enumerate(GOCLER[surum:], start=surum + 1):
            with db:
                adim(db)
                db.execute(f"PRAGMA user_version = {numara}")
    finally:
        db.close()
