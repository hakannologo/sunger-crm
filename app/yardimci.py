"""Uygulama genelinde kullanılan küçük yardımcılar."""
import math
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import abort, flash, g, redirect, request, session, url_for

# Türkiye 2016'dan beri yıl boyu UTC+3 kullanıyor.
TR_SAAT = timezone(timedelta(hours=3))

PARCA_TIPLERI = ["Oturak", "Sırt", "Başlık", "Kolçak", "Baldır", "Takım", "Diğer"]


KANALLAR = {"telefon": "Telefon", "whatsapp": "WhatsApp", "instagram": "Instagram",
            "facebook": "Facebook", "diger": "Diğer"}
TALEP_DURUMLARI = {"fiyat_verildi": "Fiyat verildi", "dusunuyor": "Düşünüyor",
                   "satis": "Satışa döndü", "olmadi": "Olmadı"}
KAYIP_SEBEPLERI = ["Pahalı buldu", "Başka yerden aldı", "Cevap vermedi", "Vazgeçti", "Diğer"]
SATIS_DURUMLARI = {"hazirlaniyor": "Hazırlanıyor", "kargoda": "Kargoda",
                   "teslim": "Teslim edildi", "iade": "İade"}
ODEME_SEKILLERI = {"nakit": "Nakit", "kart": "Kredi kartı", "havale": "Havale / EFT",
                   "kapida": "Kapıda ödeme"}
ARAS_TAKIP = "https://kargotakip.araskargo.com.tr/mainpage.aspx?code="


def simdi():
    """Türkiye saatiyle 'YYYY-AA-GG SS:DD:ss' biçiminde zaman."""
    return datetime.now(TR_SAAT).strftime("%Y-%m-%d %H:%M:%S")


def bugun(gun_ekle=0):
    """Türkiye saatiyle 'YYYY-AA-GG' (isteğe bağlı gün eklenmiş)."""
    return (datetime.now(TR_SAAT) + timedelta(days=gun_ekle)).strftime("%Y-%m-%d")


def tarih_oku(metin):
    """'YYYY-AA-GG' doğrular; boş/geçersizse None."""
    metin = (metin or "").strip()
    try:
        return datetime.strptime(metin, "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def tel_normal(metin):
    """'0 (532) 123 45 67', '+90532...' -> '5321234567'. Rakam yoksa None."""
    rakam = re.sub(r"\D", "", metin or "")
    if rakam.startswith("90") and len(rakam) == 12:
        rakam = rakam[2:]
    if rakam.startswith("0") and len(rakam) == 11:
        rakam = rakam[1:]
    return rakam or None


def tel_yaz(tel):
    """'5321234567' -> '0532 123 45 67'."""
    if not tel:
        return ""
    if len(tel) == 10:
        return f"0{tel[:3]} {tel[3:6]} {tel[6:8]} {tel[8:]}"
    return tel


def whatsapp_link(tel, mesaj=None):
    if not tel:
        return None
    hedef = "90" + tel if len(tel) == 10 else tel
    from urllib.parse import quote
    return f"https://wa.me/{hedef}" + (f"?text={quote(mesaj)}" if mesaj else "")


# --------------------------------------------------------------------------- #
# Para: veritabanında kuruş (tam sayı) olarak tutulur, kayan nokta hatası olmaz.
# --------------------------------------------------------------------------- #

def tl_oku(metin):
    """'1.250,50' / '1250,5' / '1250.50' / '1250' -> kuruş (int). Boşsa None.

    Geçersiz girişte ValueError fırlatır.
    """
    if metin is None:
        return None
    s = str(metin).strip().replace("₺", "").replace("TL", "").replace("tl", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", s):
        raise ValueError(f"Geçersiz tutar: {metin}")
    tam, _, kesir = s.partition(".")
    return int(tam) * 100 + int((kesir + "00")[:2])


def tl_yaz(kurus, sembol=True):
    """kuruş -> '1.250,50 ₺'. None ise '—'."""
    if kurus is None:
        return "—"
    negatif = kurus < 0
    kurus = abs(int(kurus))
    tam = f"{kurus // 100:,}".replace(",", ".")
    metin = f"{'-' if negatif else ''}{tam},{kurus % 100:02d}"
    return f"{metin} ₺" if sembol else metin


def tl_girdi(kurus):
    """Form alanına yazılacak hali: 1250,50 (binlik ayırıcı yok). None ise boş."""
    if kurus is None:
        return ""
    return f"{kurus // 100},{kurus % 100:02d}"


def tarih_yaz(metin, saat=True):
    """'2026-10-12 14:05:00' -> '12.10.2026 14:05'."""
    if not metin:
        return "—"
    if len(metin) == 10:
        try:
            return datetime.strptime(metin, "%Y-%m-%d").strftime("%d.%m.%Y")
        except ValueError:
            return metin
    try:
        d = datetime.strptime(metin[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return metin
    return d.strftime("%d.%m.%Y %H:%M" if saat else "%d.%m.%Y")


# --------------------------------------------------------------------------- #
# Oturum, yetki ve form güvenliği
# --------------------------------------------------------------------------- #

def giris_gerekli(f):
    @wraps(f)
    def sar(*args, **kwargs):
        if g.get("kullanici") is None:
            return redirect(url_for("auth.giris", sonra=request.full_path))
        return f(*args, **kwargs)
    return sar


def admin_gerekli(f):
    @wraps(f)
    @giris_gerekli
    def sar(*args, **kwargs):
        if g.kullanici["rol"] != "admin":
            flash("Bu sayfa sadece yöneticiler içindir.", "hata")
            return redirect(url_for("ana.panel"))
        return f(*args, **kwargs)
    return sar


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(32)
    return session["csrf"]


def csrf_kontrol():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        gelen = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        if not gelen or not secrets.compare_digest(gelen, session.get("csrf", "")):
            abort(400, description="Form süresi dolmuş olabilir. Sayfayı yenileyip tekrar deneyin.")


def islem_kaydet(islem, detay=None):
    from .db import baglanti
    kullanici = g.get("kullanici")
    baglanti().execute(
        "INSERT INTO islem_kaydi (zaman, kullanici_id, islem, detay) VALUES (?, ?, ?, ?)",
        (simdi(), kullanici["id"] if kullanici else None, islem, detay),
    )


# --------------------------------------------------------------------------- #
# Sayfalama
# --------------------------------------------------------------------------- #

class Sayfa:
    def __init__(self, toplam, sayfa, boyut):
        self.toplam = toplam
        self.boyut = boyut
        self.sayfa_sayisi = max(1, math.ceil(toplam / boyut))
        self.sayfa = min(max(1, sayfa), self.sayfa_sayisi)
        self.ofset = (self.sayfa - 1) * boyut

    def url(self, numara):
        args = request.args.to_dict()
        args["sayfa"] = numara
        return url_for(request.endpoint, **(request.view_args or {}), **args)


def sayfa_no():
    try:
        return int(request.args.get("sayfa", 1))
    except ValueError:
        return 1
