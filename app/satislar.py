"""Satışlar (talepten çevrilen) ve müşteriler."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .db import baglanti, sorgu, tr_kucuk
from .talepler import kalemler as talep_kalemleri, talep_getir
from .yardimci import (ARAS_TAKIP, KANALLAR, ODEME_SEKILLERI, SATIS_DURUMLARI, TALEP_DURUMLARI, Sayfa,
                       giris_gerekli, islem_kaydet, sayfa_no, simdi, tel_normal, tl_yaz, whatsapp_link)

bp = Blueprint("satislar", __name__)


# --------------------------------------------------------------------------- #
# Talepten satışa
# --------------------------------------------------------------------------- #

@bp.route("/talepler/<int:talep_id>/satis", methods=["GET", "POST"])
@giris_gerekli
def talepten_satis(talep_id):
    t = talep_getir(talep_id)
    if t["durum"] == "satis" and t["satis_id"]:
        return redirect(url_for("satislar.satis_detay", satis_id=t["satis_id"]))
    kl = talep_kalemleri(talep_id)
    if not kl:
        flash("Satışa çevirmek için talepte en az bir ürün olmalı. Önce talebi düzenleyin.", "hata")
        return redirect(url_for("talepler.detay", talep_id=talep_id))

    mevcut = None
    if t["musteri_id"]:
        mevcut = sorgu("SELECT * FROM musteriler WHERE id = ?", (t["musteri_id"],), tek=True)
    elif t["telefon"]:
        mevcut = sorgu("SELECT * FROM musteriler WHERE telefon = ? ORDER BY id LIMIT 1", (t["telefon"],), tek=True)

    v = {
        "ad": (mevcut["ad"] if mevcut else t["ad"]) or "",
        "telefon": (mevcut["telefon"] if mevcut else t["telefon"]) or "",
        "tip": mevcut["tip"] if mevcut else ("toptan" if t["fiyat_tipi"] == "toptan" else "bireysel"),
        "firma_adi": (mevcut["firma_adi"] if mevcut else "") or "",
        "sehir": (mevcut["sehir"] if mevcut else "") or "",
        "adres": (mevcut["adres"] if mevcut else "") or "",
        "odeme": "kapida", "takip_no": "", "notlar": "",
    }
    hatalar = {}
    if request.method == "POST":
        fm = request.form
        v = {k: fm.get(k, "").strip() for k in ("ad", "telefon", "tip", "firma_adi", "sehir", "adres",
                                                 "odeme", "takip_no", "notlar")}
        tel = tel_normal(v["telefon"])
        if not v["ad"]:
            hatalar["ad"] = "Müşterinin adı gerekli."
        if not tel or len(tel) < 10:
            hatalar["telefon"] = "Kargo için telefon numarası gerekli."
        if not v["adres"]:
            hatalar["adres"] = "Teslimat adresi gerekli."
        if v["odeme"] not in ODEME_SEKILLERI:
            hatalar["odeme"] = "Ödeme şeklini seçin."
        if v["tip"] not in ("bireysel", "toptan"):
            v["tip"] = "bireysel"
        if not hatalar:
            db = baglanti()
            zaman = simdi()
            if mevcut:
                musteri_id = mevcut["id"]
                db.execute(
                    """UPDATE musteriler SET ad = ?, telefon = ?, tip = ?, firma_adi = ?, sehir = ?, adres = ?,
                           sosyal = COALESCE(sosyal, ?), guncelleme = ? WHERE id = ?""",
                    (v["ad"], tel, v["tip"], v["firma_adi"] or None, v["sehir"] or None, v["adres"],
                     t["sosyal"], zaman, musteri_id),
                )
            else:
                musteri_id = db.execute(
                    """INSERT INTO musteriler (ad, telefon, sosyal, tip, firma_adi, sehir, adres, olusturan_id,
                           olusturma, guncelleme) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (v["ad"], tel, t["sosyal"], v["tip"], v["firma_adi"] or None, v["sehir"] or None, v["adres"],
                     g.kullanici["id"], zaman, zaman),
                ).lastrowid
            satis_id = db.execute(
                """INSERT INTO satislar (talep_id, musteri_id, kullanici_id, odeme, fiyat_tipi, adres, sehir,
                       takip_no, toplam_kurus, notlar, olusturma, guncelleme)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (talep_id, musteri_id, t["kullanici_id"], v["odeme"], t["fiyat_tipi"], v["adres"],
                 v["sehir"] or None, v["takip_no"] or None, t["toplam_kurus"], v["notlar"] or None, zaman, zaman),
            ).lastrowid
            for k in kl:
                db.execute(
                    "INSERT INTO satis_kalemleri (satis_id, urun_id, urun_adi, adet, birim_kurus) VALUES (?, ?, ?, ?, ?)",
                    (satis_id, k["urun_id"], k["urun_adi"], k["adet"], k["birim_kurus"]),
                )
            db.execute(
                """UPDATE talepler SET durum = 'satis', hatirlatma = NULL, satis_id = ?, musteri_id = ?,
                       ad = COALESCE(ad, ?), telefon = COALESCE(telefon, ?), guncelleme = ? WHERE id = ?""",
                (satis_id, musteri_id, v["ad"], tel, zaman, talep_id),
            )
            db.execute("INSERT INTO talep_notlari (talep_id, kullanici_id, zaman, metin) VALUES (?, ?, ?, ?)",
                       (talep_id, g.kullanici["id"], zaman, f"Satışa döndü (satış #{satis_id})"))
            islem_kaydet("Satış oluşturuldu", f"#{satis_id} — {v['ad']} — {tl_yaz(t['toplam_kurus'])} — "
                                              f"{ODEME_SEKILLERI[v['odeme']]}")
            db.commit()
            flash("Satış oluşturuldu.", "basari")
            return redirect(url_for("satislar.satis_detay", satis_id=satis_id))

    return render_template("satislar/talepten.html", t=t, kalemler=kl, v=v, hatalar=hatalar, mevcut=mevcut,
                           odemeler=ODEME_SEKILLERI), (400 if hatalar else 200)


# --------------------------------------------------------------------------- #
# Satışlar
# --------------------------------------------------------------------------- #

def satis_getir(satis_id):
    s = sorgu(
        """SELECT s.*, m.ad AS musteri, m.telefon, m.tip AS musteri_tip, m.firma_adi, k.ad_soyad AS kullanici
           FROM satislar s JOIN musteriler m ON m.id = s.musteri_id
           LEFT JOIN kullanicilar k ON k.id = s.kullanici_id WHERE s.id = ?""",
        (satis_id,), tek=True,
    )
    if s is None:
        abort(404)
    return s


@bp.route("/satislar/")
@giris_gerekli
def satis_liste():
    f = request.args
    kosullar, param = [], []
    if f.get("durum") in SATIS_DURUMLARI:
        kosullar.append("s.durum = ?")
        param.append(f["durum"])
    elif f.get("durum", "acik") == "acik":
        kosullar.append("s.durum IN ('hazirlaniyor', 'kargoda')")
    if f.get("odeme") in ODEME_SEKILLERI:
        kosullar.append("s.odeme = ?")
        param.append(f["odeme"])
    q = f.get("q", "").strip()
    if q:
        tel = tel_normal(q)
        kosullar.append("(tr_kucuk(m.ad || ' ' || COALESCE(m.firma_adi,'') || ' ' || COALESCE(s.takip_no,'')) LIKE ?"
                        + (" OR m.telefon LIKE ?" if tel and len(tel) >= 4 else "") + ")")
        param.append(f"%{tr_kucuk(q)}%")
        if tel and len(tel) >= 4:
            param.append(f"%{tel}%")
    where = ("WHERE " + " AND ".join(kosullar)) if kosullar else ""
    toplam = sorgu(f"SELECT COUNT(*) AS n FROM satislar s JOIN musteriler m ON m.id = s.musteri_id {where}",
                   tuple(param), tek=True)["n"]
    sayfa = Sayfa(toplam, sayfa_no(), 50)
    satirlar = sorgu(
        f"""SELECT s.*, m.ad AS musteri, m.telefon, k.ad_soyad AS kullanici,
                   (SELECT GROUP_CONCAT(adet || ' × ' || urun_adi, ', ') FROM satis_kalemleri WHERE satis_id = s.id) AS urunler
            FROM satislar s JOIN musteriler m ON m.id = s.musteri_id
            LEFT JOIN kullanicilar k ON k.id = s.kullanici_id
            {where} ORDER BY s.id DESC LIMIT ? OFFSET ?""",
        tuple(param) + (sayfa.boyut, sayfa.ofset),
    )
    return render_template("satislar/liste.html", satislar=satirlar, sayfa=sayfa, f=f,
                           durumlar=SATIS_DURUMLARI, odemeler=ODEME_SEKILLERI)


@bp.route("/satislar/<int:satis_id>")
@giris_gerekli
def satis_detay(satis_id):
    s = satis_getir(satis_id)
    kl = sorgu("""SELECT sk.*, u.kod FROM satis_kalemleri sk LEFT JOIN urunler u ON u.id = sk.urun_id
                  WHERE sk.satis_id = ? ORDER BY sk.id""", (satis_id,))
    mesaj = None
    if s["takip_no"]:
        mesaj = (f"Merhaba {s['musteri']}, siparişiniz Aras Kargo'ya verildi. Takip no: {s['takip_no']} "
                 f"— {ARAS_TAKIP}{s['takip_no']}")
    return render_template(
        "satislar/detay.html", s=s, kalemler=kl, durumlar=SATIS_DURUMLARI, odemeler=ODEME_SEKILLERI,
        aras=ARAS_TAKIP, wa=whatsapp_link(s["telefon"]), wa_kargo=whatsapp_link(s["telefon"], mesaj) if mesaj else None,
    )


@bp.route("/satislar/<int:satis_id>/guncelle", methods=["POST"])
@giris_gerekli
def satis_guncelle(satis_id):
    s = satis_getir(satis_id)
    durum = request.form.get("durum", s["durum"])
    if durum not in SATIS_DURUMLARI:
        durum = s["durum"]
    takip_no = request.form.get("takip_no", "").strip() or None
    odeme = request.form.get("odeme", s["odeme"])
    if odeme not in ODEME_SEKILLERI:
        odeme = s["odeme"]
    if takip_no and durum == "hazirlaniyor" and not s["takip_no"]:
        durum = "kargoda"
    notlar = request.form.get("notlar", "").strip() or None
    db = baglanti()
    db.execute("UPDATE satislar SET durum = ?, takip_no = ?, odeme = ?, notlar = ?, guncelleme = ? WHERE id = ?",
               (durum, takip_no, odeme, notlar, simdi(), satis_id))
    degisen = []
    if durum != s["durum"]:
        degisen.append(f"durum: {SATIS_DURUMLARI[s['durum']]} → {SATIS_DURUMLARI[durum]}")
    if takip_no != s["takip_no"]:
        degisen.append(f"takip no: {takip_no or '—'}")
    if odeme != s["odeme"]:
        degisen.append(f"ödeme: {ODEME_SEKILLERI[odeme]}")
    if degisen:
        islem_kaydet("Satış güncellendi", f"#{satis_id} — " + ", ".join(degisen))
    db.commit()
    flash("Satış güncellendi.", "basari")
    return redirect(url_for("satislar.satis_detay", satis_id=satis_id))


# --------------------------------------------------------------------------- #
# Müşteriler
# --------------------------------------------------------------------------- #

def musteri_getir(musteri_id):
    m = sorgu("SELECT * FROM musteriler WHERE id = ?", (musteri_id,), tek=True)
    if m is None:
        abort(404)
    return m


@bp.route("/musteriler/")
@giris_gerekli
def musteri_liste():
    f = request.args
    kosullar, param = [], []
    if f.get("tip") in ("bireysel", "toptan"):
        kosullar.append("m.tip = ?")
        param.append(f["tip"])
    q = f.get("q", "").strip()
    if q:
        tel = tel_normal(q)
        kosullar.append("(tr_kucuk(m.ad || ' ' || COALESCE(m.firma_adi,'') || ' ' || COALESCE(m.sosyal,'') || ' ' || "
                        "COALESCE(m.sehir,'')) LIKE ?" + (" OR m.telefon LIKE ?" if tel and len(tel) >= 4 else "") + ")")
        param.append(f"%{tr_kucuk(q)}%")
        if tel and len(tel) >= 4:
            param.append(f"%{tel}%")
    where = ("WHERE " + " AND ".join(kosullar)) if kosullar else ""
    toplam = sorgu(f"SELECT COUNT(*) AS n FROM musteriler m {where}", tuple(param), tek=True)["n"]
    sayfa = Sayfa(toplam, sayfa_no(), 50)
    satirlar = sorgu(
        f"""SELECT m.*, (SELECT COUNT(*) FROM satislar s WHERE s.musteri_id = m.id) AS satis_sayisi,
                   (SELECT COALESCE(SUM(toplam_kurus), 0) FROM satislar s WHERE s.musteri_id = m.id AND s.durum != 'iade') AS ciro,
                   (SELECT MAX(olusturma) FROM satislar s WHERE s.musteri_id = m.id) AS son_satis
            FROM musteriler m {where} ORDER BY m.id DESC LIMIT ? OFFSET ?""",
        tuple(param) + (sayfa.boyut, sayfa.ofset),
    )
    return render_template("musteriler/liste.html", musteriler=satirlar, sayfa=sayfa, f=f)


@bp.route("/musteriler/<int:musteri_id>", methods=["GET", "POST"])
@giris_gerekli
def musteri_detay(musteri_id):
    m = musteri_getir(musteri_id)
    hatalar = {}
    if request.method == "POST":
        fm = request.form
        v = {k: fm.get(k, "").strip() for k in ("ad", "telefon", "sosyal", "tip", "firma_adi", "vergi_no",
                                                 "vergi_dairesi", "sehir", "adres", "notlar")}
        tel = tel_normal(v["telefon"])
        if not v["ad"]:
            hatalar["ad"] = "Ad gerekli."
        if v["telefon"] and (not tel or len(tel) < 10):
            hatalar["telefon"] = "Telefon numarası eksik görünüyor."
        if v["tip"] not in ("bireysel", "toptan"):
            v["tip"] = "bireysel"
        if not hatalar:
            db = baglanti()
            db.execute(
                """UPDATE musteriler SET ad = ?, telefon = ?, sosyal = ?, tip = ?, firma_adi = ?, vergi_no = ?,
                       vergi_dairesi = ?, sehir = ?, adres = ?, notlar = ?, guncelleme = ? WHERE id = ?""",
                (v["ad"], tel, v["sosyal"].lstrip("@") or None, v["tip"], v["firma_adi"] or None,
                 v["vergi_no"] or None, v["vergi_dairesi"] or None, v["sehir"] or None, v["adres"] or None,
                 v["notlar"] or None, simdi(), musteri_id),
            )
            islem_kaydet("Müşteri güncellendi", f"#{musteri_id} — {v['ad']}")
            db.commit()
            flash("Müşteri bilgileri kaydedildi.", "basari")
            return redirect(url_for("satislar.musteri_detay", musteri_id=musteri_id))
        m = {**dict(m), **v}

    satislar = sorgu(
        """SELECT s.*, (SELECT GROUP_CONCAT(adet || ' × ' || urun_adi, ', ') FROM satis_kalemleri WHERE satis_id = s.id) AS urunler
           FROM satislar s WHERE s.musteri_id = ? ORDER BY s.id DESC""",
        (musteri_id,),
    )
    talepler = sorgu(
        """SELECT t.*, mk.ad AS marka, mo.ad AS model,
                  (SELECT GROUP_CONCAT(urun_adi, ', ') FROM talep_kalemleri WHERE talep_id = t.id) AS urunler
           FROM talepler t LEFT JOIN markalar mk ON mk.id = t.marka_id LEFT JOIN modeller mo ON mo.id = t.model_id
           WHERE t.musteri_id = ? OR (t.telefon IS NOT NULL AND t.telefon = ?) ORDER BY t.id DESC""",
        (musteri_id, m["telefon"]),
    )
    ciro = sum(s["toplam_kurus"] for s in satislar if s["durum"] != "iade")
    return render_template(
        "musteriler/detay.html", m=m, hatalar=hatalar, satislar=satislar, talepler=talepler, ciro=ciro,
        wa=whatsapp_link(m["telefon"]), durumlar=SATIS_DURUMLARI, talep_durumlari=TALEP_DURUMLARI,
        odemeler=ODEME_SEKILLERI, kanallar=KANALLAR,
    ), (400 if hatalar else 200)
