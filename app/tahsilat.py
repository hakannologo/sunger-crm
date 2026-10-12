"""Tahsilat: peşin/kapıda/vadeli ödemeler, cari hesap, alacak listesi, takvim, dışa aktarma."""
import calendar
import csv
import io
from datetime import date

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from .db import baglanti, sorgu
from .yardimci import (KAPIDA_BEKLEME_GUN, ODEME_SEKILLERI, PESIN_ODEMELER, SATIS_DURUMLARI,
                       TAHSILAT_YONTEMLERI, VARSAYILAN_VADE_GUN, admin_gerekli, bugun, giris_gerekli, gun_ekle,
                       islem_kaydet, simdi, tarih_oku, tel_yaz, tl_oku, tl_yaz)

bp = Blueprint("tahsilat", __name__)


# --------------------------------------------------------------------------- #
# Yardımcılar (satış oluşturma / güncellemede de kullanılır)
# --------------------------------------------------------------------------- #

def kalan(satis_id):
    s = sorgu(
        """SELECT s.toplam_kurus, s.durum, o.odenen FROM satislar s JOIN satis_odeme o ON o.satis_id = s.id
           WHERE s.id = ?""",
        (satis_id,), tek=True,
    )
    if s is None or s["durum"] == "iade":
        return 0
    return max(0, s["toplam_kurus"] - s["odenen"])


def tahsilat_yaz(db, musteri_id, satis_id, tutar, yontem, tarih, aciklama=None):
    db.execute(
        """INSERT INTO tahsilatlar (musteri_id, satis_id, tutar_kurus, yontem, tarih, aciklama, kullanici_id,
               olusturma) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (musteri_id, satis_id, tutar, yontem, tarih, aciklama, g.kullanici["id"], simdi()),
    )


def vade_gun(musteri_id):
    m = sorgu("SELECT vade_gun FROM musteriler WHERE id = ?", (musteri_id,), tek=True)
    return (m["vade_gun"] if m and m["vade_gun"] else VARSAYILAN_VADE_GUN)


def satis_odeme_ayarla(db, satis_id):
    """Satışın ödeme şekline ve durumuna göre vade tarihini ayarlar; peşinse kalanı tahsil eder.

    Satış oluşturulduktan ve her güncellemeden sonra çağrılır.
    """
    s = sorgu("SELECT * FROM satislar WHERE id = ?", (satis_id,), tek=True)
    vade = s["vade_tarihi"]
    if s["odeme"] in PESIN_ODEMELER:
        k = kalan(satis_id)
        if k > 0:
            tahsilat_yaz(db, s["musteri_id"], satis_id, k, s["odeme"], bugun(), "Satışta peşin alındı")
        vade = vade or bugun()
    elif s["odeme"] == "vadeli":
        vade = gun_ekle(s["olusturma"], vade_gun(s["musteri_id"]))
    elif s["odeme"] == "kapida":
        vade = gun_ekle(s["teslim_tarihi"], KAPIDA_BEKLEME_GUN) if s["teslim_tarihi"] else None
    if vade != s["vade_tarihi"]:
        db.execute("UPDATE satislar SET vade_tarihi = ? WHERE id = ?", (vade, satis_id))


def acik_alacaklar(ek_kosul="", param=()):
    """Kalanı olan (iade olmayan) satışlar. Kapıda ödemeliler teslimden sonra alacak sayılır."""
    return sorgu(
        f"""SELECT s.*, m.ad AS musteri, m.telefon, m.tip AS musteri_tip, o.odenen,
                   s.toplam_kurus - o.odenen AS kalan
            FROM satislar s JOIN satis_odeme o ON o.satis_id = s.id JOIN musteriler m ON m.id = s.musteri_id
            WHERE s.durum != 'iade' AND s.toplam_kurus - o.odenen > 0
              AND (s.odeme != 'kapida' OR s.durum = 'teslim') {ek_kosul}
            ORDER BY COALESCE(s.vade_tarihi, '9999'), s.id""",
        param,
    )


def ozet():
    """Ana sayfa ve alacaklar sayfası için toplamlar."""
    b = bugun()
    r = sorgu(
        """SELECT
             COALESCE(SUM(CASE WHEN s.odeme = 'kapida' THEN s.toplam_kurus - o.odenen END), 0) AS aras,
             COALESCE(SUM(CASE WHEN s.odeme = 'kapida' THEN 1 END), 0) AS aras_adet,
             COALESCE(SUM(CASE WHEN s.odeme != 'kapida' THEN s.toplam_kurus - o.odenen END), 0) AS vadeli,
             COALESCE(SUM(CASE WHEN s.vade_tarihi < ? THEN s.toplam_kurus - o.odenen END), 0) AS geciken,
             COALESCE(SUM(CASE WHEN s.vade_tarihi < ? THEN 1 END), 0) AS geciken_adet,
             COALESCE(SUM(CASE WHEN s.vade_tarihi = ? THEN s.toplam_kurus - o.odenen END), 0) AS bugun,
             COALESCE(SUM(CASE WHEN s.vade_tarihi = ? THEN 1 END), 0) AS bugun_adet
           FROM satislar s JOIN satis_odeme o ON o.satis_id = s.id
           WHERE s.durum != 'iade' AND s.toplam_kurus - o.odenen > 0 AND (s.odeme != 'kapida' OR s.durum = 'teslim')""",
        (b, b, b, b), tek=True,
    )
    yolda = sorgu(
        """SELECT COUNT(*) AS n, COALESCE(SUM(s.toplam_kurus - o.odenen), 0) AS tutar
           FROM satislar s JOIN satis_odeme o ON o.satis_id = s.id
           WHERE s.odeme = 'kapida' AND s.durum IN ('hazirlaniyor', 'kargoda') AND s.toplam_kurus - o.odenen > 0""",
        tek=True,
    )
    return dict(r) | {"yolda": yolda["tutar"], "yolda_adet": yolda["n"]}


def musteri_bakiye(musteri_id):
    r = sorgu(
        """SELECT
             COALESCE((SELECT SUM(toplam_kurus) FROM satislar WHERE musteri_id = ? AND durum != 'iade'), 0) AS borc,
             COALESCE((SELECT SUM(tutar_kurus) FROM tahsilatlar WHERE musteri_id = ?), 0) AS odenen""",
        (musteri_id, musteri_id), tek=True,
    )
    return {"borc": r["borc"], "odenen": r["odenen"], "bakiye": r["borc"] - r["odenen"]}


def ekstre(musteri_id):
    """Tarih sırasıyla satış (borç) ve tahsilat (alacak) satırları, yürüyen bakiye ile."""
    satirlar = []
    for s in sorgu("""SELECT id, olusturma, toplam_kurus, odeme, durum,
                             (SELECT GROUP_CONCAT(adet || ' × ' || urun_adi, ', ') FROM satis_kalemleri WHERE satis_id = s.id) AS urunler
                      FROM satislar s WHERE musteri_id = ?""", (musteri_id,)):
        satirlar.append({"tarih": s["olusturma"][:10], "sira": (s["olusturma"], 0, s["id"]), "tur": "satis",
                         "id": s["id"], "aciklama": f"Satış #{s['id']} — {s['urunler'] or ''}",
                         "borc": 0 if s["durum"] == "iade" else s["toplam_kurus"], "alacak": 0,
                         "not": "İade (borca yazılmadı)" if s["durum"] == "iade" else ODEME_SEKILLERI[s["odeme"]]})
    for t in sorgu("""SELECT t.*, k.ad_soyad FROM tahsilatlar t LEFT JOIN kullanicilar k ON k.id = t.kullanici_id
                      WHERE t.musteri_id = ?""", (musteri_id,)):
        satirlar.append({"tarih": t["tarih"], "sira": (t["tarih"] + " 99", 1, t["id"]), "tur": "tahsilat",
                         "id": t["id"], "satis_id": t["satis_id"],
                         "aciklama": "Tahsilat" + (f" (satış #{t['satis_id']})" if t["satis_id"] else " (hesaba)"),
                         "borc": 0, "alacak": t["tutar_kurus"],
                         "not": TAHSILAT_YONTEMLERI.get(t["yontem"], t["yontem"]) + (f" — {t['aciklama']}" if t["aciklama"] else "")
                                + (f" · {t['ad_soyad']}" if t["ad_soyad"] else "")})
    satirlar.sort(key=lambda r: (r["tarih"], r["sira"]))
    bakiye = 0
    for r in satirlar:
        bakiye += r["borc"] - r["alacak"]
        r["bakiye"] = bakiye
    return satirlar


# --------------------------------------------------------------------------- #
# Satış bazında tahsilat
# --------------------------------------------------------------------------- #

def _satis(satis_id):
    s = sorgu("SELECT * FROM satislar WHERE id = ?", (satis_id,), tek=True)
    if s is None:
        abort(404)
    return s


@bp.route("/satislar/<int:satis_id>/tahsilat", methods=["POST"])
@giris_gerekli
def satis_tahsilat(satis_id):
    s = _satis(satis_id)
    k = kalan(satis_id)
    try:
        tutar = tl_oku(request.form.get("tutar")) if request.form.get("tutar") else k
    except ValueError:
        tutar = None
    yontem = request.form.get("yontem", "kapida" if s["odeme"] == "kapida" else "nakit")
    if yontem not in TAHSILAT_YONTEMLERI:
        yontem = "diger"
    tarih = tarih_oku(request.form.get("tarih")) or bugun()
    if not tutar or tutar <= 0:
        flash("Geçerli bir tutar yazın (ör. 1450 veya 1.450,50).", "hata")
        return redirect(url_for("satislar.satis_detay", satis_id=satis_id))
    if tutar > k and k > 0:
        flash(f"Tutar kalan borçtan ({tl_yaz(k)}) fazla. Fazlası için müşteri kartından hesaba tahsilat girin.", "hata")
        return redirect(url_for("satislar.satis_detay", satis_id=satis_id))
    db = baglanti()
    tahsilat_yaz(db, s["musteri_id"], satis_id, tutar, yontem, tarih, request.form.get("aciklama", "").strip() or None)
    islem_kaydet("Tahsilat", f"Satış #{satis_id} — {tl_yaz(tutar)} — {TAHSILAT_YONTEMLERI[yontem]}")
    db.commit()
    flash(f"{tl_yaz(tutar)} tahsil edildi." + ("" if tutar >= k else f" Kalan: {tl_yaz(k - tutar)}"), "basari")
    return redirect(request.form.get("sonra") or url_for("satislar.satis_detay", satis_id=satis_id))


@bp.route("/tahsilatlar/<int:tahsilat_id>/sil", methods=["POST"])
@admin_gerekli
def tahsilat_sil(tahsilat_id):
    t = sorgu("SELECT * FROM tahsilatlar WHERE id = ?", (tahsilat_id,), tek=True)
    if t is None:
        abort(404)
    db = baglanti()
    db.execute("DELETE FROM tahsilatlar WHERE id = ?", (tahsilat_id,))
    islem_kaydet("Tahsilat silindi", f"#{tahsilat_id} — {tl_yaz(t['tutar_kurus'])} — müşteri #{t['musteri_id']}"
                                     + (f", satış #{t['satis_id']}" if t["satis_id"] else ""))
    db.commit()
    flash("Tahsilat silindi.", "bilgi")
    return redirect(request.referrer or url_for("tahsilat.alacaklar"))


# --------------------------------------------------------------------------- #
# Müşteri (cari) tahsilatı: en eski borçtan başlayarak dağıtılır
# --------------------------------------------------------------------------- #

@bp.route("/musteriler/<int:musteri_id>/tahsilat", methods=["POST"])
@giris_gerekli
def musteri_tahsilat(musteri_id):
    m = sorgu("SELECT * FROM musteriler WHERE id = ?", (musteri_id,), tek=True)
    if m is None:
        abort(404)
    try:
        tutar = tl_oku(request.form.get("tutar"))
    except ValueError:
        tutar = None
    if not tutar or tutar <= 0:
        flash("Geçerli bir tutar yazın (ör. 5000 veya 5.000,00).", "hata")
        return redirect(url_for("satislar.musteri_detay", musteri_id=musteri_id) + "#cari")
    yontem = request.form.get("yontem", "nakit")
    if yontem not in TAHSILAT_YONTEMLERI:
        yontem = "diger"
    tarih = tarih_oku(request.form.get("tarih")) or bugun()
    aciklama = request.form.get("aciklama", "").strip() or None
    db = baglanti()
    acik = acik_alacaklar("AND s.musteri_id = ?", (musteri_id,))
    kalan_tutar = tutar
    dagitim = []
    for a in acik:
        if kalan_tutar <= 0:
            break
        pay = min(kalan_tutar, a["kalan"])
        tahsilat_yaz(db, musteri_id, a["id"], pay, yontem, tarih, aciklama)
        dagitim.append(f"#{a['id']}: {tl_yaz(pay)}")
        kalan_tutar -= pay
    if kalan_tutar > 0:
        tahsilat_yaz(db, musteri_id, None, kalan_tutar, yontem, tarih, aciklama or "Hesaba (fazla ödeme)")
        dagitim.append(f"hesaba: {tl_yaz(kalan_tutar)}")
    islem_kaydet("Tahsilat", f"{m['ad']} — {tl_yaz(tutar)} — {TAHSILAT_YONTEMLERI[yontem]} ({', '.join(dagitim)})")
    db.commit()
    flash(f"{tl_yaz(tutar)} tahsil edildi ({', '.join(dagitim)}).", "basari")
    return redirect(url_for("satislar.musteri_detay", musteri_id=musteri_id) + "#cari")


# --------------------------------------------------------------------------- #
# Alacaklar, takvim
# --------------------------------------------------------------------------- #

@bp.route("/alacaklar/")
@giris_gerekli
def alacaklar():
    hepsi = acik_alacaklar()
    aras = [a for a in hepsi if a["odeme"] == "kapida"]
    vadeli = [a for a in hepsi if a["odeme"] != "kapida"]
    yolda = sorgu(
        """SELECT s.*, m.ad AS musteri, s.toplam_kurus - o.odenen AS kalan
           FROM satislar s JOIN satis_odeme o ON o.satis_id = s.id JOIN musteriler m ON m.id = s.musteri_id
           WHERE s.odeme = 'kapida' AND s.durum IN ('hazirlaniyor', 'kargoda') AND s.toplam_kurus - o.odenen > 0
           ORDER BY s.id"""
    )
    return render_template("tahsilat/alacaklar.html", aras=aras, vadeli=vadeli, yolda=yolda, ozet=ozet(),
                           bugun=bugun(), yontemler=TAHSILAT_YONTEMLERI, odemeler=ODEME_SEKILLERI,
                           durumlar=SATIS_DURUMLARI)


@bp.route("/alacaklar/takvim")
@giris_gerekli
def takvim():
    try:
        yil, ay = (int(x) for x in request.args.get("ay", bugun()[:7]).split("-"))
        date(yil, ay, 1)
    except (ValueError, TypeError):
        yil, ay = int(bugun()[:4]), int(bugun()[5:7])
    bas = f"{yil:04d}-{ay:02d}-01"
    son_gun = calendar.monthrange(yil, ay)[1]
    bit = f"{yil:04d}-{ay:02d}-{son_gun:02d}"
    kalemler = acik_alacaklar("AND s.vade_tarihi BETWEEN ? AND ?", (bas, bit))
    gunler = {}
    for k in kalemler:
        gunler.setdefault(k["vade_tarihi"], []).append(k)
    haftalar = calendar.Calendar(firstweekday=0).monthdatescalendar(yil, ay)
    onceki = f"{yil - 1}-12" if ay == 1 else f"{yil}-{ay - 1:02d}"
    sonraki = f"{yil + 1}-01" if ay == 12 else f"{yil}-{ay + 1:02d}"
    geciken = acik_alacaklar("AND s.vade_tarihi < ? AND s.vade_tarihi < ?", (bas, bugun()))
    return render_template(
        "tahsilat/takvim.html", haftalar=haftalar, gunler=gunler, yil=yil, ay=ay, bugun=bugun(),
        onceki=onceki, sonraki=sonraki, ay_toplam=sum(k["kalan"] for k in kalemler), geciken=geciken,
        ay_adi=["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim",
                "Kasım", "Aralık"][ay - 1],
    )


# --------------------------------------------------------------------------- #
# Excel'e aktarma (Excel'in doğrudan açtığı ; ayraçlı, UTF-8 BOM'lu CSV)
# --------------------------------------------------------------------------- #

def _csv(dosya_adi, basliklar, satirlar):
    tampon = io.StringIO()
    tampon.write("﻿")
    w = csv.writer(tampon, delimiter=";")
    w.writerow(basliklar)
    w.writerows(satirlar)
    islem_kaydet("Dışa aktarma", dosya_adi)
    baglanti().commit()
    return Response(tampon.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{dosya_adi}"'})


def _tl(kurus):
    return tl_yaz(kurus, sembol=False)


@bp.route("/disa-aktar/<tur>.csv")
@admin_gerekli
def disa_aktar(tur):
    b = bugun()
    if tur == "satislar":
        satirlar = sorgu(
            """SELECT s.*, m.ad AS musteri, m.telefon, k.ad_soyad AS kullanici, o.odenen,
                      (SELECT GROUP_CONCAT(adet || ' x ' || urun_adi, ', ') FROM satis_kalemleri WHERE satis_id = s.id) AS urunler
               FROM satislar s JOIN musteriler m ON m.id = s.musteri_id JOIN satis_odeme o ON o.satis_id = s.id
               LEFT JOIN kullanicilar k ON k.id = s.kullanici_id ORDER BY s.id"""
        )
        return _csv(f"satislar-{b}.csv",
                    ["No", "Tarih", "Müşteri", "Telefon", "Ürünler", "Tutar", "Ödenen", "Kalan", "Ödeme", "Durum",
                     "Takip no", "Şehir", "Adres", "Kullanıcı"],
                    [[s["id"], s["olusturma"][:10], s["musteri"], tel_yaz(s["telefon"]), s["urunler"] or "",
                      _tl(s["toplam_kurus"]), _tl(s["odenen"]),
                      _tl(0 if s["durum"] == "iade" else max(0, s["toplam_kurus"] - s["odenen"])),
                      ODEME_SEKILLERI[s["odeme"]], SATIS_DURUMLARI[s["durum"]], s["takip_no"] or "",
                      s["sehir"] or "", s["adres"] or "", s["kullanici"] or ""] for s in satirlar])
    if tur == "musteriler":
        satirlar = sorgu("SELECT * FROM musteriler ORDER BY ad")
        return _csv(f"musteriler-{b}.csv",
                    ["No", "Ad", "Telefon", "Tip", "Firma", "Vergi no", "Vergi dairesi", "Şehir", "Adres",
                     "Toplam alış", "Ödenen", "Bakiye"],
                    [[m["id"], m["ad"], tel_yaz(m["telefon"]), "Toptan" if m["tip"] == "toptan" else "Bireysel",
                      m["firma_adi"] or "", m["vergi_no"] or "", m["vergi_dairesi"] or "", m["sehir"] or "",
                      m["adres"] or ""] + [_tl(x) for x in musteri_bakiye(m["id"]).values()] for m in satirlar])
    if tur == "alacaklar":
        satirlar = acik_alacaklar()
        return _csv(f"alacaklar-{b}.csv",
                    ["Satış no", "Müşteri", "Telefon", "Tür", "Satış tarihi", "Beklenen tarih", "Tutar", "Ödenen",
                     "Kalan", "Durum"],
                    [[a["id"], a["musteri"], tel_yaz(a["telefon"]),
                      "Aras (kapıda)" if a["odeme"] == "kapida" else ODEME_SEKILLERI[a["odeme"]],
                      a["olusturma"][:10], a["vade_tarihi"] or "", _tl(a["toplam_kurus"]), _tl(a["odenen"]),
                      _tl(a["kalan"]), "Gecikti" if a["vade_tarihi"] and a["vade_tarihi"] < b else ""]
                     for a in satirlar])
    abort(404)
