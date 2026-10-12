"""Ana sayfa: bugün dönüş yapılacaklar, kısa durum."""
from flask import Blueprint, g, render_template

from .db import sorgu
from .tahsilat import ozet as alacak_ozeti
from .yardimci import KANALLAR, TALEP_DURUMLARI, bugun, giris_gerekli

bp = Blueprint("ana", __name__)


@bp.route("/")
@giris_gerekli
def panel():
    admin = g.kullanici["rol"] == "admin"
    bugun_ = bugun()
    kim_kosulu = "" if admin else "AND t.kullanici_id = ?"
    kim_param = () if admin else (g.kullanici["id"],)

    hatirlatmalar = sorgu(
        f"""SELECT t.*, m.ad AS marka, mo.ad AS model, k.ad_soyad AS kullanici,
                   (SELECT GROUP_CONCAT(urun_adi, ', ') FROM talep_kalemleri WHERE talep_id = t.id) AS urunler,
                   (SELECT metin FROM talep_notlari WHERE talep_id = t.id ORDER BY id DESC LIMIT 1) AS son_not
            FROM talepler t
            LEFT JOIN markalar m ON m.id = t.marka_id LEFT JOIN modeller mo ON mo.id = t.model_id
            LEFT JOIN kullanicilar k ON k.id = t.kullanici_id
            WHERE t.durum IN ('fiyat_verildi', 'dusunuyor') AND t.hatirlatma <= ? {kim_kosulu}
            ORDER BY t.hatirlatma, t.id""",
        (bugun_,) + kim_param,
    )
    sayilar = sorgu(
        f"""SELECT
              (SELECT COUNT(*) FROM talepler t WHERE substr(t.olusturma, 1, 10) = ? {kim_kosulu}) AS bugun_talep,
              (SELECT COUNT(*) FROM talepler t WHERE t.durum IN ('fiyat_verildi', 'dusunuyor') {kim_kosulu}) AS acik_talep,
              (SELECT COUNT(*) FROM talepler t WHERE t.durum IN ('fiyat_verildi', 'dusunuyor')
                   AND t.hatirlatma > ? {kim_kosulu}) AS ileri_hatirlatma,
              (SELECT COUNT(*) FROM satislar WHERE durum = 'hazirlaniyor') AS hazirlanan,
              (SELECT COUNT(*) FROM urunler WHERE aktif = 1 AND (perakende_kurus IS NULL OR toptan_kurus IS NULL)) AS fiyatsiz""",
        (bugun_,) + kim_param + kim_param + (bugun_,) + kim_param,
        tek=True,
    )
    return render_template(
        "panel.html", hatirlatmalar=hatirlatmalar, sayilar=sayilar, bugun=bugun_, admin=admin, alacak=alacak_ozeti(),
        kanallar=KANALLAR, durumlar=TALEP_DURUMLARI,
    )
