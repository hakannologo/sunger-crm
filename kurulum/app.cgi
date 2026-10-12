#!/opt/alt/python311/bin/python3
"""cPanel CGI başlatıcısı (Günaydın CRM ile aynı yöntem).

Bu dosya alan adının belge kök dizinindeki cgi-bin/ klasöründe durur.
Program dosyaları (app/ ve packages/) belge kök dizinindedir; veriler ise
internetten erişilemeyen bir üst klasördeki crm-veri/ içinde tutulur.
"""
import os
import sys
import traceback

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERI = os.path.join(os.path.dirname(KOK), "crm-veri")

os.chdir(KOK)
sys.path.insert(0, KOK)
sys.path.insert(0, os.path.join(KOK, "packages"))
os.environ.setdefault("VERI_KLASORU", VERI)
if os.environ.get("HTTPS", "").lower() not in ("on", "1"):
    os.environ["HTTPS_KAPALI"] = "1"

try:
    from wsgiref.handlers import CGIHandler

    from app import create_app

    uygulama = create_app()

    class KokCGIHandler(CGIHandler):
        def setup_environ(self):
            CGIHandler.setup_environ(self)
            # Site alan adının kökünde görünsün (/cgi-bin/app.cgi adreste gizli kalır).
            self.environ["SCRIPT_NAME"] = ""
            yol = self.environ.get("PATH_INFO") or "/"
            onek = "/cgi-bin/app.cgi"
            if yol.startswith(onek):
                self.environ["PATH_INFO"] = yol[len(onek):] or "/"

    KokCGIHandler().run(uygulama)
except Exception:
    os.makedirs(VERI, exist_ok=True)
    with open(os.path.join(VERI, "hata.log"), "a", encoding="utf-8") as f:
        f.write(traceback.format_exc() + "\n")
    sys.stdout.write("Status: 500 Internal Server Error\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n")
    sys.stdout.write("Program başlatılamadı. Ayrıntı: crm-veri/hata.log\n")
