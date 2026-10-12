"""Ürün listesi, ürün kartı, ürün düzenleme ve toplu fiyat girişi."""
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from .db import baglanti, sorgu, tr_kucuk
from .yardimci import (PARCA_TIPLERI, Sayfa, admin_gerekli, giris_gerekli, islem_kaydet,
                       sayfa_no, simdi, tl_girdi, tl_oku, tl_yaz)

bp = Blueprint("urunler", __name__, url_prefix="/urunler")

SAYFA_BOYUTU = 50


def kategoriler():
    return [r["kategori"] for r in sorgu("SELECT DISTINCT kategori FROM urunler ORDER BY kategori")]


def urun_getir(urun_id):
    u = sorgu("SELECT * FROM urunler WHERE id = ?", (urun_id,), tek=True)
    if u is None:
        abort(404)
    return u


def uyumluluklar(urun_idler):
    """{urun_id: [satır, ...]} — her satırda marka, model, id."""
    if not urun_idler:
        return {}
    yer = ",".join("?" * len(urun_idler))
    satirlar = sorgu(
        f"""SELECT u.id, u.urun_id, m.id AS marka_id, m.ad AS marka, mo.id AS model_id, mo.ad AS model
            FROM urun_uyumluluk u
            JOIN markalar m ON m.id = u.marka_id
            LEFT JOIN modeller mo ON mo.id = u.model_id
            WHERE u.urun_id IN ({yer})
            ORDER BY m.ad, mo.ad""",
        tuple(urun_idler),
    )
    sonuc = {}
    for s in satirlar:
        sonuc.setdefault(s["urun_id"], []).append(s)
    return sonuc


def _filtre_sorgusu(args, admin):
    kosullar, param = [], []

    durum = args.get("durum", "aktif") if admin else "aktif"
    if durum == "aktif":
        kosullar.append("u.aktif = 1")
    elif durum == "pasif":
        kosullar.append("u.aktif = 0")

    q = args.get("q", "").strip()
    for kelime in tr_kucuk(q).split():
        kosullar.append(
            """(tr_kucuk(u.kod || ' ' || u.ad || ' ' || u.kategori || ' ' || COALESCE(u.orijinal_kod, '')) LIKE ?
                OR EXISTS (SELECT 1 FROM urun_uyumluluk x JOIN markalar m ON m.id = x.marka_id
                           LEFT JOIN modeller mo ON mo.id = x.model_id
                           WHERE x.urun_id = u.id
                             AND tr_kucuk(m.ad || ' ' || COALESCE(mo.ad, '')) LIKE ?))"""
        )
        param += [f"%{kelime}%", f"%{kelime}%"]

    if args.get("kategori"):
        kosullar.append("u.kategori = ?")
        param.append(args["kategori"])

    if args.get("tip"):
        kosullar.append("u.parca_tipi = ?")
        param.append(args["tip"])

    marka = args.get("marka", "")
    if marka == "genel":
        kosullar.append("NOT EXISTS (SELECT 1 FROM urun_uyumluluk x WHERE x.urun_id = u.id)")
    elif marka.isdigit():
        model = args.get("model", "")
        if model.isdigit():
            # Seçilen modele uyanlar + markanın geneline uyanlar (model belirtilmemiş)
            kosullar.append(
                """EXISTS (SELECT 1 FROM urun_uyumluluk x WHERE x.urun_id = u.id AND x.marka_id = ?
                           AND (x.model_id = ? OR x.model_id IS NULL))"""
            )
            param += [int(marka), int(model)]
        else:
            kosullar.append("EXISTS (SELECT 1 FROM urun_uyumluluk x WHERE x.urun_id = u.id AND x.marka_id = ?)")
            param.append(int(marka))

    if args.get("fiyat") == "eksik":
        kosullar.append("(u.perakende_kurus IS NULL OR u.toptan_kurus IS NULL)")

    where = ("WHERE " + " AND ".join(kosullar)) if kosullar else ""
    return where, param


@bp.route("/")
@giris_gerekli
def liste():
    admin = g.kullanici["rol"] == "admin"
    where, param = _filtre_sorgusu(request.args, admin)
    toplam = sorgu(f"SELECT COUNT(*) AS n FROM urunler u {where}", tuple(param), tek=True)["n"]
    sayfa = Sayfa(toplam, sayfa_no(), SAYFA_BOYUTU)
    urunler = sorgu(
        f"SELECT u.* FROM urunler u {where} ORDER BY u.kategori, u.kod LIMIT ? OFFSET ?",
        tuple(param) + (sayfa.boyut, sayfa.ofset),
    )
    secili_marka = request.args.get("marka", "")
    modeller = []
    if secili_marka.isdigit():
        modeller = sorgu("SELECT id, ad FROM modeller WHERE marka_id = ? ORDER BY ad", (int(secili_marka),))
    return render_template(
        "urunler/liste.html",
        urunler=urunler,
        uyum=uyumluluklar([u["id"] for u in urunler]),
        sayfa=sayfa,
        kategoriler=kategoriler(),
        markalar=sorgu("SELECT id, ad FROM markalar ORDER BY ad"),
        modeller=modeller,
        tipler=PARCA_TIPLERI,
        f=request.args,
    )


@bp.route("/<int:urun_id>")
@giris_gerekli
def detay(urun_id):
    u = urun_getir(urun_id)
    return render_template(
        "urunler/detay.html",
        u=u,
        uyum=uyumluluklar([u["id"]]).get(u["id"], []),
        markalar=sorgu("SELECT id, ad FROM markalar ORDER BY ad"),
    )


def _form_oku(mevcut_id=None):
    form = {k: request.form.get(k, "").strip() for k in
            ("kod", "ad", "kategori", "parca_tipi", "perakende", "toptan")}
    form["kod"] = form["kod"].upper()
    form["aktif"] = request.form.get("aktif") == "1"
    hatalar = {}
    if not form["kod"]:
        hatalar["kod"] = "Ürün kodu gerekli."
    else:
        cakisan = sorgu("SELECT id FROM urunler WHERE kod = ? AND id != ?", (form["kod"], mevcut_id or 0), tek=True)
        if cakisan:
            hatalar["kod"] = "Bu kod başka bir üründe kullanılıyor."
    if not form["ad"]:
        hatalar["ad"] = "Ürün adı gerekli."
    if not form["kategori"]:
        hatalar["kategori"] = "Kategori gerekli."
    if form["parca_tipi"] not in PARCA_TIPLERI:
        hatalar["parca_tipi"] = "Parça tipini seçin."
    fiyatlar = {}
    for alan in ("perakende", "toptan"):
        try:
            fiyatlar[alan] = tl_oku(form[alan])
        except ValueError:
            hatalar[alan] = "Geçerli bir tutar yazın (ör. 1250 veya 1.250,50)."
    return form, fiyatlar, hatalar


@bp.route("/yeni", methods=["GET", "POST"])
@admin_gerekli
def yeni():
    form = {"kod": "", "ad": "", "kategori": request.args.get("kategori", ""), "parca_tipi": "Oturak",
            "perakende": "", "toptan": "", "aktif": True}
    hatalar = {}
    if request.method == "POST":
        form, fiyatlar, hatalar = _form_oku()
        if not hatalar:
            db = baglanti()
            cur = db.execute(
                """INSERT INTO urunler (kod, ad, kategori, parca_tipi, perakende_kurus, toptan_kurus, aktif,
                                        olusturma, guncelleme)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (form["kod"], form["ad"], form["kategori"], form["parca_tipi"], fiyatlar["perakende"],
                 fiyatlar["toptan"], int(form["aktif"]), simdi(), simdi()),
            )
            islem_kaydet("Ürün eklendi", f"{form['kod']} — {form['ad']}")
            db.commit()
            flash("Ürün eklendi. Şimdi hangi araçlara uyduğunu ekleyebilirsiniz.", "basari")
            return redirect(url_for("urunler.detay", urun_id=cur.lastrowid))
    return render_template("urunler/form.html", form=form, hatalar=hatalar, u=None,
                           kategoriler=kategoriler(), tipler=PARCA_TIPLERI)


@bp.route("/<int:urun_id>/duzenle", methods=["GET", "POST"])
@admin_gerekli
def duzenle(urun_id):
    u = urun_getir(urun_id)
    form = {"kod": u["kod"], "ad": u["ad"], "kategori": u["kategori"], "parca_tipi": u["parca_tipi"],
            "perakende": tl_girdi(u["perakende_kurus"]), "toptan": tl_girdi(u["toptan_kurus"]),
            "aktif": bool(u["aktif"])}
    hatalar = {}
    if request.method == "POST":
        form, fiyatlar, hatalar = _form_oku(urun_id)
        if not hatalar:
            degisenler = []
            eski_yeni = [("Kod", u["kod"], form["kod"]), ("Ad", u["ad"], form["ad"]),
                         ("Kategori", u["kategori"], form["kategori"]),
                         ("Parça", u["parca_tipi"], form["parca_tipi"]),
                         ("Perakende", tl_yaz(u["perakende_kurus"]), tl_yaz(fiyatlar["perakende"])),
                         ("Toptan", tl_yaz(u["toptan_kurus"]), tl_yaz(fiyatlar["toptan"])),
                         ("Durum", "aktif" if u["aktif"] else "pasif", "aktif" if form["aktif"] else "pasif")]
            for ad, eski, yeni_deger in eski_yeni:
                if eski != yeni_deger:
                    degisenler.append(f"{ad}: {eski} → {yeni_deger}")
            db = baglanti()
            db.execute(
                """UPDATE urunler SET kod = ?, ad = ?, kategori = ?, parca_tipi = ?, perakende_kurus = ?,
                       toptan_kurus = ?, aktif = ?, guncelleme = ? WHERE id = ?""",
                (form["kod"], form["ad"], form["kategori"], form["parca_tipi"], fiyatlar["perakende"],
                 fiyatlar["toptan"], int(form["aktif"]), simdi(), urun_id),
            )
            if degisenler:
                islem_kaydet("Ürün düzenlendi", f"{form['kod']} — " + "; ".join(degisenler))
            db.commit()
            flash("Ürün kaydedildi.", "basari")
            return redirect(url_for("urunler.detay", urun_id=urun_id))
    return render_template("urunler/form.html", form=form, hatalar=hatalar, u=u,
                           kategoriler=kategoriler(), tipler=PARCA_TIPLERI)


@bp.route("/<int:urun_id>/uyumluluk", methods=["POST"])
@admin_gerekli
def uyumluluk_ekle(urun_id):
    u = urun_getir(urun_id)
    marka_id = request.form.get("marka_id", "")
    model_id = request.form.get("model_id", "")
    if not marka_id.isdigit():
        flash("Marka seçin.", "hata")
        return redirect(url_for("urunler.detay", urun_id=urun_id))
    marka = sorgu("SELECT * FROM markalar WHERE id = ?", (int(marka_id),), tek=True)
    model = None
    if model_id.isdigit():
        model = sorgu("SELECT * FROM modeller WHERE id = ? AND marka_id = ?", (int(model_id), int(marka_id)), tek=True)
    if marka is None or (model_id and model is None):
        flash("Seçilen marka/model bulunamadı.", "hata")
        return redirect(url_for("urunler.detay", urun_id=urun_id))
    var = sorgu(
        "SELECT 1 FROM urun_uyumluluk WHERE urun_id = ? AND marka_id = ? AND model_id IS ?",
        (urun_id, marka["id"], model["id"] if model else None), tek=True,
    )
    if var:
        flash("Bu araç zaten listede.", "bilgi")
    else:
        db = baglanti()
        db.execute("INSERT INTO urun_uyumluluk (urun_id, marka_id, model_id) VALUES (?, ?, ?)",
                   (urun_id, marka["id"], model["id"] if model else None))
        arac = marka["ad"] + (f" {model['ad']}" if model else " (tüm modeller)")
        islem_kaydet("Uyumlu araç eklendi", f"{u['kod']} — {arac}")
        db.commit()
        flash(f"{arac} eklendi.", "basari")
    return redirect(url_for("urunler.detay", urun_id=urun_id))


@bp.route("/<int:urun_id>/uyumluluk/<int:uyum_id>/sil", methods=["POST"])
@admin_gerekli
def uyumluluk_sil(urun_id, uyum_id):
    u = urun_getir(urun_id)
    satir = sorgu(
        """SELECT m.ad AS marka, mo.ad AS model FROM urun_uyumluluk x
           JOIN markalar m ON m.id = x.marka_id LEFT JOIN modeller mo ON mo.id = x.model_id
           WHERE x.id = ? AND x.urun_id = ?""",
        (uyum_id, urun_id), tek=True,
    )
    if satir is None:
        abort(404)
    db = baglanti()
    db.execute("DELETE FROM urun_uyumluluk WHERE id = ?", (uyum_id,))
    arac = satir["marka"] + (f" {satir['model']}" if satir["model"] else " (tüm modeller)")
    islem_kaydet("Uyumlu araç çıkarıldı", f"{u['kod']} — {arac}")
    db.commit()
    flash(f"{arac} çıkarıldı.", "bilgi")
    return redirect(url_for("urunler.detay", urun_id=urun_id))


@bp.route("/toplu-fiyat", methods=["GET", "POST"])
@admin_gerekli
def toplu_fiyat():
    args = request.args
    kosullar, param = ["aktif = 1"], []
    if args.get("kategori"):
        kosullar.append("kategori = ?")
        param.append(args["kategori"])
    if args.get("tip"):
        kosullar.append("parca_tipi = ?")
        param.append(args["tip"])
    if args.get("fiyat") == "eksik":
        kosullar.append("(perakende_kurus IS NULL OR toptan_kurus IS NULL)")
    urunler = sorgu(f"SELECT * FROM urunler WHERE {' AND '.join(kosullar)} ORDER BY kategori, kod", tuple(param))

    girilen, hatalar = {}, {}
    if request.method == "POST":
        idler = [int(i) for i in request.form.getlist("id") if i.isdigit()]
        mevcut = {r["id"]: r for r in sorgu(
            f"SELECT * FROM urunler WHERE id IN ({','.join('?' * len(idler))})", tuple(idler))} if idler else {}
        degisecek = []
        for uid in idler:
            if uid not in mevcut:
                continue
            p_metin = request.form.get(f"p_{uid}", "")
            t_metin = request.form.get(f"t_{uid}", "")
            girilen[uid] = (p_metin, t_metin)
            try:
                p = tl_oku(p_metin)
            except ValueError:
                hatalar[(uid, "p")] = True
                p = None
            try:
                t = tl_oku(t_metin)
            except ValueError:
                hatalar[(uid, "t")] = True
                t = None
            if (p, t) != (mevcut[uid]["perakende_kurus"], mevcut[uid]["toptan_kurus"]):
                degisecek.append((uid, p, t))
        if hatalar:
            flash("Bazı tutarlar okunamadı (kırmızı işaretli). Hiçbir şey kaydedilmedi; düzeltip tekrar kaydedin.", "hata")
        elif not degisecek:
            flash("Değişiklik yok.", "bilgi")
            return redirect(request.full_path)
        else:
            db = baglanti()
            for uid, p, t in degisecek:
                db.execute("UPDATE urunler SET perakende_kurus = ?, toptan_kurus = ?, guncelleme = ? WHERE id = ?",
                           (p, t, simdi(), uid))
            ozet = ", ".join(f"{mevcut[uid]['kod']}: {tl_yaz(p)} / {tl_yaz(t)}" for uid, p, t in degisecek[:20])
            if len(degisecek) > 20:
                ozet += f" … (+{len(degisecek) - 20} ürün)"
            islem_kaydet("Toplu fiyat güncellendi", f"{len(degisecek)} ürün — {ozet}")
            db.commit()
            flash(f"{len(degisecek)} ürünün fiyatı kaydedildi.", "basari")
            return redirect(request.full_path)

    return render_template(
        "urunler/toplu_fiyat.html",
        urunler=urunler, girilen=girilen, hatalar=hatalar,
        kategoriler=kategoriler(), tipler=PARCA_TIPLERI, f=args,
    )


@bp.route("/api/modeller")
@giris_gerekli
def api_modeller():
    marka_id = request.args.get("marka_id", "")
    if not marka_id.isdigit():
        return jsonify([])
    satirlar = sorgu("SELECT id, ad FROM modeller WHERE marka_id = ? ORDER BY ad", (int(marka_id),))
    return jsonify([{"id": s["id"], "ad": s["ad"]} for s in satirlar])
