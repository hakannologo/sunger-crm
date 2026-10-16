"""Unutulan şifreyi sunucudaki bir dosya ile sıfırlama.

Yalnızca cPanel'e (Dosya Yöneticisi) erişebilen biri kullanabilir:
crm-veri/ klasörüne "sifre_sifirla.txt" adında bir dosya oluşturulur.

  Dosyada tek satır varsa:  yeni şifre  -> ilk yönetici hesabının şifresi olur
  "kullanici_adi yenisifre" yazılırsa  -> o kullanıcının şifresi olur

Program bir sonraki açılışta şifreyi değiştirir, dosyayı SİLER ve sonucu
crm-veri/sifre_sifirlama_sonucu.txt dosyasına yazar.
"""
import os
import sqlite3
from datetime import datetime

from werkzeug.security import generate_password_hash

DOSYA_ADI = "sifre_sifirla.txt"
SONUC_DOSYASI = "sifre_sifirlama_sonucu.txt"
EN_AZ_SIFRE = 6


def _sonuc_yaz(klasor, mesaj):
    zaman = datetime.now().strftime("%d.%m.%Y %H:%M")
    with open(os.path.join(klasor, SONUC_DOSYASI), "w", encoding="utf-8") as f:
        f.write(f"{zaman}\n{mesaj}\n")


def calistir(veritabani):
    klasor = os.path.dirname(veritabani)
    yol = os.path.join(klasor, DOSYA_ADI)
    if not os.path.exists(yol):
        return
    try:
        with open(yol, encoding="utf-8-sig", errors="replace") as f:
            satir = next((s.strip() for s in f if s.strip()), "")
    finally:
        os.remove(yol)  # şifre düz yazı olarak sunucuda kalmasın

    parcalar = satir.split()
    if len(parcalar) == 1:
        kullanici_adi, sifre = None, parcalar[0]
    elif len(parcalar) == 2:
        kullanici_adi, sifre = parcalar[0].lower(), parcalar[1]
    else:
        _sonuc_yaz(klasor, "HATA: Dosyaya sadece yeni şifreyi (boşluksuz) ya da 'kullaniciadi yenisifre' yazın.")
        return
    if len(sifre) < EN_AZ_SIFRE:
        _sonuc_yaz(klasor, f"HATA: Şifre en az {EN_AZ_SIFRE} karakter olmalı. Şifre değişmedi.")
        return

    db = sqlite3.connect(veritabani)
    db.row_factory = sqlite3.Row
    try:
        if kullanici_adi:
            k = db.execute("SELECT * FROM kullanicilar WHERE kullanici_adi = ?", (kullanici_adi,)).fetchone()
        else:
            k = db.execute("SELECT * FROM kullanicilar WHERE rol = 'admin' ORDER BY id LIMIT 1").fetchone()
        if k is None:
            _sonuc_yaz(klasor, f"HATA: '{kullanici_adi or 'yönetici'}' adında kullanıcı bulunamadı. Şifre değişmedi.")
            return
        with db:
            db.execute("UPDATE kullanicilar SET sifre_hash = ?, aktif = 1 WHERE id = ?",
                       (generate_password_hash(sifre, method="pbkdf2:sha256:600000"), k["id"]))
            db.execute("DELETE FROM giris_denemeleri WHERE kullanici_adi = ?", (k["kullanici_adi"],))
            db.execute("INSERT INTO islem_kaydi (zaman, kullanici_id, islem, detay) VALUES (?, NULL, ?, ?)",
                       (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Şifre sıfırlandı (sunucu dosyası)",
                        k["kullanici_adi"]))
        _sonuc_yaz(klasor, f"TAMAM: '{k['kullanici_adi']}' kullanıcısının şifresi değiştirildi. "
                           f"Bu kullanıcı adı ve yeni şifrenizle giriş yapabilirsiniz.")
    finally:
        db.close()
