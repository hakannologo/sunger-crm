"""cPanel'e yüklenecek tek zip dosyasını hazırlar.

Kullanım: python3 kurulum/paketle.py <packages_klasoru> <cikti.zip>

<packages_klasoru>: Flask ve bağımlılıklarının (Python 3.11 için) bulunduğu klasör.
Zip, alan adının belge kök dizinine açılır:
  .htaccess, cgi-bin/app.cgi, app/, packages/
"""
import os
import sys
import zipfile

PROJE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ekle(z, kaynak, hedef, mod=0o644):
    bilgi = zipfile.ZipInfo(hedef)
    bilgi.compress_type = zipfile.ZIP_DEFLATED
    bilgi.external_attr = (0o100000 | mod) << 16
    with open(kaynak, "rb") as f:
        z.writestr(bilgi, f.read())


def klasor_ekle(z, kaynak_kok, hedef_kok):
    for kok, klasorler, dosyalar in os.walk(kaynak_kok):
        klasorler[:] = [k for k in klasorler if k != "__pycache__"]
        for d in dosyalar:
            if d.startswith("._") or d.endswith(".pyc"):
                continue
            yol = os.path.join(kok, d)
            ekle(z, yol, os.path.join(hedef_kok, os.path.relpath(yol, kaynak_kok)))


def main(paketler, cikti):
    with zipfile.ZipFile(cikti, "w") as z:
        ekle(z, os.path.join(PROJE, "kurulum", "htaccess"), ".htaccess")
        ekle(z, os.path.join(PROJE, "kurulum", "app.cgi"), "cgi-bin/app.cgi", 0o755)
        klasor_ekle(z, os.path.join(PROJE, "app"), "app")
        klasor_ekle(z, paketler, "packages")
    print("hazır:", cikti)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
