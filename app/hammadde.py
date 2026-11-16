"""Hammadde maliyeti (yalnızca yönetici): araç + ürün seçilince hammadde kilosu ve TL maliyeti.

Maliyet = hammadde_kg × kilo fiyatı (€) × euro kuru. Kur iki şekilde olur:
  - sabit (elle): yöneticinin yazdığı kur, yine değiştirilene kadar geçerli (varsayılan 60 ₺)
  - TCMB: "Merkez Bankası kurunu al" seçilirse günde bir kez TCMB döviz satış kuru alınır.
"""
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

from .db import baglanti, sorgu
from .urunler import _filtre_sorgusu, kategoriler, uyumluluklar
from .yardimci import PARCA_TIPLERI, Sayfa, admin_gerekli, bugun, islem_kaydet, sayfa_no, simdi

bp = Blueprint("hammadde", __name__, url_prefix="/hammadde")

TCMB_ADRES = "https://www.tcmb.gov.tr/kurlar/today.xml"
SAYFA_BOYUTU = 50


# --- ayarlar ---------------------------------------------------------------

def ayar(anahtar, varsayilan=None):
    r = sorgu("SELECT deger FROM ayarlar WHERE anahtar = ?", (anahtar,), tek=True)
    return r["deger"] if r and r["deger"] not in (None, "") else varsayilan


def ayar_yaz(db, anahtar, deger):
    db.execute("INSERT INTO ayarlar (anahtar, deger) VALUES (?, ?) "
               "ON CONFLICT(anahtar) DO UPDATE SET deger = excluded.deger", (anahtar, deger))


def sayi_oku(metin):
    """'2,60' / '2.60' / '36,4521' -> float; boş veya hatalıysa None."""
    metin = (metin or "").strip().replace(" ", "").replace("€", "").replace("₺", "")
    if not metin:
        return None
    if "," in metin:
        metin = metin.replace(".", "").replace(",", ".")
    try:
        deger = float(metin)
    except ValueError:
        return None
    return deger if deger > 0 else None


# --- euro kuru -------------------------------------------------------------

def tcmb_euro(zaman_asimi=6):
    """(kur, 'GG.AA.YYYY') döndürür; TCMB döviz satış kuru."""
    istek = urllib.request.Request(TCMB_ADRES, headers={"User-Agent": "SungerMerkeziCRM/1.0"})
    with urllib.request.urlopen(istek, timeout=zaman_asimi) as yanit:
        kok = ET.fromstring(yanit.read())
    for doviz in kok.findall("Currency"):
        if doviz.get("Kod") == "EUR":
            return float(doviz.findtext("ForexSelling").replace(",", ".")), kok.get("Tarih", "")
    raise ValueError("TCMB listesinde EUR yok")


def euro_kuru():
    """Güncel kuru verir; gün içinde bir kez TCMB'den yeniler. Hata olursa son kuru ve hata mesajını verir.

    Dönüş: {"kur": float|None, "tarih": str, "kaynak": "tcmb"|"elle", "hata": str|None}
    """
    bilgi = {"kur": None, "tarih": ayar("eur_kur_tarih", ""), "kaynak": ayar("eur_kur_kaynak", "tcmb"), "hata": None}
    kayitli = ayar("eur_kur")
    if kayitli:
        bilgi["kur"] = float(kayitli)
    bugun_ = bugun()
    sabit = bilgi["kaynak"] == "elle" and bilgi["kur"]   # sabit kur: TCMB'ye hiç gidilmez
    guncel = ayar("eur_kur_guncelleme", "")[:10] == bugun_ and bilgi["kaynak"] == "tcmb"
    if sabit or guncel:
        return bilgi
    son_deneme = ayar("eur_kur_son_deneme", "")
    if son_deneme and son_deneme > (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"):
        # Son bir saatte denendi ve alınamadı: sayfayı yavaşlatmamak için tekrar deneme
        bilgi["hata"] = ayar("eur_kur_hata")
        return bilgi
    db = baglanti()
    try:
        kur, tarih = tcmb_euro()
    except Exception as e:  # ağ, zaman aşımı, biçim hatası
        ayar_yaz(db, "eur_kur_son_deneme", simdi())
        ayar_yaz(db, "eur_kur_hata", "Merkez Bankası kuru alınamadı. Kuru aşağıdan sabit olarak girebilirsiniz.")
        db.commit()
        bilgi["hata"] = ayar("eur_kur_hata")
        return bilgi
    for k, v in (("eur_kur", f"{kur:.4f}"), ("eur_kur_tarih", tarih), ("eur_kur_kaynak", "tcmb"),
                 ("eur_kur_guncelleme", simdi()), ("eur_kur_son_deneme", ""), ("eur_kur_hata", "")):
        ayar_yaz(db, k, v)
    db.commit()
    return {"kur": kur, "tarih": tarih, "kaynak": "tcmb", "hata": None}


# --- hesap -----------------------------------------------------------------

def birim_bilgisi():
    eur_kg = float(ayar("hammadde_eur_kg", "2.60"))
    kdv = float(ayar("kdv_orani", "20"))
    kur = euro_kuru()
    kg_tl = eur_kg * kur["kur"] if kur["kur"] else None
    return {"eur_kg": eur_kg, "kdv": kdv, "kur": kur, "kg_kurus": round(kg_tl * 100) if kg_tl else None}


def maliyet(kg, birim):
    """(KDV hariç kuruş, KDV dahil kuruş) ya da (None, None)."""
    if not kg or not birim["kg_kurus"]:
        return None, None
    haric = round(kg * birim["eur_kg"] * birim["kur"]["kur"] * 100)
    return haric, round(haric * (1 + birim["kdv"] / 100))


# --- sayfalar --------------------------------------------------------------

@bp.route("/")
@admin_gerekli
def liste():
    birim = birim_bilgisi()
    where, param = _filtre_sorgusu(request.args, True)
    if request.args.get("kilo") == "eksik":
        where = (where + " AND " if where else "WHERE ") + "u.hammadde_kg IS NULL"
    toplam = sorgu(f"SELECT COUNT(*) AS n FROM urunler u {where}", tuple(param), tek=True)["n"]
    sayfa = Sayfa(toplam, sayfa_no(), SAYFA_BOYUTU)
    urunler = sorgu(f"SELECT u.* FROM urunler u {where} ORDER BY u.kategori, u.kod LIMIT ? OFFSET ?",
                    tuple(param) + (sayfa.boyut, sayfa.ofset))
    satirlar = [{"u": u, "maliyet": maliyet(u["hammadde_kg"], birim)} for u in urunler]
    secili_marka = request.args.get("marka", "")
    modeller = []
    if secili_marka.isdigit():
        modeller = sorgu("SELECT id, ad FROM modeller WHERE marka_id = ? ORDER BY ad", (int(secili_marka),))
    eksik = sorgu("SELECT COUNT(*) AS n FROM urunler WHERE aktif = 1 AND hammadde_kg IS NULL", tek=True)["n"]
    return render_template(
        "hammadde/liste.html", satirlar=satirlar, birim=birim, sayfa=sayfa, eksik=eksik,
        uyum=uyumluluklar([u["id"] for u in urunler]), kategoriler=kategoriler(),
        markalar=sorgu("SELECT id, ad FROM markalar ORDER BY ad"), modeller=modeller, tipler=PARCA_TIPLERI,
        f=request.args,
    )


@bp.route("/ayarlar", methods=["POST"])
@admin_gerekli
def ayarlar():
    db = baglanti()
    degisen = []
    eur_kg = sayi_oku(request.form.get("eur_kg"))
    kdv = sayi_oku(request.form.get("kdv"))
    kur = sayi_oku(request.form.get("kur"))
    if request.form.get("eur_kg", "").strip() and eur_kg is None:
        flash("Kilo fiyatı anlaşılamadı (ör. 2,60).", "hata")
        return redirect(url_for("hammadde.liste"))
    if eur_kg and abs(eur_kg - float(ayar("hammadde_eur_kg", "2.60"))) > 1e-9:
        ayar_yaz(db, "hammadde_eur_kg", f"{eur_kg:.4f}".rstrip("0").rstrip("."))
        degisen.append(f"kilo fiyatı {eur_kg:.2f} €")
    if kdv and abs(kdv - float(ayar("kdv_orani", "20"))) > 1e-9:
        ayar_yaz(db, "kdv_orani", f"{kdv:g}")
        degisen.append(f"KDV %{kdv:g}")
    if kur:
        for k, v in (("eur_kur", f"{kur:.4f}"), ("eur_kur_tarih", datetime.now().strftime("%d.%m.%Y")),
                     ("eur_kur_kaynak", "elle"), ("eur_kur_guncelleme", simdi()), ("eur_kur_hata", "")):
            ayar_yaz(db, k, v)
        degisen.append(f"sabit euro kuru {kur:.4f} ₺")
    if request.form.get("tcmb") == "1":
        # Elle girilen kuru bırakıp Merkez Bankası'ndan yeniden al
        for k in ("eur_kur_guncelleme", "eur_kur_son_deneme"):
            ayar_yaz(db, k, "")
        ayar_yaz(db, "eur_kur_kaynak", "tcmb")
        degisen.append("kur Merkez Bankası'ndan yenilendi")
    if degisen:
        islem_kaydet("Hammadde ayarları", "; ".join(degisen))
        db.commit()
        flash("Kaydedildi: " + "; ".join(degisen) + ".", "basari")
    return redirect(url_for("hammadde.liste", **request.args))
