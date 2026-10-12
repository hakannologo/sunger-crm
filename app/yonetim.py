"""Yönetici ekranları: kullanıcılar, marka/model listesi, işlem kaydı."""
import sqlite3

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .auth import EN_AZ_SIFRE, KULLANICI_ADI_KALIBI, sifre_hashle
from .db import baglanti, sorgu, tr_kucuk
from .yardimci import Sayfa, admin_gerekli, islem_kaydet, sayfa_no, simdi

bp = Blueprint("yonetim", __name__, url_prefix="/yonetim")

ROLLER = {"admin": "Yönetici", "kullanici": "Kullanıcı"}


# --------------------------------------------------------------------------- #
# Kullanıcılar
# --------------------------------------------------------------------------- #

@bp.route("/kullanicilar")
@admin_gerekli
def kullanicilar():
    liste = sorgu("SELECT * FROM kullanicilar ORDER BY aktif DESC, rol, ad_soyad")
    return render_template("yonetim/kullanicilar.html", liste=liste, roller=ROLLER)


def _kullanici_getir(kid):
    k = sorgu("SELECT * FROM kullanicilar WHERE id = ?", (kid,), tek=True)
    if k is None:
        abort(404)
    return k


@bp.route("/kullanicilar/yeni", methods=["GET", "POST"])
@admin_gerekli
def kullanici_yeni():
    form = {"ad_soyad": "", "kullanici_adi": "", "rol": "kullanici"}
    hatalar = {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("ad_soyad", "kullanici_adi", "rol")}
        form["kullanici_adi"] = form["kullanici_adi"].lower()
        sifre, sifre2 = request.form.get("sifre", ""), request.form.get("sifre2", "")
        if not form["ad_soyad"]:
            hatalar["ad_soyad"] = "Ad soyad gerekli."
        if not KULLANICI_ADI_KALIBI.match(form["kullanici_adi"]):
            hatalar["kullanici_adi"] = "3-30 karakter; küçük harf, rakam, nokta, tire veya alt çizgi."
        elif sorgu("SELECT 1 FROM kullanicilar WHERE kullanici_adi = ?", (form["kullanici_adi"],), tek=True):
            hatalar["kullanici_adi"] = "Bu kullanıcı adı alınmış."
        if form["rol"] not in ROLLER:
            hatalar["rol"] = "Rol seçin."
        if len(sifre) < EN_AZ_SIFRE:
            hatalar["sifre"] = f"Şifre en az {EN_AZ_SIFRE} karakter olmalı."
        elif sifre != sifre2:
            hatalar["sifre2"] = "Şifreler aynı değil."
        if not hatalar:
            db = baglanti()
            db.execute(
                """INSERT INTO kullanicilar (kullanici_adi, ad_soyad, sifre_hash, rol, olusturma)
                   VALUES (?, ?, ?, ?, ?)""",
                (form["kullanici_adi"], form["ad_soyad"], sifre_hashle(sifre), form["rol"], simdi()),
            )
            islem_kaydet("Kullanıcı eklendi", f"{form['ad_soyad']} ({form['kullanici_adi']}, {ROLLER[form['rol']]})")
            db.commit()
            flash(f"{form['ad_soyad']} eklendi. Kullanıcı adını ve şifresini kendisine iletin.", "basari")
            return redirect(url_for("yonetim.kullanicilar"))
    return render_template("yonetim/kullanici_form.html", form=form, hatalar=hatalar, k=None, roller=ROLLER)


@bp.route("/kullanicilar/<int:kid>", methods=["GET", "POST"])
@admin_gerekli
def kullanici_duzenle(kid):
    k = _kullanici_getir(kid)
    kendisi = k["id"] == g.kullanici["id"]
    form = {"ad_soyad": k["ad_soyad"], "kullanici_adi": k["kullanici_adi"], "rol": k["rol"], "aktif": bool(k["aktif"])}
    hatalar = {}
    if request.method == "POST":
        form["ad_soyad"] = request.form.get("ad_soyad", "").strip()
        form["rol"] = request.form.get("rol", "")
        form["aktif"] = request.form.get("aktif") == "1"
        sifre, sifre2 = request.form.get("sifre", ""), request.form.get("sifre2", "")
        if not form["ad_soyad"]:
            hatalar["ad_soyad"] = "Ad soyad gerekli."
        if form["rol"] not in ROLLER:
            hatalar["rol"] = "Rol seçin."
        if kendisi and (form["rol"] != "admin" or not form["aktif"]):
            hatalar["rol"] = "Kendi yönetici yetkinizi kaldıramaz veya kendinizi pasife alamazsınız."
            form["rol"], form["aktif"] = k["rol"], bool(k["aktif"])
        elif k["rol"] == "admin" and (form["rol"] != "admin" or not form["aktif"]):
            diger = sorgu("SELECT COUNT(*) AS n FROM kullanicilar WHERE rol = 'admin' AND aktif = 1 AND id != ?",
                          (kid,), tek=True)["n"]
            if diger == 0:
                hatalar["rol"] = "En az bir aktif yönetici kalmalı."
        if sifre or sifre2:
            if len(sifre) < EN_AZ_SIFRE:
                hatalar["sifre"] = f"Şifre en az {EN_AZ_SIFRE} karakter olmalı."
            elif sifre != sifre2:
                hatalar["sifre2"] = "Şifreler aynı değil."
        if not hatalar:
            db = baglanti()
            db.execute("UPDATE kullanicilar SET ad_soyad = ?, rol = ?, aktif = ? WHERE id = ?",
                       (form["ad_soyad"], form["rol"], int(form["aktif"]), kid))
            notlar = []
            if form["rol"] != k["rol"]:
                notlar.append(f"rol: {ROLLER[k['rol']]} → {ROLLER[form['rol']]}")
            if form["aktif"] != bool(k["aktif"]):
                notlar.append("aktif edildi" if form["aktif"] else "pasife alındı")
            if form["ad_soyad"] != k["ad_soyad"]:
                notlar.append(f"ad: {k['ad_soyad']} → {form['ad_soyad']}")
            if sifre:
                db.execute("UPDATE kullanicilar SET sifre_hash = ? WHERE id = ?", (sifre_hashle(sifre), kid))
                notlar.append("şifre sıfırlandı")
            if notlar:
                islem_kaydet("Kullanıcı güncellendi", f"{k['kullanici_adi']} — " + ", ".join(notlar))
            db.commit()
            if kendisi and sifre:
                from .auth import oturum_ac
                oturum_ac(_kullanici_getir(kid))
            flash("Kullanıcı kaydedildi.", "basari")
            return redirect(url_for("yonetim.kullanicilar"))
    return render_template("yonetim/kullanici_form.html", form=form, hatalar=hatalar, k=k, roller=ROLLER,
                           kendisi=kendisi)


# --------------------------------------------------------------------------- #
# Marka / model
# --------------------------------------------------------------------------- #

@bp.route("/markalar", methods=["GET", "POST"])
@admin_gerekli
def markalar():
    if request.method == "POST":
        ad = request.form.get("ad", "").strip()
        if not ad:
            flash("Marka adı yazın.", "hata")
        else:
            db = baglanti()
            try:
                cur = db.execute("INSERT INTO markalar (ad) VALUES (?)", (ad,))
            except sqlite3.IntegrityError:
                flash(f"{ad} zaten listede.", "bilgi")
            else:
                islem_kaydet("Marka eklendi", ad)
                db.commit()
                flash(f"{ad} eklendi. Şimdi modellerini ekleyebilirsiniz.", "basari")
                return redirect(url_for("yonetim.marka", marka_id=cur.lastrowid))
        return redirect(url_for("yonetim.markalar"))

    liste = sorgu(
        """SELECT m.*,
                  (SELECT COUNT(*) FROM modeller mo WHERE mo.marka_id = m.id) AS model_sayisi,
                  (SELECT COUNT(DISTINCT x.urun_id) FROM urun_uyumluluk x WHERE x.marka_id = m.id) AS urun_sayisi
           FROM markalar m ORDER BY m.ad"""
    )
    return render_template("yonetim/markalar.html", liste=liste)


def _marka_getir(marka_id):
    m = sorgu("SELECT * FROM markalar WHERE id = ?", (marka_id,), tek=True)
    if m is None:
        abort(404)
    return m


@bp.route("/markalar/<int:marka_id>")
@admin_gerekli
def marka(marka_id):
    m = _marka_getir(marka_id)
    modeller = sorgu(
        """SELECT mo.*, (SELECT COUNT(DISTINCT x.urun_id) FROM urun_uyumluluk x WHERE x.model_id = mo.id) AS urun_sayisi
           FROM modeller mo WHERE mo.marka_id = ? ORDER BY mo.ad""",
        (marka_id,),
    )
    genel = sorgu(
        "SELECT COUNT(DISTINCT urun_id) AS n FROM urun_uyumluluk WHERE marka_id = ? AND model_id IS NULL",
        (marka_id,), tek=True,
    )["n"]
    return render_template("yonetim/marka.html", m=m, modeller=modeller, genel=genel)


@bp.route("/markalar/<int:marka_id>/ad", methods=["POST"])
@admin_gerekli
def marka_ad(marka_id):
    m = _marka_getir(marka_id)
    ad = request.form.get("ad", "").strip()
    if ad and ad != m["ad"]:
        db = baglanti()
        try:
            db.execute("UPDATE markalar SET ad = ? WHERE id = ?", (ad, marka_id))
        except sqlite3.IntegrityError:
            flash(f"{ad} adında başka bir marka var.", "hata")
        else:
            islem_kaydet("Marka adı değişti", f"{m['ad']} → {ad}")
            db.commit()
            flash("Marka adı güncellendi.", "basari")
    return redirect(url_for("yonetim.marka", marka_id=marka_id))


@bp.route("/markalar/<int:marka_id>/sil", methods=["POST"])
@admin_gerekli
def marka_sil(marka_id):
    m = _marka_getir(marka_id)
    if sorgu("SELECT 1 FROM urun_uyumluluk WHERE marka_id = ? LIMIT 1", (marka_id,), tek=True):
        flash("Bu markaya bağlı ürünler var. Önce ürünlerden çıkarın.", "hata")
        return redirect(url_for("yonetim.marka", marka_id=marka_id))
    db = baglanti()
    db.execute("DELETE FROM markalar WHERE id = ?", (marka_id,))
    islem_kaydet("Marka silindi", m["ad"])
    db.commit()
    flash(f"{m['ad']} silindi.", "bilgi")
    return redirect(url_for("yonetim.markalar"))


@bp.route("/markalar/<int:marka_id>/model", methods=["POST"])
@admin_gerekli
def model_ekle(marka_id):
    m = _marka_getir(marka_id)
    ad = request.form.get("ad", "").strip()
    if not ad:
        flash("Model adı yazın.", "hata")
    else:
        db = baglanti()
        try:
            db.execute("INSERT INTO modeller (marka_id, ad) VALUES (?, ?)", (marka_id, ad))
        except sqlite3.IntegrityError:
            flash(f"{m['ad']} {ad} zaten listede.", "bilgi")
        else:
            islem_kaydet("Model eklendi", f"{m['ad']} {ad}")
            db.commit()
            flash(f"{m['ad']} {ad} eklendi.", "basari")
    return redirect(url_for("yonetim.marka", marka_id=marka_id))


def _model_getir(model_id):
    mo = sorgu(
        "SELECT mo.*, m.ad AS marka FROM modeller mo JOIN markalar m ON m.id = mo.marka_id WHERE mo.id = ?",
        (model_id,), tek=True,
    )
    if mo is None:
        abort(404)
    return mo


@bp.route("/modeller/<int:model_id>/ad", methods=["POST"])
@admin_gerekli
def model_ad(model_id):
    mo = _model_getir(model_id)
    ad = request.form.get("ad", "").strip()
    if ad and ad != mo["ad"]:
        db = baglanti()
        try:
            db.execute("UPDATE modeller SET ad = ? WHERE id = ?", (ad, model_id))
        except sqlite3.IntegrityError:
            flash(f"{mo['marka']} {ad} zaten var.", "hata")
        else:
            islem_kaydet("Model adı değişti", f"{mo['marka']} {mo['ad']} → {ad}")
            db.commit()
            flash("Model adı güncellendi.", "basari")
    return redirect(url_for("yonetim.marka", marka_id=mo["marka_id"]))


@bp.route("/modeller/<int:model_id>/sil", methods=["POST"])
@admin_gerekli
def model_sil(model_id):
    mo = _model_getir(model_id)
    if sorgu("SELECT 1 FROM urun_uyumluluk WHERE model_id = ? LIMIT 1", (model_id,), tek=True):
        flash("Bu modele bağlı ürünler var. Önce ürünlerden çıkarın.", "hata")
    else:
        db = baglanti()
        db.execute("DELETE FROM modeller WHERE id = ?", (model_id,))
        islem_kaydet("Model silindi", f"{mo['marka']} {mo['ad']}")
        db.commit()
        flash(f"{mo['marka']} {mo['ad']} silindi.", "bilgi")
    return redirect(url_for("yonetim.marka", marka_id=mo["marka_id"]))


# --------------------------------------------------------------------------- #
# İşlem kaydı
# --------------------------------------------------------------------------- #

@bp.route("/islem-kaydi")
@admin_gerekli
def islem_kaydi():
    kosullar, param = [], []
    kid = request.args.get("kullanici", "")
    if kid.isdigit():
        kosullar.append("i.kullanici_id = ?")
        param.append(int(kid))
    q = request.args.get("q", "").strip()
    if q:
        kosullar.append("tr_kucuk(i.islem || ' ' || COALESCE(i.detay, '')) LIKE ?")
        param.append(f"%{tr_kucuk(q)}%")
    where = ("WHERE " + " AND ".join(kosullar)) if kosullar else ""
    toplam = sorgu(f"SELECT COUNT(*) AS n FROM islem_kaydi i {where}", tuple(param), tek=True)["n"]
    sayfa = Sayfa(toplam, sayfa_no(), 50)
    kayitlar = sorgu(
        f"""SELECT i.*, k.ad_soyad FROM islem_kaydi i LEFT JOIN kullanicilar k ON k.id = i.kullanici_id
            {where} ORDER BY i.id DESC LIMIT ? OFFSET ?""",
        tuple(param) + (sayfa.boyut, sayfa.ofset),
    )
    return render_template(
        "yonetim/islem_kaydi.html", kayitlar=kayitlar, sayfa=sayfa, f=request.args,
        kullanicilar=sorgu("SELECT id, ad_soyad FROM kullanicilar ORDER BY ad_soyad"),
    )
