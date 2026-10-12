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
})();
