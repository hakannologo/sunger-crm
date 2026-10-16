"""Sünger Merkezi Müşteri Takip Programı."""
import os
import secrets
from datetime import timedelta

from flask import Flask, g, redirect, render_template, request, session, url_for

from . import db, sifre_sifirlama
from .yardimci import (KANALLAR, ODEME_SEKILLERI, SATIS_DURUMLARI, TALEP_DURUMLARI, csrf_kontrol, csrf_token,
                       tarih_yaz, tel_yaz, tl_girdi, tl_yaz)

PROJE_KLASORU = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _gizli_anahtar(veri_klasoru):
    """SECRET_KEY ortam değişkeni yoksa veri klasöründe bir kere üretilip saklanır."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    yol = os.path.join(veri_klasoru, "gizli_anahtar")
    if os.path.exists(yol):
        with open(yol) as f:
            return f.read().strip()
    os.makedirs(veri_klasoru, exist_ok=True)
    anahtar = secrets.token_hex(32)
    with open(yol, "w") as f:
        f.write(anahtar)
    os.chmod(yol, 0o600)
    return anahtar


def create_app(ayarlar=None):
    app = Flask(__name__)

    # Veriler varsayılan olarak proje içindeki "veri/" klasöründe durur (git'e girmez).
    veri_klasoru = os.environ.get("VERI_KLASORU", os.path.join(PROJE_KLASORU, "veri"))
    app.config.update(
        DATABASE=os.path.join(veri_klasoru, "crm.sqlite3"),
        FIRMA_ADI=os.environ.get("FIRMA_ADI", "Sünger Merkezi"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("HTTPS_KAPALI") != "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    )
    if ayarlar:
        app.config.update(ayarlar)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _gizli_anahtar(os.path.dirname(app.config["DATABASE"]))

    db.guncelle(app.config["DATABASE"])
    sifre_sifirlama.calistir(app.config["DATABASE"])
    app.teardown_appcontext(db.kapat)

    app.jinja_env.filters["tl"] = tl_yaz
    app.jinja_env.filters["tl_girdi"] = tl_girdi
    app.jinja_env.filters["tarih"] = tarih_yaz
    app.jinja_env.filters["tel"] = tel_yaz
    app.jinja_env.globals.update(KANALLAR=KANALLAR, TALEP_DURUMLARI=TALEP_DURUMLARI,
                                 SATIS_DURUMLARI=SATIS_DURUMLARI, ODEME_SEKILLERI=ODEME_SEKILLERI)
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.before_request
    def oturum_yukle():
        csrf_kontrol()
        g.kullanici = None
        kid = session.get("kullanici_id")
        if kid is not None:
            k = db.sorgu("SELECT * FROM kullanicilar WHERE id = ?", (kid,), tek=True)
            # Pasife alınan kullanıcının açık oturumu da kapanır.
            if k is not None and k["aktif"] and k["sifre_hash"][-12:] == session.get("sifre_izi"):
                g.kullanici = k
            else:
                session.clear()

        # Hiç yönetici yoksa her şey ilk kurulum ekranına yönlenir.
        if request.endpoint not in ("auth.kurulum", "static"):
            admin_var = db.sorgu("SELECT 1 FROM kullanicilar WHERE rol = 'admin' LIMIT 1", tek=True)
            if admin_var is None:
                return redirect(url_for("auth.kurulum"))

    @app.after_request
    def guvenlik_basliklari(yanit):
        yanit.headers.setdefault("X-Content-Type-Options", "nosniff")
        yanit.headers.setdefault("X-Frame-Options", "DENY")
        yanit.headers.setdefault("Referrer-Policy", "same-origin")
        return yanit

    @app.context_processor
    def ortak_degiskenler():
        return {"firma_adi": app.config["FIRMA_ADI"], "kullanici": g.get("kullanici")}

    @app.errorhandler(400)
    def hata_400(e):
        return render_template("hata.html", baslik="İstek işlenemedi", mesaj=e.description), 400

    @app.errorhandler(404)
    def hata_404(e):
        return render_template("hata.html", baslik="Sayfa bulunamadı",
                               mesaj="Aradığınız sayfa yok ya da kaldırılmış."), 404

    @app.errorhandler(500)
    def hata_500(e):
        return render_template("hata.html", baslik="Bir hata oluştu",
                               mesaj="Beklenmeyen bir sorun oldu. Tekrar deneyin; sürerse yöneticiye haber verin."), 500

    from . import ana, auth, satislar, tahsilat, talepler, urunler, yonetim
    app.register_blueprint(auth.bp)
    app.register_blueprint(ana.bp)
    app.register_blueprint(talepler.bp)
    app.register_blueprint(satislar.bp)
    app.register_blueprint(tahsilat.bp)
    app.register_blueprint(urunler.bp)
    app.register_blueprint(yonetim.bp)

    return app
