"""Talepler: arayan/yazan kişinin ürün sorusu, verilen fiyat, takip ve hatırlatma."""
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .db import baglanti, sorgu, tr_kucuk
from .yardimci import (KANALLAR, KAYIP_SEBEPLERI, TALEP_DURUMLARI, Sayfa, bugun, giris_gerekli,
                       islem_kaydet, sayfa_no, simdi, tarih_oku, tel_normal, tl_oku, tl_yaz)

bp = Blueprint("talepler", __name__, url_prefix="/talepler")

ACIK_DURUMLAR = ("fiyat_verildi", "dusunuyor")


def admin_mi():
    return g.kullanici["rol"] == "admin"


def talep_getir(talep_id):
    t = sorgu(
        """SELECT t.*, m.ad AS marka, mo.ad AS model, k.ad_soyad AS kullanici
           FROM talepler t
           LEFT JOIN markalar m ON m.id = t.marka_id
           LEFT JOIN modeller mo ON mo.id = t.model_id
           LEFT JOIN kullanicilar k ON k.id = t.kullanici_id
           WHERE t.id = ?""",
        (talep_id,), tek=True,
    )
    if t is None:
        abort(404)
    return t


def kalemler(talep_id):
    return sorgu(
        """SELECT tk.*, u.kod FROM talep_kalemleri tk LEFT JOIN urunler u ON u.id = tk.urun_id
           WHERE tk.talep_id = ? ORDER BY tk.id""",
        (talep_id,),
    )


def gecmis_talepler(telefon, haric_id=None, limit=5):
    if not telefon:
        return []
    return sorgu(
        """SELECT t.id, t.ad, t.olusturma, t.durum, t.toplam_kurus, t.kanal, m.ad AS marka, mo.ad AS model,
                  (SELECT GROUP_CONCAT(urun_adi, ', ') FROM talep_kalemleri WHERE talep_id = t.id) AS urunler
           FROM talepler t
           LEFT JOIN markalar m ON m.id = t.marka_id LEFT JOIN modeller mo ON mo.id = t.model_id
           WHERE t.telefon = ? AND t.id != ? ORDER BY t.id DESC LIMIT ?""",
        (telefon, haric_id or 0, limit),
    )


# --------------------------------------------------------------------------- #
# Liste
# --------------------------------------------------------------------------- #

@bp.route("/")
@giris_gerekli
def liste():
    f = request.args
    kosullar, param = [], []
    kim = f.get("kim", "ben")
    if kim == "ben":
        kosullar.append("t.kullanici_id = ?")
        param.append(g.kullanici["id"])
    elif kim.isdigit():
        kosullar.append("t.kullanici_id = ?")
        param.append(int(kim))
    durum = f.get("durum", "acik")
    if durum == "acik":
        kosullar.append("t.durum IN ('fiyat_verildi', 'dusunuyor')")
    elif durum in TALEP_DURUMLARI:
        kosullar.append("t.durum = ?")
        param.append(durum)
    if f.get("kanal") in KANALLAR:
        kosullar.append("t.kanal = ?")
        param.append(f["kanal"])
    q = f.get("q", "").strip()
    if q:
        tel = tel_normal(q)
        if tel and len(tel) >= 4:
            kosullar.append("(t.telefon LIKE ? OR tr_kucuk(COALESCE(t.ad,'') || ' ' || COALESCE(t.sosyal,'')) LIKE ?)")
            param += [f"%{tel}%", f"%{tr_kucuk(q)}%"]
        else:
            kosullar.append("tr_kucuk(COALESCE(t.ad,'') || ' ' || COALESCE(t.sosyal,'') || ' ' || COALESCE(t.notlar,'')) LIKE ?")
            param.append(f"%{tr_kucuk(q)}%")
    where = ("WHERE " + " AND ".join(kosullar)) if kosullar else ""
    toplam = sorgu(f"SELECT COUNT(*) AS n FROM talepler t {where}", tuple(param), tek=True)["n"]
    sayfa = Sayfa(toplam, sayfa_no(), 50)
    liste_ = sorgu(
        f"""SELECT t.*, m.ad AS marka, mo.ad AS model, k.ad_soyad AS kullanici,
                   (SELECT GROUP_CONCAT(urun_adi, ', ') FROM talep_kalemleri WHERE talep_id = t.id) AS urunler
            FROM talepler t
            LEFT JOIN markalar m ON m.id = t.marka_id LEFT JOIN modeller mo ON mo.id = t.model_id
            LEFT JOIN kullanicilar k ON k.id = t.kullanici_id
            {where} ORDER BY t.id DESC LIMIT ? OFFSET ?""",
        tuple(param) + (sayfa.boyut, sayfa.ofset),
    )
    return render_template(
        "talepler/liste.html", talepler=liste_, sayfa=sayfa, f=f, bugun=bugun(),
        kullanicilar=sorgu("SELECT id, ad_soyad FROM kullanicilar ORDER BY ad_soyad"),
        kanallar=KANALLAR, durumlar=TALEP_DURUMLARI,
    )


# --------------------------------------------------------------------------- #
# Yeni talep / düzenleme
# --------------------------------------------------------------------------- #

def _form_oku():
    """Formu okur, doğrular. (veri, kalem_listesi, hatalar) döner."""
    fm = request.form
    veri = {
        "kanal": fm.get("kanal", ""),
        "ad": fm.get("ad", "").strip(),
        "telefon_ham": fm.get("telefon", "").strip(),
        "sosyal": fm.get("sosyal", "").strip().lstrip("@"),
        "marka_id": fm.get("marka_id", ""),
        "model_id": fm.get("model_id", ""),
        "arac_notu": fm.get("arac_notu", "").strip(),
        "fiyat_tipi": fm.get("fiyat_tipi", "perakende"),
        "durum": fm.get("durum", "fiyat_verildi"),
        "hatirlatma": fm.get("hatirlatma", "").strip(),
        "notlar": fm.get("notlar", "").strip(),
    }
    hatalar = {}
    if veri["kanal"] not in KANALLAR:
        hatalar["kanal"] = "Talebin nereden geldiğini seçin."
    veri["telefon"] = tel_normal(veri["telefon_ham"])
    if veri["telefon"] and len(veri["telefon"]) < 10:
        hatalar["telefon"] = "Telefon numarası eksik görünüyor."
    if not (veri["ad"] or veri["telefon"] or veri["sosyal"]):
        hatalar["ad"] = "Ad, telefon veya kullanıcı adından en az biri gerekli."
    if veri["fiyat_tipi"] not in ("perakende", "toptan"):
        veri["fiyat_tipi"] = "perakende"
    if veri["durum"] not in ("fiyat_verildi", "dusunuyor", "olmadi"):
        veri["durum"] = "fiyat_verildi"
    veri["marka_id"] = int(veri["marka_id"]) if veri["marka_id"].isdigit() else None
    veri["model_id"] = int(veri["model_id"]) if veri["model_id"].isdigit() and veri["marka_id"] else None
    if veri["model_id"] and not sorgu("SELECT 1 FROM modeller WHERE id = ? AND marka_id = ?",
                                      (veri["model_id"], veri["marka_id"]), tek=True):
        veri["model_id"] = None

    if veri["durum"] in ACIK_DURUMLAR:
        hat = tarih_oku(veri["hatirlatma"])
        if veri["hatirlatma"] and not hat:
            hatalar["hatirlatma"] = "Geçerli bir tarih seçin."
        veri["hatirlatma"] = hat or bugun(1)
    else:
        veri["hatirlatma"] = None
    veri["kayip_sebebi"] = fm.get("kayip_sebebi", "").strip() if veri["durum"] == "olmadi" else None

    kalem_listesi = []
    urun_idler = fm.getlist("k_urun_id")
    adlar = fm.getlist("k_urun_adi")
    adetler = fm.getlist("k_adet")
    fiyatlar = fm.getlist("k_fiyat")
    for i, ad in enumerate(adlar):
        ad = ad.strip()
        if not ad:
            continue
        uid = urun_idler[i] if i < len(urun_idler) else ""
        try:
            adet = max(1, int((adetler[i] if i < len(adetler) else "1") or 1))
        except ValueError:
            adet = 1
        try:
            fiyat = tl_oku(fiyatlar[i] if i < len(fiyatlar) else "") or 0
        except ValueError:
            hatalar["kalemler"] = f"“{ad}” için fiyat okunamadı (ör. 1450 veya 1.450,50)."
            fiyat = 0
        kalem_listesi.append({"urun_id": int(uid) if uid.isdigit() else None, "urun_adi": ad,
                              "adet": adet, "birim_kurus": fiyat})
    if not kalem_listesi and veri["durum"] != "olmadi":
        hatalar["kalemler"] = hatalar.get("kalemler") or "En az bir ürün ekleyin."
    veri["toplam_kurus"] = sum(k["adet"] * k["birim_kurus"] for k in kalem_listesi)
    return veri, kalem_listesi, hatalar


def _form_sayfasi(veri, kalem_listesi, hatalar, t=None):
    modeller = []
    if veri.get("marka_id"):
        modeller = sorgu("SELECT id, ad FROM modeller WHERE marka_id = ? ORDER BY ad", (veri["marka_id"],))
    return render_template(
        "talepler/form.html", v=veri, kalemler=kalem_listesi, hatalar=hatalar, t=t,
        markalar=sorgu("SELECT id, ad FROM markalar ORDER BY ad"), modeller=modeller,
        kanallar=KANALLAR, kayip_sebepleri=KAYIP_SEBEPLERI, yarin=bugun(1),
    ), (400 if hatalar else 200)


def _kalemleri_yaz(db, talep_id, kalem_listesi):
    db.execute("DELETE FROM talep_kalemleri WHERE talep_id = ?", (talep_id,))
    for k in kalem_listesi:
        db.execute(
            "INSERT INTO talep_kalemleri (talep_id, urun_id, urun_adi, adet, birim_kurus) VALUES (?, ?, ?, ?, ?)",
            (talep_id, k["urun_id"], k["urun_adi"], k["adet"], k["birim_kurus"]),
        )


@bp.route("/yeni", methods=["GET", "POST"])
@giris_gerekli
def yeni():
    if request.method == "POST":
        veri, kalem_listesi, hatalar = _form_oku()
        if hatalar:
            return _form_sayfasi(veri, kalem_listesi, hatalar)
        db = baglanti()
        musteri = None
        if veri["telefon"]:
            musteri = sorgu("SELECT id FROM musteriler WHERE telefon = ? ORDER BY id LIMIT 1",
                            (veri["telefon"],), tek=True)
        zaman = simdi()
        cur = db.execute(
            """INSERT INTO talepler (kanal, ad, telefon, sosyal, marka_id, model_id, arac_notu, fiyat_tipi, durum,
                   kayip_sebebi, hatirlatma, notlar, toplam_kurus, kullanici_id, musteri_id, olusturma, guncelleme)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (veri["kanal"], veri["ad"] or None, veri["telefon"], veri["sosyal"] or None, veri["marka_id"],
             veri["model_id"], veri["arac_notu"] or None, veri["fiyat_tipi"], veri["durum"], veri["kayip_sebebi"],
             veri["hatirlatma"], veri["notlar"] or None, veri["toplam_kurus"], g.kullanici["id"],
             musteri["id"] if musteri else None, zaman, zaman),
        )
        talep_id = cur.lastrowid
        _kalemleri_yaz(db, talep_id, kalem_listesi)
        islem_kaydet("Talep girildi", f"#{talep_id} — {veri['ad'] or veri['telefon_ham'] or veri['sosyal']} — "
                                      f"{tl_yaz(veri['toplam_kurus'])}")
        db.commit()
        mesaj = "Talep kaydedildi."
        if veri["hatirlatma"]:
            mesaj += f" Hatırlatma: {veri['hatirlatma'][8:10]}.{veri['hatirlatma'][5:7]}.{veri['hatirlatma'][:4]}"
        flash(mesaj, "basari")
        if request.form.get("sonra") == "yeni":
            return redirect(url_for("talepler.yeni"))
        return redirect(url_for("talepler.detay", talep_id=talep_id))

    veri = {"kanal": request.args.get("kanal", ""), "ad": "", "telefon_ham": request.args.get("tel", ""),
            "sosyal": "", "marka_id": None, "model_id": None, "arac_notu": "", "fiyat_tipi": "perakende",
            "durum": "fiyat_verildi", "hatirlatma": bugun(1), "notlar": "", "kayip_sebebi": None}
    return _form_sayfasi(veri, [], {})


@bp.route("/<int:talep_id>/duzenle", methods=["GET", "POST"])
@giris_gerekli
def duzenle(talep_id):
    t = talep_getir(talep_id)
    if t["durum"] == "satis":
        flash("Satışa dönmüş talep düzenlenemez; değişiklikleri satış kaydında yapın.", "bilgi")
        return redirect(url_for("talepler.detay", talep_id=talep_id))
    if request.method == "POST":
        veri, kalem_listesi, hatalar = _form_oku()
        if hatalar:
            return _form_sayfasi(veri, kalem_listesi, hatalar, t)
        db = baglanti()
        db.execute(
            """UPDATE talepler SET kanal = ?, ad = ?, telefon = ?, sosyal = ?, marka_id = ?, model_id = ?,
                   arac_notu = ?, fiyat_tipi = ?, durum = ?, kayip_sebebi = ?, hatirlatma = ?, notlar = ?,
                   toplam_kurus = ?, guncelleme = ? WHERE id = ?""",
            (veri["kanal"], veri["ad"] or None, veri["telefon"], veri["sosyal"] or None, veri["marka_id"],
             veri["model_id"], veri["arac_notu"] or None, veri["fiyat_tipi"], veri["durum"], veri["kayip_sebebi"],
             veri["hatirlatma"], veri["notlar"] or None, veri["toplam_kurus"], simdi(), talep_id),
        )
        _kalemleri_yaz(db, talep_id, kalem_listesi)
        islem_kaydet("Talep düzenlendi", f"#{talep_id} — {tl_yaz(veri['toplam_kurus'])}")
        db.commit()
        flash("Talep güncellendi.", "basari")
        return redirect(url_for("talepler.detay", talep_id=talep_id))

    veri = dict(t)
    veri["telefon_ham"] = t["telefon"] or ""
    kl = [dict(k) for k in kalemler(talep_id)]
    return _form_sayfasi(veri, kl, {}, t)


# --------------------------------------------------------------------------- #
# Detay, not ekleme, durum
# --------------------------------------------------------------------------- #

@bp.route("/<int:talep_id>")
@giris_gerekli
def detay(talep_id):
    t = talep_getir(talep_id)
    notlar = sorgu(
        """SELECT n.*, k.ad_soyad FROM talep_notlari n LEFT JOIN kullanicilar k ON k.id = n.kullanici_id
           WHERE n.talep_id = ? ORDER BY n.id DESC""",
        (talep_id,),
    )
    return render_template(
        "talepler/detay.html", t=t, kalemler=kalemler(talep_id), notlar=notlar,
        gecmis=gecmis_talepler(t["telefon"], talep_id), kanallar=KANALLAR, durumlar=TALEP_DURUMLARI,
        kayip_sebepleri=KAYIP_SEBEPLERI, bugun=bugun(), yarin=bugun(1),
    )


@bp.route("/<int:talep_id>/takip", methods=["POST"])
@giris_gerekli
def takip(talep_id):
    """Görüşme notu + yeni durum + yeni hatırlatma (tek form)."""
    t = talep_getir(talep_id)
    if t["durum"] == "satis":
        abort(400, description="Bu talep zaten satışa döndü.")
    metin = request.form.get("metin", "").strip()
    durum = request.form.get("durum", t["durum"])
    if durum not in ("fiyat_verildi", "dusunuyor", "olmadi"):
        durum = t["durum"]
    hat = None
    kayip = None
    if durum in ACIK_DURUMLAR:
        hat = tarih_oku(request.form.get("hatirlatma")) or bugun(1)
    else:
        kayip = request.form.get("kayip_sebebi", "").strip() or "Diğer"
    db = baglanti()
    zaman = simdi()
    parcalar = []
    if durum != t["durum"]:
        parcalar.append(f"Durum: {TALEP_DURUMLARI[t['durum']]} → {TALEP_DURUMLARI[durum]}")
    if kayip:
        parcalar.append(f"Sebep: {kayip}")
    if hat and hat != t["hatirlatma"]:
        parcalar.append(f"Hatırlatma: {hat[8:10]}.{hat[5:7]}.{hat[:4]}")
    if metin:
        parcalar.insert(0, metin)
    if not parcalar:
        flash("Değişiklik yok.", "bilgi")
        return redirect(url_for("talepler.detay", talep_id=talep_id))
    db.execute("INSERT INTO talep_notlari (talep_id, kullanici_id, zaman, metin) VALUES (?, ?, ?, ?)",
               (talep_id, g.kullanici["id"], zaman, " · ".join(parcalar)))
    db.execute("UPDATE talepler SET durum = ?, hatirlatma = ?, kayip_sebebi = ?, guncelleme = ? WHERE id = ?",
               (durum, hat, kayip, zaman, talep_id))
    if durum != t["durum"]:
        islem_kaydet("Talep durumu", f"#{talep_id} — {TALEP_DURUMLARI[durum]}" + (f" ({kayip})" if kayip else ""))
    db.commit()
    flash("Kaydedildi.", "basari")
    if request.form.get("sonra") == "panel":
        return redirect(url_for("ana.panel"))
    return redirect(url_for("talepler.detay", talep_id=talep_id))


@bp.route("/<int:talep_id>/ertele", methods=["POST"])
@giris_gerekli
def ertele(talep_id):
    """Ana sayfadan hızlı erteleme (+1 gün / +3 gün)."""
    t = talep_getir(talep_id)
    if t["durum"] not in ACIK_DURUMLAR:
        abort(400)
    try:
        gun = max(1, min(30, int(request.form.get("gun", "1"))))
    except ValueError:
        gun = 1
    hat = bugun(gun)
    db = baglanti()
    db.execute("UPDATE talepler SET hatirlatma = ?, guncelleme = ? WHERE id = ?", (hat, simdi(), talep_id))
    db.execute("INSERT INTO talep_notlari (talep_id, kullanici_id, zaman, metin) VALUES (?, ?, ?, ?)",
               (talep_id, g.kullanici["id"], simdi(), f"Ertelendi: {hat[8:10]}.{hat[5:7]}.{hat[:4]}"))
    db.commit()
    flash(f"Hatırlatma {gun} gün ertelendi.", "bilgi")
    return redirect(request.referrer if request.referrer and "/talepler" not in request.referrer
                    else url_for("ana.panel"))


# --------------------------------------------------------------------------- #
# API: kişi geçmişi, araca uygun ürünler
# --------------------------------------------------------------------------- #

@bp.route("/api/kisi")
@giris_gerekli
def api_kisi():
    tel = tel_normal(request.args.get("tel", ""))
    if not tel or len(tel) < 10:
        return jsonify({"musteri": None, "talepler": []})
    m = sorgu("SELECT id, ad, tip, firma_adi FROM musteriler WHERE telefon = ? ORDER BY id LIMIT 1", (tel,), tek=True)
    gecmis = gecmis_talepler(tel, request.args.get("haric", type=int))
    return jsonify({
        "musteri": dict(m) if m else None,
        "talepler": [{"id": r["id"], "ad": r["ad"], "tarih": r["olusturma"][:10], "durum": TALEP_DURUMLARI[r["durum"]],
                      "arac": " ".join(filter(None, [r["marka"], r["model"]])), "urunler": r["urunler"] or "",
                      "toplam": tl_yaz(r["toplam_kurus"]),
                      "url": url_for("talepler.detay", talep_id=r["id"])} for r in gecmis],
    })


@bp.route("/api/urunler")
@giris_gerekli
def api_urunler():
    kosullar, param = ["u.aktif = 1"], []
    marka = request.args.get("marka", "")
    model = request.args.get("model", "")
    q = request.args.get("q", "").strip()
    if marka.isdigit() and not q:
        if model.isdigit():
            kosullar.append("""EXISTS (SELECT 1 FROM urun_uyumluluk x WHERE x.urun_id = u.id AND x.marka_id = ?
                               AND (x.model_id = ? OR x.model_id IS NULL))""")
            param += [int(marka), int(model)]
        else:
            kosullar.append("EXISTS (SELECT 1 FROM urun_uyumluluk x WHERE x.urun_id = u.id AND x.marka_id = ?)")
            param.append(int(marka))
    for kelime in tr_kucuk(q).split():
        kosullar.append("tr_kucuk(u.kod || ' ' || u.ad || ' ' || u.kategori) LIKE ?")
        param.append(f"%{kelime}%")
    satirlar = sorgu(
        f"""SELECT u.id, u.kod, u.ad, u.parca_tipi, u.perakende_kurus, u.toptan_kurus FROM urunler u
            WHERE {' AND '.join(kosullar)} ORDER BY u.parca_tipi, u.ad LIMIT 60""",
        tuple(param),
    )
    return jsonify([{"id": r["id"], "kod": r["kod"], "ad": r["ad"], "tip": r["parca_tipi"],
                     "perakende": r["perakende_kurus"], "toptan": r["toptan_kurus"]} for r in satirlar])
