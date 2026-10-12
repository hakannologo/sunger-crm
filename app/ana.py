"""Ana sayfa."""
from flask import Blueprint, g, render_template

from .db import sorgu
from .yardimci import giris_gerekli

bp = Blueprint("ana", __name__)


@bp.route("/")
@giris_gerekli
def panel():
    sayilar = sorgu(
        """SELECT
             (SELECT COUNT(*) FROM urunler WHERE aktif = 1) AS urun,
             (SELECT COUNT(*) FROM urunler WHERE aktif = 1
                 AND (perakende_kurus IS NULL OR toptan_kurus IS NULL)) AS fiyatsiz,
             (SELECT COUNT(*) FROM markalar) AS marka,
             (SELECT COUNT(*) FROM modeller) AS model,
             (SELECT COUNT(*) FROM kullanicilar WHERE aktif = 1) AS kullanici""",
        tek=True,
    )
    markalar = sorgu("SELECT id, ad FROM markalar ORDER BY ad")
    son_islemler = []
    if g.kullanici["rol"] == "admin":
        son_islemler = sorgu(
            """SELECT i.*, k.ad_soyad FROM islem_kaydi i
               LEFT JOIN kullanicilar k ON k.id = i.kullanici_id
               ORDER BY i.id DESC LIMIT 8"""
        )
    return render_template("panel.html", sayilar=sayilar, markalar=markalar, son_islemler=son_islemler)
