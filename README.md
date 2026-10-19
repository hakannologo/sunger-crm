# Sünger Merkezi — Müşteri Takip Programı

Flask + SQLite ile yazılmış, cPanel'de "Setup Python App" ile çalışan müşteri takip programı.
Tek dış bağımlılık Flask'tır; veritabanı için ayrı bir sunucu gerekmez.

## Şu an neler var (1. aşama)

- İlk açılışta yönetici hesabı oluşturma ekranı
- Giriş / çıkış, şifre değiştirme, 5 hatalı denemede 10 dakika kilit
- **Kullanıcılar** (yönetici): ekleme, düzenleme, pasife alma, şifre sıfırlama
- **Ürünler**: 356 ürün hazır yüklü; marka → model seçerek veya arayarak ürün bulma
- **Ürün kartı**: perakende/toptan fiyat, uyumlu araçlar (yönetici araç ekleyip çıkarabilir)
- **Toplu fiyat girişi** (yönetici): kategori/parça tipine göre listeleyip tabloya fiyat yazma,
  "Hızlı doldur" ile aynı fiyatı birçok ürüne verme, toptanı perakendeden yüzde ile hesaplama
- **Marka / model** (yönetici): 30 marka, 108 model hazır; ekleme, yeniden adlandırma, silme
- **İşlem kaydı** (yönetici): kim, ne zaman, neyi değiştirdi

## 2. aşama

- **Talepler:** arayan/yazan kişinin kanalı (telefon, WhatsApp, Instagram, Facebook), aracı, istediği ürünler
  ve verilen fiyat; aynı numara daha önce sorduysa geçmişi gösterilir
- **Hatırlatma:** "Fiyat verildi" talepler ertesi gün ana sayfada "Bugün dönüş yapılacaklar"a düşer
  (talebi giren kullanıcıda; yönetici hepsini görür), not + yeni tarih ile takip edilir
- **Satışa çevirme:** tek tuşla; müşteri kaydı kendiliğinden oluşur; ödeme şekli, Aras Kargo takip no
- **Satışlar** (hazırlanıyor → kargoda → teslim / iade), **Müşteriler** (kart, WhatsApp, geçmiş)
- **Talep raporu** (yönetici): kanal ve kullanıcı bazında talep, satış, dönüş oranı, olmama sebepleri

## 3. aşama

- **Tahsilat:** nakit/kart/havale satışta otomatik tahsil edilir; kapıda ödemede para teslimden 3 gün sonra
  Aras'tan beklenir ("Para geldi" ile kapanır); parçalı tahsilat girilebilir
- **Vadeli (cari hesap):** toptan müşteriye vade günü (varsayılan 30); müşteri kartında bakiye, hesap ekstresi,
  tahsilat (en eski borçtan başlayarak satışlara dağıtılır, fazlası hesaba yazılır)
- **Alacaklar** sayfası ve aylık **alacak takvimi**; ana sayfada beklenen / geciken / bugünkü tutarlar
- **Excel'e aktarma** (yönetici): satışlar, müşteriler, alacaklar

## 4. ek: pazaryeri siparişleri

- Kanallar: **Trendyol, Hepsiburada, N11**. Bunlarda telefon zorunlu değil, **sipariş no** girilir; her sipariş ayrı
  müşteri olur, eski kayıtlarla eşleştirme/otomatik doldurma yapılmaz. Kayıttan sonra doğrudan satış ekranı açılır.
- Ödeme şekli **Pazaryeri**: alacaklarda ayrı bölüm; beklenen tarih isteğe bağlı (girilirse takvimde görünür), "Para geldi".
- Satışta **kargo firması** seçilir (Aras, Trendyol Express, HepsiJet, Yurtiçi, MNG, PTT, Sürat, Diğer).
- 00000000000 gibi tek rakamdan oluşan numaralar kabul edilmez; daha önce böyle girilip tek müşteride birleşmiş
  satışlar güncellemede otomatik olarak ayrı müşterilere ayrılır.

## cPanel'e kurulum — CGI yöntemi (önerilen)

Bu sunucuda Setup Python App yerine Günaydın CRM ile aynı CGI yöntemi kullanılır:

1. `python3 kurulum/paketle.py <python3.11 packages klasörü> sunger-crm-kurulum.zip`
2. Zip'i alan adının belge kök dizinine (ör. `crm.koltuksungeri.com/`) yükleyip açın.
3. `cgi-bin/app.cgi` izni 0755 olmalı.
4. Veriler belge kökünün yanındaki `crm-veri/` klasöründe tutulur (internetten erişilemez).

## cPanel'e kurulum — Setup Python App yöntemi (alternatif)

1. **Alt alan adı:** cPanel → *Domains* → yeni alt alan adı (ör. `crm.sungermerkezi.com`).
   SSL'in açık olduğundan emin olun (*SSL/TLS Status* → AutoSSL).
2. **Depoyu sunucuya çekin:** cPanel → *Git™ Version Control* → *Create*
   - *Clone a Repository*: açık
   - *Clone URL*: `https://github.com/hakannologo/sunger-crm.git`
     (depo gizli olduğu için GitHub kullanıcı adı ve bir erişim anahtarı istenebilir; adım adım birlikte yaparız)
   - *Repository Path*: ör. `sunger-crm`
3. **Python uygulaması:** cPanel → *Setup Python App* → *Create Application*
   - *Python version*: 3.9 veya üstü
   - *Application root*: 2. adımdaki klasör (ör. `sunger-crm`)
   - *Application URL*: 1. adımdaki alt alan adı
   - *Application startup file*: `passenger_wsgi.py`
   - *Application Entry point*: `application`
   - Kaydettikten sonra aynı sayfada *Configuration files* kısmına `requirements.txt` yazıp
     *Run Pip Install* deyin.
   - İsteğe bağlı *Environment variables*: `FIRMA_ADI` (ekranda görünen ad, varsayılan "Sünger Merkezi")
4. **Restart** deyin, alt alan adını tarayıcıda açın. İlk ekran yönetici hesabını oluşturmanızı ister.

## Güncelleme (her yeni sürümde)

cPanel → *Git™ Version Control* → depo → *Manage* → *Pull or Deploy* sekmesi:

1. **Update from Remote** — GitHub'daki son kodu sunucuya çeker.
2. **Deploy HEAD Commit** — uygulamayı yeniden başlatır (`.cpanel.yml`).

Veritabanı tablo değişiklikleri uygulama açılırken otomatik uygulanır; mevcut veriler korunur.

## Veriler nerede?

- Veritabanı: `veri/crm.sqlite3` (proje klasöründe; GitHub'a **gönderilmez**)
- Oturum anahtarı: `veri/gizli_anahtar` (ilk açılışta kendiliğinden oluşur)
- Farklı bir klasör kullanmak için `VERI_KLASORU` ortam değişkenini verin.

**Yedek:** `veri/crm.sqlite3` dosyasını düzenli olarak indirin (cPanel *File Manager* veya
*Backup*). Tüm müşteri ve satış verileri bu tek dosyadadır.

## Şifre unutulursa

cPanel → *File Manager* → `crm-veri/` klasöründe `sifre_sifirla.txt` adında bir dosya oluşturun ve içine
yalnızca yeni şifreyi yazın (ilk yönetici hesabı için) ya da `kullaniciadi yenisifre` yazın.
Siteyi bir kez açtığınızda şifre değişir, dosya kendiliğinden silinir ve sonuç
`crm-veri/sifre_sifirlama_sonucu.txt` dosyasına yazılır (kullanıcı adı da orada görünür).

## Geliştirme

```bash
pip install -r requirements.txt
VERI_KLASORU=./veri HTTPS_KAPALI=1 flask --app "app:create_app()" run --debug
python3 -m unittest discover tests
```

`HTTPS_KAPALI=1` sadece kendi bilgisayarınızda (http üzerinden) denemek içindir; sunucuda kullanmayın.

`araclar/pdf_urun_listesi.py`, web sitesinden alınan ürün listesi PDF'ini temizleyip
`app/data/urunler.csv` dosyasına çeviren betiktir. Bu CSV yalnızca ilk kurulumda yüklenir.
