(function () {
  "use strict";

  // Mobil menü
  document.querySelectorAll("[data-menu-ac]").forEach(function (b) {
    b.addEventListener("click", function () { document.body.classList.add("menu-acik"); });
  });
  document.querySelectorAll("[data-menu-kapat]").forEach(function (b) {
    b.addEventListener("click", function () { document.body.classList.remove("menu-acik"); });
  });

  // Onay isteyen formlar (silme vb.)
  document.querySelectorAll("form[data-onay]").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      if (!window.confirm(f.getAttribute("data-onay"))) e.preventDefault();
    });
  });

  // Tıklanabilir tablo satırları (bağlantı/düğme/girdi tıklamalarını bozmadan)
  document.querySelectorAll("tr[data-href]").forEach(function (tr) {
    tr.addEventListener("click", function (e) {
      if (e.target.closest("a, button, input, select, label")) return;
      window.location = tr.getAttribute("data-href");
    });
  });

  // Marka seçilince modelleri getir
  var modelMeta = document.querySelector('meta[name="model-api"]');
  var modelUrl = modelMeta ? modelMeta.content : "urunler/api/modeller";
  document.querySelectorAll("select[data-model-hedef]").forEach(function (markaSec) {
    var hedef = document.getElementById(markaSec.getAttribute("data-model-hedef"));
    if (!hedef) return;
    var bosEtiket = hedef.getAttribute("data-bos-etiket") || "Tüm modeller";
    markaSec.addEventListener("change", function () {
      var deger = markaSec.value;
      hedef.innerHTML = "";
      if (!/^\d+$/.test(deger)) {
        hedef.add(new Option(deger === "genel" ? "—" : "Önce marka seçin", ""));
        hedef.disabled = true;
        return;
      }
      hedef.add(new Option("Yükleniyor…", ""));
      hedef.disabled = true;
      fetch(modelUrl + "?marka_id=" + encodeURIComponent(deger), { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (liste) {
          hedef.innerHTML = "";
          hedef.add(new Option(bosEtiket, ""));
          liste.forEach(function (m) { hedef.add(new Option(m.ad, m.id)); });
          hedef.disabled = false;
          hedef.dispatchEvent(new Event("change", { bubbles: true }));
        })
        .catch(function () {
          hedef.innerHTML = "";
          hedef.add(new Option("Modeller alınamadı", ""));
        });
    });
  });

  // ---------- Toplu fiyat ----------
  function tlOku(metin) {
    var s = String(metin || "").replace(/[₺\s]|TL/gi, "");
    if (!s) return null;
    if (s.indexOf(",") > -1 && s.indexOf(".") > -1) s = s.replace(/\./g, "").replace(",", ".");
    else if (s.indexOf(",") > -1) s = s.replace(",", ".");
    else if (/^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, "");
    if (!/^\d+(\.\d{1,2})?$/.test(s)) return NaN;
    return Math.round(parseFloat(s) * 100);
  }
  function tlYaz(kurus) {
    return Math.floor(kurus / 100) + "," + String(kurus % 100).padStart(2, "0");
  }

  var form = document.querySelector("form[data-degisiklik-uyarisi]");
  if (form) {
    var degisti = false;
    form.addEventListener("input", function (e) {
      if (e.target.matches("input.tutar-girdi")) {
        degisti = true;
        e.target.closest("tr").classList.add("degisti");
      }
    });
    form.addEventListener("submit", function () { degisti = false; });
    window.addEventListener("beforeunload", function (e) {
      if (degisti) { e.preventDefault(); e.returnValue = ""; }
    });

    var dugme = document.querySelector("[data-doldur]");
    if (dugme) {
      dugme.addEventListener("click", function () {
        var tip = document.getElementById("h-tip").value;
        var p = tlOku(document.getElementById("h-p").value);
        var t = tlOku(document.getElementById("h-t").value);
        var yuzdeMetin = document.getElementById("h-yuzde").value.replace(",", ".").trim();
        var yuzde = yuzdeMetin ? parseFloat(yuzdeMetin) : null;
        var sadeceBos = document.getElementById("h-bos").checked;
        if (Number.isNaN(p) || Number.isNaN(t) || (yuzde !== null && (isNaN(yuzde) || yuzde < 0 || yuzde >= 100))) {
          window.alert("Tutarları 1250 veya 1.250,50 gibi, yüzdeyi 0-99 arası yazın.");
          return;
        }
        if (p === null && t === null && yuzde === null) {
          window.alert("Perakende, toptan veya yüzde alanlarından en az birini doldurun.");
          return;
        }
        var sayac = 0;
        form.querySelectorAll("tbody tr").forEach(function (tr) {
          if (tip && tr.getAttribute("data-tip") !== tip) return;
          var pg = tr.querySelector("[data-perakende]");
          var tg = tr.querySelector("[data-toptan]");
          var oldu = false;
          if (p !== null && (!sadeceBos || !pg.value.trim())) { pg.value = tlYaz(p); oldu = true; }
          if (t !== null && (!sadeceBos || !tg.value.trim())) { tg.value = tlYaz(t); oldu = true; }
          if (t === null && yuzde !== null && (!sadeceBos || !tg.value.trim())) {
            var mevcutP = tlOku(pg.value);
            if (mevcutP && !Number.isNaN(mevcutP)) {
              tg.value = tlYaz(Math.round(mevcutP * (100 - yuzde) / 100));
              oldu = true;
            }
          }
          if (oldu) { tr.classList.add("degisti"); sayac++; }
        });
        degisti = degisti || sayac > 0;
        var sonuc = document.querySelector("[data-doldur-sonuc]");
        if (sonuc) {
          sonuc.textContent = sayac
            ? sayac + " satır dolduruldu. Kontrol edip en alttaki “Kaydet”e basın."
            : "Doldurulacak satır bulunamadı (seçili parça tipinde boş alan yok).";
        }
      });
    }
  }

  // ---------- Durum seçimi: hatırlatma / olmama sebebi alanları ----------
  document.querySelectorAll("select[data-durum-sec]").forEach(function (sec) {
    var kap = sec.closest("form");
    function guncelle() {
      var olmadi = sec.value === "olmadi";
      kap.querySelectorAll("[data-acik-alan]").forEach(function (e) { e.hidden = olmadi; });
      kap.querySelectorAll("[data-kayip-alan]").forEach(function (e) { e.hidden = !olmadi; });
    }
    sec.addEventListener("change", guncelle);
    guncelle();
  });

  // ---------- Talep formu ----------
  var tf = document.getElementById("talep-form");
  if (tf) {
    var urunApi = tf.getAttribute("data-urun-api");
    var kisiApi = tf.getAttribute("data-kisi-api");
    var talepId = tf.getAttribute("data-talep-id");
    var govde = document.getElementById("kalemler");
    var sablon = document.getElementById("kalem-sablon");
    var oneriler = document.getElementById("urun-oneriler");
    var araKutu = document.getElementById("urun-ara");
    var markaSec = document.getElementById("a-marka");
    var modelSec = document.getElementById("a-model");
    var fiyatTipi = document.getElementById("a-fiyat_tipi");
    var sonUrunler = [];

    function yazTL(kurus) {
      var tam = Math.floor(kurus / 100).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
      return tam + "," + String(kurus % 100).padStart(2, "0") + " ₺";
    }
    function toplamHesapla() {
      var toplam = 0;
      govde.querySelectorAll("tr").forEach(function (tr) {
        var adet = parseInt(tr.querySelector(".kalem-adet").value, 10) || 0;
        var f = tlOku(tr.querySelector(".kalem-fiyat").value);
        var tutar = (f && !Number.isNaN(f)) ? adet * f : 0;
        toplam += tutar;
        tr.querySelector(".kalem-tutar").textContent = yazTL(tutar);
      });
      document.getElementById("genel-toplam").textContent = yazTL(toplam);
    }
    function kalemEkle(urun) {
      var satir = sablon.content.firstElementChild.cloneNode(true);
      if (urun) {
        satir.querySelector("[name=k_urun_id]").value = urun.id;
        satir.querySelector(".kalem-ad").value = urun.ad;
        var f = fiyatTipi.value === "toptan" ? urun.toptan : urun.perakende;
        if (f != null) satir.querySelector(".kalem-fiyat").value = tlYaz(f);
      }
      govde.appendChild(satir);
      toplamHesapla();
      if (!urun) satir.querySelector(".kalem-ad").focus();
      else if (!satir.querySelector(".kalem-fiyat").value) satir.querySelector(".kalem-fiyat").focus();
    }
    govde.addEventListener("input", toplamHesapla);
    govde.addEventListener("click", function (e) {
      if (e.target.matches("[data-kalem-sil]")) { e.target.closest("tr").remove(); toplamHesapla(); }
    });
    document.getElementById("elle-ekle").addEventListener("click", function () { kalemEkle(null); });
    fiyatTipi.addEventListener("change", function () {
      // Listeden gelen ürünlerin fiyatını yeni tipe göre güncelle
      govde.querySelectorAll("tr").forEach(function (tr) {
        var id = tr.querySelector("[name=k_urun_id]").value;
        var u = sonUrunler.filter(function (x) { return String(x.id) === id; })[0];
        if (u) {
          var f = fiyatTipi.value === "toptan" ? u.toptan : u.perakende;
          if (f != null) tr.querySelector(".kalem-fiyat").value = tlYaz(f);
        }
      });
      toplamHesapla();
      urunleriGoster(sonUrunler);
    });

    function urunleriGoster(liste) {
      oneriler.innerHTML = "";
      if (!liste.length) {
        oneriler.innerHTML = '<p class="soluk kucuk">Uygun ürün bulunamadı. Aramayı değiştirin ya da “Listede olmayan ürün ekle”yi kullanın.</p>';
        return;
      }
      liste.forEach(function (u) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "oneri";
        var f = fiyatTipi.value === "toptan" ? u.toptan : u.perakende;
        b.innerHTML = '<span class="oneri-tip"></span><span class="oneri-ad"></span><span class="oneri-fiyat"></span>';
        b.querySelector(".oneri-tip").textContent = u.tip;
        b.querySelector(".oneri-ad").textContent = u.ad;
        b.querySelector(".oneri-fiyat").textContent = f != null ? yazTL(f) : "fiyat yok";
        b.addEventListener("click", function () { kalemEkle(u); b.classList.add("eklendi"); });
        oneriler.appendChild(b);
      });
    }
    var sayac = 0;
    function urunleriGetir() {
      var q = araKutu.value.trim();
      var marka = markaSec.value, model = modelSec.value;
      if (!q && !marka) {
        oneriler.innerHTML = '<p class="soluk kucuk">Araç seçince uyumlu ürünler burada listelenir. Tıklayınca talebe eklenir.</p>';
        return;
      }
      var no = ++sayac;
      var url = urunApi + "?marka=" + encodeURIComponent(marka) + "&model=" + encodeURIComponent(model) +
        "&q=" + encodeURIComponent(q);
      fetch(url, { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(function (liste) {
        if (no !== sayac) return;
        sonUrunler = sonUrunler.concat(liste.filter(function (u) {
          return !sonUrunler.some(function (x) { return x.id === u.id; });
        }));
        urunleriGoster(liste);
      });
    }
    var araZaman;
    araKutu.addEventListener("input", function () { clearTimeout(araZaman); araZaman = setTimeout(urunleriGetir, 250); });
    araKutu.addEventListener("keydown", function (e) { if (e.key === "Enter") e.preventDefault(); });
    markaSec.addEventListener("change", urunleriGetir);
    modelSec.addEventListener("change", urunleriGetir);
    if (markaSec.value) urunleriGetir();
    toplamHesapla();

    // Telefon yazılınca önceki talepleri göster
    var telKutu = document.getElementById("a-telefon");
    var gecmisKutu = document.getElementById("kisi-gecmis");
    var telZaman;
    var pazaryerleri = (tf.getAttribute("data-pazaryerleri") || "").split(" ");
    function seciliKanal() {
      var k = tf.querySelector("input[name=kanal]:checked");
      return k ? k.value : "";
    }
    function pazaryeriMi() { return pazaryerleri.indexOf(seciliKanal()) >= 0; }
    function kanalaGoreGoster() {
      var p = pazaryeriMi();
      tf.querySelectorAll("[data-pazaryeri-alan]").forEach(function (el) { el.hidden = !p; });
      if (p) gecmisKutu.hidden = true;
    }
    tf.querySelectorAll("input[name=kanal]").forEach(function (r) {
      r.addEventListener("change", function () { kanalaGoreGoster(); kisiSorgula(); });
    });
    function kisiSorgula() {
      var rakam = telKutu.value.replace(/\D/g, "");
      // Pazaryeri siparişinde ve 00000000000 gibi sahte numaralarda eski kayıt aranmaz / ad doldurulmaz
      if (rakam.length < 10 || pazaryeriMi() || /^(\d)\1+$/.test(rakam)) { gecmisKutu.hidden = true; return; }
      fetch(kisiApi + "?tel=" + encodeURIComponent(telKutu.value) + "&kanal=" + encodeURIComponent(seciliKanal()) +
            (talepId ? "&haric=" + talepId : ""),
            { credentials: "same-origin" })
        .then(function (r) { return r.json(); })
        .then(function (v) {
          if (!v.musteri && !v.talepler.length) { gecmisKutu.hidden = true; return; }
          gecmisKutu.innerHTML = "";
          var bas = document.createElement("strong");
          bas.textContent = v.musteri
            ? "Kayıtlı müşteri: " + v.musteri.ad + (v.musteri.tip === "toptan" ? " (toptan)" : "")
            : "Bu numara daha önce sormuş:";
          gecmisKutu.appendChild(bas);
          var ul = document.createElement("ul");
          v.talepler.forEach(function (t) {
            var li = document.createElement("li");
            var a = document.createElement("a");
            a.href = t.url; a.target = "_blank"; a.textContent = t.tarih.split("-").reverse().join(".");
            li.appendChild(a);
            li.appendChild(document.createTextNode(" — " + [t.arac, t.urunler].filter(Boolean).join(" · ") +
              " — " + t.toplam + " (" + t.durum + ")"));
            ul.appendChild(li);
          });
          gecmisKutu.appendChild(ul);
          gecmisKutu.hidden = false;
          var adKutu = document.getElementById("a-ad");
          if (!adKutu.value) {
            var eskiAd = v.musteri ? v.musteri.ad : (v.talepler.filter(function (t) { return t.ad; })[0] || {}).ad;
            if (eskiAd) adKutu.value = eskiAd;
          }
          if (v.musteri && v.musteri.tip === "toptan" && fiyatTipi.value !== "toptan") {
            fiyatTipi.value = "toptan";
            fiyatTipi.dispatchEvent(new Event("change"));
          }
        });
    }
    telKutu.addEventListener("input", function () { clearTimeout(telZaman); telZaman = setTimeout(kisiSorgula, 400); });
    if (telKutu.value) kisiSorgula();
  }
})();
