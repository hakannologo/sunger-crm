"""PDF'ten çıkarılan ürün listesini temizleyip CSV'ye çevirir.

Kullanım: python3 parse_urunler.py girdi.txt cikti.csv
"""
import csv
import re
import sys

# Grup adı -> (gösterilecek kategori, varsayılan marka)
GRUPLAR = {
    "TOYOTA GRUBU": ("Toyota Grubu", "Toyota"),
    "OPEL GRUBU": ("Opel Grubu", "Opel"),
    "AMBULANS": ("Ambulans", None),
    "BAŞLIK GRUBU": ("Başlık Grubu", None),
    "BMC GRUBU": ("BMC Grubu", "BMC"),
    "BMW GRUBU": ("BMW Grubu", "BMW"),
    "CHEVROLET GRUBU": ("Chevrolet Grubu", "Chevrolet"),
    "CİTROEN GRUBU": ("Citroen Grubu", "Citroen"),
    "DACİA GRUBU": ("Dacia Grubu", "Dacia"),
    "DAF GRUBU": ("DAF Grubu", "DAF"),
    "FİAT GRUBU": ("Fiat Grubu", "Fiat"),
    "FORD GRUBU": ("Ford Grubu", "Ford"),
    "HYUNDAİ GRUBU": ("Hyundai Grubu", "Hyundai"),
    "İŞ MAKİNESİ GRUBU": ("İş Makinesi Grubu", None),
    "ISUZU GRUBU": ("Isuzu Grubu", "Isuzu"),
    "IVECO GRUBU": ("Iveco Grubu", "Iveco"),
    "KİA GRUBU": ("Kia Grubu", "Kia"),
    "KOLÇAK GRUBU": ("Kolçak Grubu", None),
    "LADA GRUBU": ("Lada Grubu", "Lada"),
    "MAN GRUBU": ("MAN Grubu", "MAN"),
    "MAZDA GRUBU": ("Mazda Grubu", "Mazda"),
    "MERCEDES GRUBU": ("Mercedes Grubu", "Mercedes"),
    "MİTSUBİSHİ GRUBU": ("Mitsubishi Grubu", "Mitsubishi"),
    "NİSSAN GRUBU": ("Nissan Grubu", "Nissan"),
    "OTOBÜS GRUBU": ("Otobüs Grubu", None),
    "PEUGEOT GRUBU": ("Peugeot Grubu", "Peugeot"),
    "PİLOT GRUBU": ("Pilot Grubu", None),
    "RENAULT GRUBU": ("Renault Grubu", "Renault"),
    "SCANİA GRUBU": ("Scania Grubu", "Scania"),
    "SEAT GRUBU": ("Seat Grubu", "Seat"),
    "SKODA GRUBU": ("Skoda Grubu", "Skoda"),
    "TRAKTÖR GRUBU": ("Traktör Grubu", None),
    "VİP TAKIMLAR": ("VIP Takımlar", None),
    "VOLVO TIR GRUBU": ("Volvo Tır Grubu", "Volvo"),
    "VOLKSWAGEN GRUBU": ("Volkswagen Grubu", "Volkswagen"),
}

# (marka, model, [ürün adında aranacak kalıplar]) — sıralama önemli değil,
# her kalıp kelime sınırıyla aranır, büyük/küçük harf duyarsız.
MODELLER = [
    ("Toyota", "Corolla", [r"corolla", r"coralla"]),
    ("Toyota", "Hilux", [r"hilux"]),
    ("Toyota", "Yaris", [r"yaris"]),
    ("Toyota", "101", [r"toyota 101"]),
    ("Toyota", "Avensis", [r"avensis"]),
    ("Opel", "Astra", [r"astra"]),
    ("Opel", "Corsa", [r"corsa"]),
    ("Opel", "Combo", [r"combo"]),
    ("Opel", "Vectra", [r"vectra"]),
    ("BMW", "5.20", [r"5\.20"]),
    ("BMW", "M3", [r"m3"]),
    ("BMW", "E36", [r"e36"]),
    ("BMW", "E46", [r"e46"]),
    ("Chevrolet", "Captiva", [r"captiva"]),
    ("Citroen", "Berlingo", [r"berlingo"]),
    ("Citroen", "Jumper", [r"jumper"]),
    ("Citroen", "Nemo", [r"nemo"]),
    ("Citroen", "C4", [r"c-4", r"c4"]),
    ("Citroen", "C-Elysée", [r"elysea", r"elysee"]),
    ("Dacia", "Stepway", [r"stepway"]),
    ("Dacia", "Logan", [r"logan"]),
    ("Dacia", "Lodgy", [r"lodgy"]),
    ("Dacia", "Duster", [r"duster"]),
    ("Fiat", "Ducato", [r"ducato"]),
    ("Fiat", "Albea", [r"albea"]),
    ("Fiat", "Linea", [r"linea"]),
    ("Fiat", "Egea", [r"egea"]),
    ("Fiat", "Siena", [r"siena"]),
    ("Fiat", "Marea", [r"marea"]),
    ("Fiat", "Fiorino", [r"fiorino"]),
    ("Fiat", "Scudo", [r"sucuto", r"scudo"]),
    ("Fiat", "Punto", [r"punto"]),
    ("Fiat", "Doblo", [r"doblo"]),
    ("Fiat", "Uno", [r"uno"]),
    ("Tofaş", "Doğan SLX", [r"doğan"]),
    ("Tofaş", "Şahin", [r"şahin(?! bakışlı)"]),
    ("Ford", "Transit", [r"transit(?!/)"]),
    ("Ford", "Connect", [r"connect"]),
    ("Ford", "Custom", [r"custom"]),
    ("Ford", "Courier", [r"courier"]),
    ("Ford", "Cargo", [r"ford kargo", r"cargo"]),
    ("Ford", "Ranger", [r"ranger"]),
    ("Ford", "Fiesta", [r"fiesta"]),
    ("Ford", "Escort", [r"escort"]),
    ("Ford", "Focus", [r"focus"]),
    ("Ford", "Fusion", [r"fusion"]),
    ("Ford", "Taunus", [r"taunus"]),
    ("Hyundai", "H-100", [r"h-100"]),
    ("Hyundai", "Accent Era", [r"era"]),
    ("Hyundai", "Accent Blue", [r"accent blue"]),
    ("Hyundai", "Starex", [r"starex"]),
    ("Honda", "Civic", [r"civic"]),
    ("Honda", "CR-V", [r"crv", r"cr-v"]),
    ("Isuzu", "Şampiyon", [r"şampiyon"]),
    ("Isuzu", "Nova", [r"nova"]),
    ("Isuzu", "D-Max", [r"d-max"]),
    ("Iveco", "Daily", [r"dally", r"daily"]),
    ("Kia", "Ceres", [r"çerez", r"ceres"]),
    ("Kia", "Bongo", [r"bongo"]),
    ("Mercedes", "Axor", [r"aksor", r"axor"]),
    ("Mercedes", "W123", [r"123 kasa"]),
    ("Mercedes", "Arocs", [r"arox", r"arocs"]),
    ("Mercedes", "Actros", [r"actross", r"actros"]),
    ("Mercedes", "Sprinter", [r"sprinter"]),
    ("Mercedes", "Vito", [r"vito"]),
    ("Mitsubishi", "Canter", [r"canter", r"fuso"]),
    ("Mitsubishi", "L200", [r"l-200"]),
    ("Mitsubishi", "L300", [r"l-300"]),
    ("Mitsubishi", "Carisma", [r"carisma"]),
    ("Nissan", "Qashqai", [r"qashqai"]),
    ("Nissan", "Juke", [r"juke"]),
    ("Nissan", "Navara", [r"navara"]),
    ("Nissan", "Skystar", [r"skaystar", r"skystar"]),
    ("Peugeot", "Partner", [r"partner"]),
    ("Peugeot", "307", [r"307"]),
    ("Peugeot", "206", [r"206"]),
    ("Peugeot", "301", [r"301"]),
    ("Peugeot", "Boxer", [r"boxer"]),
    ("Peugeot", "Bipper", [r"bipper"]),
    ("Karsan", "Jest", [r"jest"]),
    ("Renault", "Kangoo", [r"kango"]),
    ("Renault", "Master", [r"master"]),
    ("Renault", "Trafic", [r"traffic", r"trafic"]),
    ("Renault", "R9", [r"reno-9", r"r-9"]),
    ("Renault", "R12", [r"reno-12", r"r-12"]),
    ("Renault", "R19", [r"reno-19"]),
    ("Renault", "Fluence", [r"fluence"]),
    ("Renault", "Clio", [r"clio"]),
    ("Renault", "Megane", [r"megan"]),
    ("Renault", "Symbol", [r"symbol"]),
    ("Renault", "420", [r"reno 420"]),
    ("Scania", "360", [r"scania 360"]),
    ("Scania", "420", [r"scania 420"]),
    ("Seat", "Toledo", [r"toledo"]),
    ("Skoda", "Octavia", [r"octavia"]),
    ("Volvo", "420", [r"volvo 420"]),
    ("Volvo", "460", [r"volvo 460"]),
    ("Volkswagen", "Polo", [r"polo"]),
    ("Volkswagen", "Golf", [r"golf"]),
    ("Volkswagen", "Bora", [r"bora"]),
    ("Volkswagen", "Passat", [r"passat"]),
    ("Volkswagen", "Crafter", [r"crafter"]),
    ("Volkswagen", "Transporter T4", [r"t-4"]),
    ("Volkswagen", "Transporter T5", [r"t-5"]),
    ("Volkswagen", "Transporter", [r"transporter"]),
    ("Volkswagen", "Caddy", [r"caddy"]),
    ("Volkswagen", "Amarok", [r"amarok"]),
    ("Volkswagen", "LT 35", [r"lt-35"]),
]

# Sadece markaya uyan ürünler (model belirsiz) — ürün adında marka geçiyorsa
MARKA_KALIPLARI = [
    ("BMC", r"bmc"),
    ("DAF", r"daf"),
    ("MAN", r"man"),
    ("Lada", r"lada"),
    ("Iveco", r"iveco"),
    ("Isuzu", r"isuzu"),
    ("Mazda", r"mazda"),
    ("Karsan", r"karsan"),
    ("Toyota", r"toyota"),
]


def tr_lower(s):
    return s.replace("I", "ı").replace("İ", "i").lower()


def kalip_var(kalip, metin):
    return re.search(r"(?<![\w])" + kalip + r"(?![\w])", metin) is not None


def kod_duzelt(kod):
    """Kod yazımını tek biçime getirir: SM-MARKA-001."""
    k = kod.strip().upper()
    k = (k.replace("İ", "I").replace("Ç", "C").replace("Ş", "S")
          .replace("Ğ", "G").replace("Ü", "U").replace("Ö", "O"))
    k = re.sub(r"\s+", "-", k)
    k = k.replace("MITSUBUSHI", "MITSUBISHI").replace("SM-RENO-", "SM-RENAULT-")
    if k.startswith("WW-"):
        k = "SM-" + k
    return k


def parca_tipi(ad):
    a = tr_lower(ad)
    if "takım" in a or ("oturak" in a and "sırt" in a):
        return "Takım"
    a = a.replace("kolçaklı", "").replace("kolçaksız", "")
    for anahtar, tip in [("başlık", "Başlık"), ("kolçak", "Kolçak"), ("baldır", "Baldır"),
                         ("oturak", "Oturak"), ("sırt", "Sırt")]:
        if anahtar in a:
            return tip
    if "pilot" in a:
        return "Oturak"
    return "Diğer"


AD_DUZELTME = {
    "TOYOTA TERRA-TOYOTA AVENSİS UYUMLU OTURAK SÜNGERİ": "Toyota Terra / Avensis Uyumlu Oturak Süngeri",
    "DOBLO SIRT (YENİ MODEL) UYUMLU SÜNGER": "Doblo Uyumlu Sırt Süngeri (Yeni Model)",
    "Hyundaı H-100 Uyumlu Sırt Süngeri": "Hyundai H-100 Uyumlu Sırt Süngeri",
    "Reno-9 (BOADWAY )Uyumlu Sırt Süngeri": "Reno-9 (Broadway) Uyumlu Sırt Süngeri",
    "Reno-9 (BROADWAY) Uyumlu Oturak Süngeri": "Reno-9 (Broadway) Uyumlu Oturak Süngeri",
    "Opel astra G kasa uyumlu oturak süngeri": "Opel Astra G Kasa Uyumlu Oturak Süngeri",
    "FİAT ALBEA SOLE UYUMLU SIRT SÜNGERİ": "Fiat Albea Sole Uyumlu Sırt Süngeri",
    "FORD TAUNUS UYUMLU OTURAK SÜNGERİ": "Ford Taunus Uyumlu Oturak Süngeri",
    "FORD TAUNUS UYUMLU SIRT SÜNGERİ": "Ford Taunus Uyumlu Sırt Süngeri",
    "TOYOTA COROLLA (2013/14/15/16/17/2018 MODEL) UYUMLU OTURAK SÜNGERİ": "Toyota Corolla (2013-2018 Model) Uyumlu Oturak Süngeri",
    "TRANSİT KOLÇAK (SAĞ)": "Transit Kolçak Süngeri (Sağ)",
    "TRANSİT KOLÇAK (SOL)": "Transit Kolçak Süngeri (Sol)",
    "MASTER KOLÇAK (SAĞ)": "Master Kolçak Süngeri (Sağ)",
    "UZUN ORTA KOLÇAK (SAĞ)": "Uzun Orta Kolçak Süngeri (Sağ)",
    "UZUN ORTA KOLÇAK (SOL)": "Uzun Orta Kolçak Süngeri (Sol)",
    "Transporter Uyumlu Kolçak Süngeri (SOL)": "Transporter Uyumlu Kolçak Süngeri (Sol)",
    "FUSO Canter Yeni Uyumlu 2'li Oturak Süngeri": "Fuso Canter Yeni Uyumlu 2'li Oturak Süngeri",
}


def guzel_ad(ad):
    if ad in AD_DUZELTME:
        return AD_DUZELTME[ad]
    """Tamamı büyük harf yazılmış adları okunur hale getirir."""
    harfler = [c for c in ad if c.isalpha()]
    if harfler and sum(c.isupper() for c in harfler) / len(harfler) > 0.8:
        kelimeler = []
        for w in ad.split(" "):
            if re.fullmatch(r"[A-ZİĞÜŞÖÇ]{2,4}", w) and w in {"BMW", "BMC", "SLX", "VIP", "MAN", "DAF"}:
                kelimeler.append(w)
            elif w:
                kucuk = tr_lower(w)
                kelimeler.append(kucuk[0].upper().replace("i", "İ") + kucuk[1:] if kucuk[0] != "i" else "İ" + kucuk[1:])
        return " ".join(kelimeler)
    # İlk harfi büyük yap (örn. "Opel astra G kasa ...")
    return ad[0].upper() + ad[1:]


def main(girdi, cikti):
    satirlar = []
    with open(girdi, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i == 0 or not line.strip():
                continue
            parcalar = re.split(r"\s{2,}", line.strip())
            if len(parcalar) == 2:
                parcalar = [""] + parcalar
            kod, ad, grup = parcalar
            satirlar.append((kod.strip(), ad.strip(), grup.strip()))

    kayitlar = []
    kullanilan = {}
    notlar = []
    for orijinal_kod, ad, grup in satirlar:
        kategori, varsayilan_marka = GRUPLAR[grup]
        kod = kod_duzelt(orijinal_kod) if orijinal_kod else ""
        a = tr_lower(ad)

        uyum = []
        for marka, model, kaliplar in MODELLER:
            if any(kalip_var(k, a) for k in kaliplar):
                uyum.append((marka, model))
        # "Accent Era" ile "Era" çakışmasın, "Transporter" T4/T5'te tekrar etmesin
        if ("Hyundai", "Accent Blue") in uyum and ("Hyundai", "Accent Era") in uyum and "era" not in a.replace("accent blue", ""):
            uyum.remove(("Hyundai", "Accent Era"))
        # Ford grubundaki "Transit" kalıbı Custom ile birlikte gelirse ikisi de kalsın (ürün ikisine uyuyor)
        # Marka grubu ürünlerinde başka markadan model eşleşmesi varsa (örn. Fiat Grubu'nda Doblo) sorun yok.
        if not uyum:
            for marka, kalip in MARKA_KALIPLARI:
                if kalip_var(kalip, a):
                    uyum.append((marka, ""))
                    break
        if not uyum and varsayilan_marka:
            uyum.append((varsayilan_marka, ""))

        # Yanlış grupta duran ürünlerin kategorisini düzelt
        markalar = {m for m, _ in uyum}
        if markalar == {"Honda"}:
            kategori = "Honda Grubu"
            notlar.append(f"{orijinal_kod}: Hyundai Grubu -> Honda Grubu")
        if markalar == {"Karsan"}:
            kategori = "Karsan Grubu"
            notlar.append(f"{orijinal_kod}: Peugeot Grubu -> Karsan Grubu")

        kayitlar.append({
            "kod": kod, "orijinal_kod": orijinal_kod, "ad": guzel_ad(ad),
            "kategori": kategori, "parca_tipi": parca_tipi(ad),
            "uyumluluk": ";".join(f"{m}|{mo}" for m, mo in uyum),
        })

    # Kod düzeltmeleri: grupla uyumsuz, kodsuz veya çakışan kodlar
    ozel = {
        "SM-MITSUBISHI-017": "SM-KOLCAK-018",   # Transporter kolçak, Mitsubishi koduyla girilmiş
        "G-KASA-001": "SM-OPEL-021",
    }
    for k in kayitlar:
        if k["kod"] in ozel:
            notlar.append(f"{k['orijinal_kod']} -> {ozel[k['kod']]}")
            k["kod"] = ozel[k["kod"]]

    for k in kayitlar:
        if not k["kod"]:
            k["kod"] = "SM-TOYOTA-009"
            notlar.append(f"(kodsuz) {k['ad'][:40]} -> SM-TOYOTA-009")

    gorulen = {}
    for k in kayitlar:
        if k["kod"] in gorulen:
            onek = k["kod"].rsplit("-", 1)[0]
            n = 1
            mevcut = {x["kod"] for x in kayitlar}
            while f"{onek}-{n:03d}" in mevcut:
                n += 1
            yeni = f"{onek}-{n:03d}"
            notlar.append(f"Çakışan kod {k['orijinal_kod']} -> {yeni}")
            k["kod"] = yeni
        gorulen[k["kod"]] = True

    kayitlar.sort(key=lambda x: (x["kategori"], x["kod"]))
    with open(cikti, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["kod", "orijinal_kod", "ad", "kategori", "parca_tipi", "uyumluluk"])
        w.writeheader()
        w.writerows(kayitlar)

    print(len(kayitlar), "ürün yazıldı")
    for n in notlar:
        print("  ", n)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
