"""Giriş, çıkış, ilk kurulum ve şifre değiştirme."""
import re
from datetime import datetime, timedelta

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import baglanti, sorgu
from .yardimci import TR_SAAT, giris_gerekli, islem_kaydet, simdi

bp = Blueprint("auth", __name__)

KULLANICI_ADI_KALIBI = re.compile(r"^[a-z0-9._-]{3,30}$")
EN_AZ_SIFRE = 6
DENEME_SINIRI = 5           # bu kadar hatalı denemeden sonra
KILIT_SURESI_DK = 10        # bu kadar dakika bekletilir


def sifre_hashle(sifre):
    # pbkdf2 her sunucuda (eski OpenSSL dahil) çalışır.
    return generate_password_hash(sifre, method="pbkdf2:sha256:600000")


def oturum_ac(kullanici):
    session.clear()
    session.permanent = True
    session["kullanici_id"] = kullanici["id"]
    session["sifre_izi"] = kullanici["sifre_hash"][-12:]


def _guvenli_yonlendirme(hedef):
    if hedef and hedef.startswith("/") and not hedef.startswith("//"):
        return hedef
    return url_for("ana.panel")


@bp.route("/giris", methods=["GET", "POST"])
def giris():
    if g.kullanici:
        return redirect(url_for("ana.panel"))

    if request.method == "POST":
        kadi = request.form.get("kullanici_adi", "").strip().lower()
        sifre = request.form.get("sifre", "")
        db = baglanti()

        esik = (datetime.now(TR_SAAT) - timedelta(minutes=KILIT_SURESI_DK)).strftime("%Y-%m-%d %H:%M:%S")
        hatali = sorgu("SELECT COUNT(*) AS n FROM giris_denemeleri WHERE kullanici_adi = ? AND zaman > ?",
                       (kadi, esik), tek=True)["n"]
        if hatali >= DENEME_SINIRI:
            flash(f"Çok fazla hatalı deneme yapıldı. {KILIT_SURESI_DK} dakika sonra tekrar deneyin.", "hata")
            return render_template("giris.html", kullanici_adi=kadi), 429

        k = sorgu("SELECT * FROM kullanicilar WHERE kullanici_adi = ?", (kadi,), tek=True)
        if k is None or not check_password_hash(k["sifre_hash"], sifre):
            db.execute("INSERT INTO giris_denemeleri (kullanici_adi, ip, zaman) VALUES (?, ?, ?)",
                       (kadi, request.remote_addr, simdi()))
            db.commit()
            flash("Kullanıcı adı veya şifre hatalı.", "hata")
            return render_template("giris.html", kullanici_adi=kadi), 401
        if not k["aktif"]:
            flash("Bu hesap pasif durumda. Yöneticiye başvurun.", "hata")
            return render_template("giris.html", kullanici_adi=kadi), 403

        db.execute("DELETE FROM giris_denemeleri WHERE kullanici_adi = ?", (kadi,))
        db.execute("UPDATE kullanicilar SET son_giris = ? WHERE id = ?", (simdi(), k["id"]))
        db.commit()
        oturum_ac(k)
        return redirect(_guvenli_yonlendirme(request.args.get("sonra")))

    return render_template("giris.html", kullanici_adi="")


@bp.route("/cikis", methods=["POST"])
def cikis():
    session.clear()
    flash("Çıkış yapıldı.", "bilgi")
    return redirect(url_for("auth.giris"))


@bp.route("/kurulum", methods=["GET", "POST"])
def kurulum():
    """Hiç yönetici yokken ilk yönetici hesabını oluşturur. Sonra kapanır."""
    if sorgu("SELECT 1 FROM kullanicilar WHERE rol = 'admin' LIMIT 1", tek=True):
        return redirect(url_for("auth.giris"))

    hatalar = {}
    form = {"ad_soyad": "", "kullanici_adi": ""}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("ad_soyad", "kullanici_adi")}
        form["kullanici_adi"] = form["kullanici_adi"].lower()
        sifre = request.form.get("sifre", "")
        sifre2 = request.form.get("sifre2", "")
        if not form["ad_soyad"]:
            hatalar["ad_soyad"] = "Ad soyad gerekli."
        if not KULLANICI_ADI_KALIBI.match(form["kullanici_adi"]):
            hatalar["kullanici_adi"] = "3-30 karakter; küçük harf, rakam, nokta, tire veya alt çizgi."
        if len(sifre) < EN_AZ_SIFRE:
            hatalar["sifre"] = f"Şifre en az {EN_AZ_SIFRE} karakter olmalı."
        elif sifre != sifre2:
            hatalar["sifre2"] = "Şifreler aynı değil."
        if not hatalar:
            db = baglanti()
            cur = db.execute(
                """INSERT INTO kullanicilar (kullanici_adi, ad_soyad, sifre_hash, rol, olusturma, son_giris)
                   VALUES (?, ?, ?, 'admin', ?, ?)""",
                (form["kullanici_adi"], form["ad_soyad"], sifre_hashle(sifre), simdi(), simdi()),
            )
            k = sorgu("SELECT * FROM kullanicilar WHERE id = ?", (cur.lastrowid,), tek=True)
            g.kullanici = k
            islem_kaydet("İlk kurulum", f"Yönetici hesabı oluşturuldu: {k['kullanici_adi']}")
            db.commit()
            oturum_ac(k)
            flash("Kurulum tamamlandı. Hoş geldiniz!", "basari")
            return redirect(url_for("ana.panel"))

    return render_template("kurulum.html", form=form, hatalar=hatalar)


@bp.route("/sifre", methods=["GET", "POST"])
@giris_gerekli
def sifre_degistir():
    hatalar = {}
    if request.method == "POST":
        mevcut = request.form.get("mevcut", "")
        yeni = request.form.get("yeni", "")
        yeni2 = request.form.get("yeni2", "")
        if not check_password_hash(g.kullanici["sifre_hash"], mevcut):
            hatalar["mevcut"] = "Mevcut şifre hatalı."
        if len(yeni) < EN_AZ_SIFRE:
            hatalar["yeni"] = f"Şifre en az {EN_AZ_SIFRE} karakter olmalı."
        elif yeni != yeni2:
            hatalar["yeni2"] = "Şifreler aynı değil."
        if not hatalar:
            db = baglanti()
            db.execute("UPDATE kullanicilar SET sifre_hash = ? WHERE id = ?", (sifre_hashle(yeni), g.kullanici["id"]))
            islem_kaydet("Şifre değiştirildi", g.kullanici["kullanici_adi"])
            db.commit()
            oturum_ac(sorgu("SELECT * FROM kullanicilar WHERE id = ?", (g.kullanici["id"],), tek=True))
            flash("Şifreniz değiştirildi.", "basari")
            return redirect(url_for("ana.panel"))
    return render_template("sifre.html", hatalar=hatalar)
