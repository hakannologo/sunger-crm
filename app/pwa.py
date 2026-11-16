"""Telefona yüklenebilir uygulama (PWA): manifest, service worker ve çevrimdışı sayfası.

Bu adresler giriş gerektirmez (tarayıcı uygulamayı yüklerken oturum olmadan ister) ve kişisel veri içermez.
Service worker sitenin köküne (/sw.js) konur ki bütün sayfaları kapsayabilsin.
"""
import json

from flask import Blueprint, current_app, make_response, render_template, url_for

bp = Blueprint("pwa", __name__)

SURUM = "1"   # service worker değişince artırın


@bp.route("/manifest.webmanifest")
def manifest():
    s = lambda ad: url_for("static", filename=f"pwa/{ad}")   # noqa: E731
    veri = {
        "name": "Sünger CRM",
        "short_name": "Sünger CRM",
        "description": f"{current_app.config['FIRMA_ADI']} müşteri takip programı",
        "lang": "tr",
        "id": "/",
        "start_url": "/?kaynak=uygulama",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#f4f2ee",
        "theme_color": "#17594a",
        "icons": [
            {"src": s("simge-192.png"), "sizes": "192x192", "type": "image/png", "purpose": "any"},
            {"src": s("simge-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "any"},
            {"src": s("simge-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Yeni talep", "url": "/talepler/yeni",
             "icons": [{"src": s("simge-192.png"), "sizes": "192x192", "type": "image/png"}]},
            {"name": "Alacaklar", "url": "/alacaklar/",
             "icons": [{"src": s("simge-192.png"), "sizes": "192x192", "type": "image/png"}]},
        ],
    }
    yanit = make_response(json.dumps(veri, ensure_ascii=False))
    yanit.headers["Content-Type"] = "application/manifest+json; charset=utf-8"
    yanit.headers["Cache-Control"] = "public, max-age=3600"
    return yanit


@bp.route("/sw.js")
def service_worker():
    js = render_template("pwa/sw.js", surum=SURUM, cevrimdisi=url_for("pwa.cevrimdisi"),
                         simge=url_for("static", filename="pwa/simge-192.png"))
    yanit = make_response(js)
    yanit.headers["Content-Type"] = "application/javascript; charset=utf-8"
    yanit.headers["Cache-Control"] = "no-cache"
    yanit.headers["Service-Worker-Allowed"] = "/"
    return yanit


@bp.route("/cevrimdisi")
def cevrimdisi():
    return render_template("pwa/cevrimdisi.html")
