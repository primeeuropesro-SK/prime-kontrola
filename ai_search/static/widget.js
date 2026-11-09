/* Prime AI Search widget – embeds into an Upgates e-shop.
 *
 * <script src="https://VAS-SERVER/widget.js" defer
 *         data-lang="sk"                       (optional, default <html lang>)
 *         data-input="input[name='q']"        (optional CSS selector of the shop's search box)
 *         data-enter="ai"></script>            (ai = Enter runs AI search, native = keep shop search)
 */
(function () {
  "use strict";
  if (window.__primeAiSearch) return;
  window.__primeAiSearch = true;

  var script = document.currentScript || document.querySelector('script[src*="widget.js"]');
  var ds = (script && script.dataset) || {};
  var API = (ds.api || (script ? new URL(script.src).origin : "")).replace(/\/$/, "");
  var LANG = (ds.lang || document.documentElement.lang || "sk").slice(0, 2).toLowerCase();
  var SELECTOR = ds.input || 'input[name="q"], input[name="search"], input[name="fulltext"], input[type="search"]';
  var ENTER_MODE = ds.enter || "ai";

  var T = {
    sk: { ai: "Opýtať sa AI", aiHint: "Napíšte, čo potrebujete – napr. „zimné rukavice do 10 €“",
          thinking: "AI hľadá najvhodnejšie produkty…", all: "Zobraziť všetky výsledky", none: "Nič sme nenašli. Skúste to opísať inak alebo sa opýtajte AI.",
          inStock: "Skladom", outStock: "Na objednávku", from: "od ", fixed: "Zobrazujem výsledky pre:",
          sugg: "Hľadané výrazy", popular: "Populárne vyhľadávania", cats: "Kategórie", topCats: "Obľúbené kategórie",
          brands: "Značky", pages: "Informácie", products: "Produkty", tab: "Tab" },
    hu: { ai: "Kérdezd az AI-t", aiHint: "Írd le, mire van szükséged – pl. „téli kesztyű 3000 Ft alatt”",
          thinking: "Az AI keresi a legjobb termékeket…", all: "Összes találat", none: "Nincs találat. Próbáld másképp leírni, vagy kérdezd az AI-t.",
          inStock: "Raktáron", outStock: "Rendelésre", from: "", fixed: "Találatok erre:",
          sugg: "Keresési javaslatok", popular: "Népszerű keresések", cats: "Kategóriák", topCats: "Népszerű kategóriák",
          brands: "Márkák", pages: "Információk", products: "Termékek", tab: "Tab" }
  };
  var t = T[LANG] || T.sk;

  var css = "" +
    ".pas-panel{position:absolute;z-index:99999;background:#fff;color:#222;border:1px solid #ddd;border-radius:12px;" +
    "box-shadow:0 14px 36px rgba(0,0,0,.18);font:14px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;" +
    "max-height:80vh;overflow:auto;box-sizing:border-box;text-align:left}" +
    ".pas-panel *{box-sizing:border-box}" +
    ".pas-ai{display:flex;gap:10px;align-items:center;padding:10px 14px;border-bottom:1px solid #eee;background:#fafafa}" +
    ".pas-ai button{border:0;border-radius:999px;padding:7px 14px;font-weight:600;cursor:pointer;" +
    "background:linear-gradient(90deg,#f39200,#e4572e);color:#fff;white-space:nowrap}" +
    ".pas-ai span{color:#666;font-size:12px}" +
    ".pas-summary{padding:10px 14px;background:#fff8ec;border-bottom:1px solid #f3e2c2;font-weight:600}" +
    ".pas-fix{padding:8px 14px;font-size:13px;color:#555;border-bottom:1px solid #eee}.pas-fix b{color:#111}" +
    ".pas-cols{display:flex}.pas-left{flex:0 0 36%;border-right:1px solid #eee;padding:6px 0}.pas-right{flex:1;min-width:0}" +
    ".pas-h{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#888;padding:10px 14px 4px;font-weight:600}" +
    ".pas-s{display:flex;align-items:center;gap:8px;padding:6px 14px;color:#333;text-decoration:none;cursor:pointer}" +
    ".pas-s:hover,.pas-s.pas-active{background:#f6f8fb}" +
    ".pas-s .pas-ic{color:#aaa;flex:none;width:14px;text-align:center}" +
    ".pas-s b{font-weight:700;color:#111}.pas-s .pas-k{margin-left:auto;font-size:10px;color:#aaa;border:1px solid #ddd;border-radius:4px;padding:0 4px}" +
    ".pas-item{display:flex;gap:12px;padding:8px 14px;text-decoration:none;color:inherit;border-bottom:1px solid #f3f3f3}" +
    ".pas-item:hover,.pas-item.pas-active{background:#f6f8fb}" +
    ".pas-item img{width:56px;height:56px;object-fit:contain;flex:none;background:#fff}" +
    ".pas-item .pas-t{font-weight:500}.pas-item .pas-t b{font-weight:700}" +
    ".pas-item .pas-r{color:#2f7d32;font-size:12px;margin-top:2px}" +
    ".pas-item .pas-m{display:flex;gap:10px;font-size:12px;color:#777;margin-top:2px}" +
    ".pas-item .pas-p{margin-left:auto;font-weight:700;color:#111;white-space:nowrap;align-self:center}" +
    ".pas-ok{color:#2f7d32}.pas-no{color:#b26a00}" +
    ".pas-foot{display:block;padding:10px 14px;text-align:center;color:#e4572e;font-weight:600;cursor:pointer;text-decoration:none}" +
    ".pas-msg{padding:16px 14px;color:#666}" +
    ".pas-spin{display:inline-block;width:14px;height:14px;border:2px solid #f39200;border-right-color:transparent;" +
    "border-radius:50%;animation:pasr .7s linear infinite;vertical-align:-2px;margin-right:8px}" +
    "@keyframes pasr{to{transform:rotate(360deg)}}" +
    ".pas-narrow .pas-cols{display:block}.pas-narrow .pas-left{border-right:0;border-bottom:1px solid #eee}";
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fold(s) { return String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, ""); }
  function money(v, cur) {
    if (v == null) return "";
    try { return new Intl.NumberFormat(LANG, { style: "currency", currency: cur || "EUR", maximumFractionDigits: cur === "HUF" ? 0 : 2 }).format(v); }
    catch (e) { return v + " " + (cur || ""); }
  }
  function debounce(fn, ms) {
    var h; return function () { var a = arguments, s = this; clearTimeout(h); h = setTimeout(function () { fn.apply(s, a); }, ms); };
  }
  // Bold the words of `text` that match what the customer typed (diacritics-insensitive).
  function highlight(text, query) {
    var qs = fold(query).split(/[^a-z0-9]+/).filter(function (w) { return w.length >= 2; });
    if (!qs.length) return esc(text);
    return String(text).split(/(\s+)/).map(function (w) {
      var fw = fold(w).replace(/[^a-z0-9]/g, "");
      var hit = fw && qs.some(function (q) { return fw.indexOf(q.slice(0, Math.max(2, q.length - 2))) === 0; });
      return hit ? "<b>" + esc(w) + "</b>" : esc(w);
    }).join("");
  }
  // Suggestion: typed words normal, the completion in bold (like Google / Luigi's Box).
  function suggestionHtml(s, query) {
    var typed = fold(query).split(/[^a-z0-9]+/).filter(Boolean);
    return s.split(" ").map(function (w) {
      var fw = fold(w);
      var isTyped = typed.some(function (q) {
        return fw === q || (q.length >= 4 && fw.indexOf(q.slice(0, q.length - 1)) === 0 && Math.abs(fw.length - q.length) <= 2);
      });
      return isTyped ? esc(w) : "<b>" + esc(w) + "</b>";
    }).join(" ");
  }
  function track(q) {
    if (!q) return;
    try { fetch(API + "/api/track?lang=" + encodeURIComponent(LANG) + "&q=" + encodeURIComponent(q), { keepalive: true, credentials: "omit" }); }
    catch (e) { /* ignore */ }
  }

  function attach(input) {
    if (input.__pas) return;
    input.__pas = true;
    input.setAttribute("autocomplete", "off");
    var panel = document.createElement("div");
    panel.className = "pas-panel";
    panel.style.display = "none";
    panel.setAttribute("role", "listbox");
    document.body.appendChild(panel);
    var seq = 0, active = -1, lastQuery = null, lastData = null;

    function place() {
      var r = input.getBoundingClientRect();
      var vw = document.documentElement.clientWidth;
      var width = Math.min(Math.max(r.width, 820), vw - 16);
      var left = Math.min(Math.max(8, r.left), vw - width - 8);
      panel.style.top = (r.bottom + window.scrollY + 6) + "px";
      panel.style.left = (left + window.scrollX) + "px";
      panel.style.width = width + "px";
      panel.classList.toggle("pas-narrow", width < 640);
    }
    function show(html) { place(); panel.innerHTML = html; panel.style.display = "block"; active = -1; }
    function hide() { panel.style.display = "none"; }

    function sItem(icon, html, attrs, kbd) {
      return '<a class="pas-s pas-nav" ' + attrs + '><span class="pas-ic">' + icon + "</span><span>" + html + "</span>" +
        (kbd ? '<span class="pas-k">' + kbd + "</span>" : "") + "</a>";
    }
    function linkOrQuery(name, url) {
      return url ? 'href="' + esc(url) + '"' : 'data-pas-q="' + esc(name) + '"';
    }
    function productHtml(p, query) {
      var price = (p.price_max && p.price_max > p.price ? t.from : "") + money(p.price, p.currency);
      return '<a class="pas-item pas-nav" role="option" href="' + esc(p.url) + '" data-pas-track>' +
        (p.image ? '<img loading="lazy" alt="" src="' + esc(p.image) + '">' : "") +
        '<div><div class="pas-t">' + highlight(p.title, query) + "</div>" +
        (p.reason ? '<div class="pas-r">✔ ' + esc(p.reason) + "</div>" : "") +
        '<div class="pas-m"><span class="' + (p.in_stock ? "pas-ok" : "pas-no") + '">' +
        esc(p.in_stock ? (p.availability || t.inStock) : t.outStock) + "</span>" +
        (p.manufacturer ? "<span>" + esc(p.manufacturer) + "</span>" : "") + "</div></div>" +
        '<div class="pas-p">' + esc(price) + "</div></a>";
    }

    function renderEmpty(data) {
      var h = "";
      if (data.popular && data.popular.length) {
        h += '<div class="pas-h">' + esc(t.popular) + "</div>" +
          data.popular.map(function (q) { return sItem("↗", esc(q), 'data-pas-q="' + esc(q) + '"'); }).join("");
      }
      if (data.categories && data.categories.length) {
        h += '<div class="pas-h">' + esc(t.topCats) + "</div>" +
          data.categories.map(function (c) { return sItem("▸", esc(c.name), linkOrQuery(c.name, c.url)); }).join("");
      }
      if (h) show('<div style="padding:4px 0">' + h + "</div>"); else hide();
    }

    function render(data, isAi) {
      lastData = data;
      var q = data.query || "";
      var h = "";
      if (!isAi) {
        h += '<div class="pas-ai"><button type="button" data-pas-ai>✨ ' + esc(t.ai) + "</button><span>" + esc(t.aiHint) + "</span></div>";
      } else if (data.ai && data.ai.summary) {
        h += '<div class="pas-summary">✨ ' + esc(data.ai.summary) + "</div>";
      }
      var fixes = data.corrections ? Object.keys(data.corrections) : [];
      if (fixes.length) {
        var fixedQuery = q.split(/\s+/).map(function (w) { return data.corrections[fold(w)] || w; }).join(" ");
        h += '<div class="pas-fix">' + esc(t.fixed) + " <b>" + esc(fixedQuery) + "</b></div>";
      }

      var left = "";
      if (!isAi) {
        var sug = data.suggestions || [];
        if (sug.length) {
          left += '<div class="pas-h">' + esc(t.sugg) + "</div>" + sug.map(function (s, i) {
            return sItem("⌕", suggestionHtml(s, q), 'data-pas-q="' + esc(s) + '"', i === 0 ? t.tab : "");
          }).join("");
        }
        if (data.categories && data.categories.length) {
          left += '<div class="pas-h">' + esc(t.cats) + "</div>" + data.categories.map(function (c) {
            return sItem("▸", highlight(c.name, q), linkOrQuery(c.name, c.url));
          }).join("");
        }
        if (data.brands && data.brands.length) {
          left += '<div class="pas-h">' + esc(t.brands) + "</div>" + data.brands.map(function (b) {
            return sItem("★", highlight(b.name, q), linkOrQuery(b.name, b.url));
          }).join("");
        }
        if (data.pages && data.pages.length) {
          left += '<div class="pas-h">' + esc(t.pages) + "</div>" + data.pages.map(function (p) {
            return sItem("ℹ", highlight(p.title, q), 'href="' + esc(p.url) + '"');
          }).join("");
        }
      }

      var right = "";
      if (!data.products || !data.products.length) {
        right += '<div class="pas-msg">' + esc(t.none) + "</div>";
      } else {
        if (left) right += '<div class="pas-h">' + esc(t.products) + "</div>";
        right += data.products.map(function (p) { return productHtml(p, q); }).join("");
      }
      if (input.form && data.total) right += '<a class="pas-foot pas-nav" data-pas-all>' + esc(t.all) + " (" + data.total + ") →</a>";

      h += left ? '<div class="pas-cols"><div class="pas-left">' + left + '</div><div class="pas-right">' + right + "</div></div>" : right;
      show(h);
    }

    function search(q, ai) {
      var my = ++seq;
      if (ai) show('<div class="pas-msg"><span class="pas-spin"></span>' + esc(t.thinking) + "</div>");
      var url = API + "/api/search?lang=" + encodeURIComponent(LANG) + "&limit=" + (ai ? 10 : 6) +
        "&ai=" + (ai ? 1 : 0) + "&q=" + encodeURIComponent(q);
      fetch(url, { credentials: "omit" }).then(function (r) { return r.json(); }).then(function (data) {
        if (my !== seq) return; // a newer query is already running
        if (!q) renderEmpty(data); else render(data, ai);
      }).catch(function () { if (my === seq && ai) hide(); });
    }

    function applyQuery(q) {
      input.value = q;
      lastQuery = q;
      track(q);
      search(q, false);
      input.focus();
    }

    var instant = debounce(function () {
      var q = input.value;
      if (q === lastQuery) return;
      lastQuery = q;
      if (!q.trim()) { search("", false); return; }
      if (q.trim().length < 2) { seq++; return hide(); }
      search(q, false);
    }, 120);

    input.addEventListener("input", instant);
    input.addEventListener("focus", function () {
      if (panel.innerHTML && panel.style.display === "none" && input.value.trim().length >= 2) { place(); panel.style.display = "block"; }
      else if (!input.value.trim()) search("", false);
    });
    input.addEventListener("keydown", function (e) {
      var items = panel.querySelectorAll(".pas-nav");
      var open = panel.style.display !== "none";
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && open && items.length) {
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach(function (el, i) { el.classList.toggle("pas-active", i === active); });
        items[active].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Tab" && open && !e.shiftKey && lastData && lastData.suggestions && lastData.suggestions.length &&
                 input.selectionStart === input.value.length) {
        e.preventDefault();
        applyQuery(lastData.suggestions[0] + " ");
      } else if (e.key === "Enter") {
        if (active >= 0 && items[active]) { e.preventDefault(); items[active].click(); return; }
        var q = input.value.trim();
        if (ENTER_MODE === "ai" && q.length >= 3) { e.preventDefault(); track(q); search(q, true); }
      } else if (e.key === "Escape") { hide(); }
    });
    panel.addEventListener("mousedown", function (e) { e.preventDefault(); }); // keep focus in the input
    panel.addEventListener("click", function (e) {
      var el;
      if ((el = e.target.closest("[data-pas-ai]"))) { e.preventDefault(); track(input.value.trim()); search(input.value.trim(), true); input.focus(); return; }
      if ((el = e.target.closest("[data-pas-q]"))) { e.preventDefault(); applyQuery(el.getAttribute("data-pas-q")); return; }
      if ((el = e.target.closest("[data-pas-all]"))) {
        e.preventDefault();
        track(input.value.trim());
        hide();
        if (input.form.requestSubmit) input.form.requestSubmit(); else input.form.submit();
        return;
      }
      if ((el = e.target.closest("[data-pas-track]"))) { track(input.value.trim()); }
    });
    document.addEventListener("click", function (e) { if (e.target !== input && !panel.contains(e.target)) hide(); });
    window.addEventListener("resize", function () { if (panel.style.display !== "none") place(); });
  }

  function init() { document.querySelectorAll(SELECTOR).forEach(attach); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
  // Upgates templates can render the search box lazily (mobile menu) – watch for it.
  new MutationObserver(debounce(init, 300)).observe(document.documentElement, { childList: true, subtree: true });
})();
