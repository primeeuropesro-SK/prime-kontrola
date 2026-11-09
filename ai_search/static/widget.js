/* Prime AI Search widget – embeds into an Upgates e-shop.
 *
 * <script src="https://VAS-SERVER/widget.js" defer
 *         data-lang="sk"                       (optional, default <html lang>)
 *         data-input="input[name='q']"        (optional CSS selector of the shop's search box)
 *         data-enter="ai"                      (ai = Enter runs AI search, native = keep shop search)
 *         data-placeholder="..."></script>     (optional text in the phone's full-screen search box)
 *
 * Desktop: a two-column suggestion panel under the shop's search box.
 * Phone (<= 640 px): tapping the search box opens a full-screen search; ✕ or the phone's
 * Back button closes it and returns the customer exactly where they were.
 */
(function () {
  "use strict";
  if (window.__primeAiSearch) return;
  window.__primeAiSearch = true;

  var script = document.currentScript || document.querySelector('script[src*="widget.js"]');
  var ds = (script && script.dataset) || {};
  var API = (ds.api || (script ? new URL(script.src).origin : "")).replace(/\/$/, "");
  // The page's own language (Upgates sets <html lang="sk"> / "hu") wins, so one shared script
  // works for every language version; data-lang is only a fallback.
  var PAGE_LANG = (document.documentElement.lang || "").slice(0, 2).toLowerCase();
  var LANG = (/^(sk|hu|cs)$/.test(PAGE_LANG) ? PAGE_LANG : (ds.lang || "sk")).slice(0, 2).toLowerCase();
  var SELECTOR = ds.input || 'input[name="q"], input[name="search"], input[name="fulltext"], input[type="search"]';
  var ENTER_MODE = ds.enter || "ai";
  var TOUCH = window.matchMedia && window.matchMedia("(hover: none)").matches;
  function isPhone() { return window.matchMedia ? window.matchMedia("(max-width: 640px)").matches : window.innerWidth <= 640; }

  var T = {
    sk: { ai: "Opýtať sa AI", aiHint: "Napíšte vlastnými slovami, čo potrebujete",
          thinking: "AI hľadá najvhodnejšie produkty…",
          steps: ["Rozumiem, čo hľadáte…", "Prehľadávam celý katalóg…", "Vyberám najvhodnejšie produkty…", "Ešte chvíľku…"],
          aiSlow: "AI teraz neodpovedá, zobrazujem bežné výsledky.",
          helped: "Pomohlo vám to?", thanks: "Ďakujeme za hodnotenie!", all: "Zobraziť všetky výsledky", none: "Nič sme nenašli. Skúste to opísať inak alebo sa opýtajte AI.",
          inStock: "Skladom", outStock: "Na objednávku", from: "od ", fixed: "Výsledky pre:",
          fav: "Pridať do obľúbených", cmp: "Pridať do porovnania", favDone: "Pridané do obľúbených",
          cmpDone: "Pridané do porovnania", actFail: "Nepodarilo sa, otváram produkt…",
          sugg: "Hľadané výrazy", popular: "Populárne vyhľadávania", cats: "Kategórie", topCats: "Obľúbené kategórie",
          brands: "Značky", pages: "Informácie", products: "Produkty", placeholder: "Poď hľadať a pomôže aj Ai 🤖", close: "Zavrieť" },
    hu: { ai: "Kérdezd az AI-t", aiHint: "Írd le a saját szavaiddal, mire van szükséged",
          thinking: "Az AI keresi a legjobb termékeket…",
          steps: ["Értem, mit keresel…", "Átnézem a teljes kínálatot…", "Kiválasztom a legmegfelelőbb termékeket…", "Még egy pillanat…"],
          aiSlow: "Az AI most nem válaszol, a szokásos találatokat mutatom.",
          helped: "Segített?", thanks: "Köszönjük az értékelést!", all: "Összes találat", none: "Nincs találat. Próbáld másképp leírni, vagy kérdezd az AI-t.",
          inStock: "Raktáron", outStock: "Rendelésre", from: "", fixed: "Találatok erre:",
          fav: "Kedvencekhez", cmp: "Összehasonlításhoz", favDone: "Hozzáadva a kedvencekhez",
          cmpDone: "Hozzáadva az összehasonlításhoz", actFail: "Nem sikerült, megnyitom a terméket…",
          sugg: "Keresési javaslatok", popular: "Népszerű keresések", cats: "Kategóriák", topCats: "Népszerű kategóriák",
          brands: "Márkák", pages: "Információk", products: "Termékek", placeholder: "Gyere, keressük meg, az AI is segít majd 🤖", close: "Bezár" }
  };
  var t = T[LANG] || T.sk;

  var css = "" +
    ".pas-panel{position:absolute;z-index:99999;background:#fff;color:#222;border:1px solid #ddd;border-radius:12px;" +
    "box-shadow:0 14px 36px rgba(0,0,0,.18);max-height:80vh;overflow:auto}" +
    ".pas-panel,.pas-ov{font:14px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;box-sizing:border-box;text-align:left;color:#222}" +
    ".pas-panel *,.pas-ov *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}" +
    ".pas-ai{display:flex;gap:10px;align-items:center;padding:8px 14px;border-bottom:1px solid #f0f0f0}" +
    ".pas-ai button{border:0;border-radius:999px;padding:6px 12px;font:600 13px/1.2 inherit;cursor:pointer;" +
    "background:linear-gradient(90deg,#f39200,#e4572e);color:#fff;white-space:nowrap}" +
    ".pas-ai span{color:#888;font-size:12px}" +
    ".pas-summary{padding:10px 14px;background:#fff8ec;border-bottom:1px solid #f3e2c2;font-weight:600;display:flex;" +
    "gap:10px;align-items:center;flex-wrap:wrap}.pas-fb{margin-left:auto;font-weight:400;font-size:12px;color:#777;display:flex;" +
    "align-items:center;gap:4px}.pas-fb button{border:1px solid #e8d3ad;background:#fff;border-radius:999px;width:36px;height:30px;padding:0;display:inline-flex;align-items:center;justify-content:center;" +
    "cursor:pointer;font-size:15px;line-height:1}.pas-fb button:hover{background:#fff1d9}" +
    ".pas-fix{padding:8px 14px;font-size:13px;color:#666;border-bottom:1px solid #f0f0f0}.pas-fix b{color:#111}" +
    ".pas-cols{display:flex}.pas-left{flex:0 0 36%;border-right:1px solid #eee;padding:4px 0 8px}.pas-right{flex:1;min-width:0}" +
    ".pas-h{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:#999;padding:10px 14px 4px;font-weight:600}" +
    ".pas-s{display:flex;align-items:center;gap:10px;padding:6px 14px;color:#333;text-decoration:none;cursor:pointer}" +
    ".pas-s:hover,.pas-s.pas-active{background:#f6f8fb}" +
    ".pas-s .pas-ic{color:#bbb;flex:none;width:14px;text-align:center}" +
    ".pas-s b{font-weight:700;color:#111}.pas-s .pas-k{margin-left:auto;font-size:10px;color:#aaa;border:1px solid #ddd;border-radius:4px;padding:0 4px}" +
    ".pas-item{display:flex;gap:12px;align-items:center;padding:8px 14px;text-decoration:none;color:inherit;border-bottom:1px solid #f3f3f3}" +
    ".pas-item:hover,.pas-item.pas-active{background:#f6f8fb}" +
    ".pas-item img{width:56px;height:56px;object-fit:contain;flex:none;background:#fff}" +
    ".pas-item .pas-t{font-weight:500}.pas-item .pas-t b{font-weight:700}" +
    ".pas-item .pas-r{color:#2f7d32;font-size:12px;margin-top:2px}" +
    ".pas-item .pas-m{display:flex;gap:10px;font-size:12px;color:#777;margin-top:2px}" +
    ".pas-item .pas-p{font-weight:700;color:#111;white-space:nowrap}" +
    ".pas-ok{color:#2f7d32}.pas-no{color:#b26a00}" +
    ".pas-side{margin-left:auto;display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex:none}" +
    ".pas-act{display:flex;gap:2px}.pas-act button{width:34px;height:34px;border:0;border-radius:8px;background:none;" +
    "color:#888;font-size:17px;line-height:1;cursor:pointer;padding:0}.pas-act button:hover{background:#eef1f5;color:#e4572e}" +
    ".pas-act button.pas-on{color:#e4572e}.pas-ov .pas-act button{width:42px;height:42px;font-size:19px}" +
    ".pas-toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:2147483646;background:#222;color:#fff;" +
    "padding:10px 16px;border-radius:999px;font:14px/1.3 system-ui,sans-serif;box-shadow:0 6px 20px rgba(0,0,0,.25)}" +
    ".pas-foot{display:block;padding:12px 14px;text-align:center;color:#e4572e;font-weight:600;cursor:pointer;text-decoration:none}" +
    ".pas-msg{padding:16px 14px;color:#666}" +
    ".pas-spin{display:inline-block;width:14px;height:14px;border:2px solid #f39200;border-right-color:transparent;" +
    "border-radius:50%;animation:pasr .7s linear infinite;vertical-align:-2px;margin-right:8px}" +
    "@keyframes pasr{to{transform:rotate(360deg)}}" +
    ".pas-bar{height:3px;background:linear-gradient(90deg,#f39200,#e4572e,#ffd08a,#f39200);background-size:200% 100%;" +
    "animation:pasbar 1.1s linear infinite}@keyframes pasbar{to{background-position:-200% 0}}" +
    ".pas-load{padding:16px 14px 6px}.pas-load-h{display:flex;align-items:center;gap:12px}" +
    ".pas-load-h .pas-spin{width:28px;height:28px;border-width:3px;margin:0;flex:none}" +
    ".pas-load-t{font-weight:700;font-size:15px;color:#222}.pas-step{color:#777;font-size:13px;margin-top:2px;min-height:18px}" +
    ".pas-sk{display:flex;gap:12px;align-items:center;padding:10px 14px}.pas-sk i{display:block;border-radius:6px;" +
    "background:linear-gradient(90deg,#eee,#f7f7f7,#eee);background-size:200% 100%;animation:pasbar 1.4s linear infinite}" +
    // chips (phone): categories / brands in one horizontally scrollable row
    ".pas-chips{display:flex;gap:8px;overflow-x:auto;padding:8px 14px 10px;scrollbar-width:none;-webkit-overflow-scrolling:touch}" +
    ".pas-chips::-webkit-scrollbar{display:none}" +
    ".pas-chip{flex:none;padding:9px 14px;border-radius:999px;background:#f2f3f5;color:#222;text-decoration:none;white-space:nowrap;font-size:14px}" +
    // full-screen search (phone)
    ".pas-ov{position:fixed;left:0;top:0;right:0;bottom:0;z-index:2147483000;background:#fff;display:flex;flex-direction:column}" +
    ".pas-ovh{display:flex;gap:6px;align-items:center;padding:8px 8px 8px 12px;border-bottom:1px solid #eee;background:#fff}" +
    ".pas-ovh input{flex:1;min-width:0;font-size:16px;padding:11px 14px;border:1px solid #ccc;border-radius:12px;" +
    "background:#fff;color:#111;-webkit-appearance:none;appearance:none;outline:none}" +
    ".pas-ovh input:focus{border-color:#f39200}" +
    ".pas-hint{padding:8px 16px 0;color:#888;font-size:13px}" +
    ".pas-ovh input::placeholder{text-overflow:ellipsis;white-space:nowrap;overflow:hidden;color:#999;" +
    "font-size:var(--pas-ph,16px)}" +
    ".pas-x{flex:none;width:44px;height:44px;border:0;background:none;font-size:24px;line-height:1;color:#444;cursor:pointer}" +
    ".pas-ovb{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain}" +
    ".pas-ov .pas-s{min-height:46px;font-size:15px}.pas-ov .pas-item{min-height:72px}" +
    ".pas-ov .pas-ai{padding:8px 14px}" +
    "html.pas-lock,html.pas-lock body{overflow:hidden!important}";
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
    var h;
    var d = function () { var a = arguments, s = this; clearTimeout(h); h = setTimeout(function () { fn.apply(s, a); }, ms); };
    d.cancel = function () { clearTimeout(h); };
    return d;
  }
  // When the widget takes over Enter, the shop template's own search must not submit the form
  // (it would navigate away before the AI answer appears).
  var submitBlock = { form: null, until: 0 };
  document.addEventListener("submit", function (e) {
    if (submitBlock.form && e.target === submitBlock.form && Date.now() < submitBlock.until) {
      e.preventDefault();
      e.stopImmediatePropagation();
    }
  }, true);
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
  // Random id of this page view - only to tell one search from the next in the statistics.
  var SID = Math.random().toString(36).slice(2, 12);
  function track(type, q, pid) {
    q = (q || "").trim();
    if (q.length < 2) return;
    var url = API + "/api/track?lang=" + encodeURIComponent(LANG) + "&type=" + type + "&sid=" + SID +
      "&q=" + encodeURIComponent(q) + (pid ? "&pid=" + encodeURIComponent(pid) : "");
    try { fetch(url, { keepalive: true, credentials: "omit" }); } catch (e) { /* ignore */ }
  }

  // ------------------------------------------------------------------ rendering
  function sItem(icon, html, attrs, kbd) {
    return '<a class="pas-s pas-nav" ' + attrs + '><span class="pas-ic">' + icon + "</span><span>" + html + "</span>" +
      (kbd ? '<span class="pas-k">' + kbd + "</span>" : "") + "</a>";
  }
  function target(name, url) { return url ? 'href="' + esc(url) + '"' : 'data-pas-q="' + esc(name) + '"'; }
  function chip(name, url, query) { return '<a class="pas-chip pas-nav" ' + target(name, url) + ">" + highlight(name, query) + "</a>"; }
  function productHtml(p, query) {
    var price = (p.price_max && p.price_max > p.price ? t.from : "") + money(p.price, p.currency);
    return '<a class="pas-item pas-nav" role="option" href="' + esc(p.url) + '" data-pas-pid="' + esc(p.id) + '">' +
      (p.image ? '<img loading="lazy" alt="" src="' + esc(p.image) + '">' : "") +
      '<div style="min-width:0"><div class="pas-t">' + highlight(p.title, query) + "</div>" +
      (p.reason ? '<div class="pas-r">✔ ' + esc(p.reason) + "</div>" : "") +
      '<div class="pas-m"><span class="' + (p.in_stock ? "pas-ok" : "pas-no") + '">' +
      esc(p.in_stock ? (p.availability || t.inStock) : t.outStock) + "</span>" +
      (p.manufacturer ? "<span>" + esc(p.manufacturer) + "</span>" : "") + "</div></div>" +
      '<div class="pas-side"><div class="pas-p">' + esc(price) + "</div>" + (SHOP_ACTIONS(p.url)
        ? '<div class="pas-act"><button type="button" data-pas-act="fav" data-url="' + esc(p.url) + '" title="' + esc(t.fav) +
          '" aria-label="' + esc(t.fav) + '">♡</button><button type="button" data-pas-act="cmp" data-url="' + esc(p.url) +
          '" title="' + esc(t.cmp) + '" aria-label="' + esc(t.cmp) + '">⇄</button></div>' : "") + "</div></a>";
  }

  // ------------------------------------------------------------------ favourites / compare
  /* Uses the shop's own buttons: the widget loads the product page, finds Upgates'
   * "function-favourites" / "function-compare" links and follows them in the background,
   * so the product lands in the same favourites / comparison as from the shop itself. */
  function SHOP_ACTIONS(url) {
    try { return new URL(url, location.href).origin === location.origin; } catch (e) { return false; }
  }
  function toast(msg) {
    var el = document.createElement("div");
    el.className = "pas-toast";
    el.textContent = msg;
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 2600);
  }
  function shopAction(kind, productUrl, button, closeSearch) {
    var sel = kind === "fav" ? ".function-favourites" : ".function-compare";
    button.disabled = true;
    fetch(productUrl, { credentials: "include" }).then(function (r) { return r.text(); }).then(function (html) {
      var a = new DOMParser().parseFromString(html, "text/html").querySelector(sel);
      if (!a) throw new Error("button not found");
      var target = a.getAttribute("data-target");
      if (a.getAttribute("data-toggle") === "modal" && target) {
        // Not logged in: open the shop's own login dialog, exactly like its button does.
        closeSearch();
        var opener = document.querySelector('[data-toggle="modal"][data-target="' + target + '"]');
        if (opener) { opener.click(); } else { location.href = productUrl; }
        return;
      }
      var href = new URL(a.getAttribute("href"), productUrl).href;
      return fetch(href, { credentials: "include" }).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        button.classList.add("pas-on");
        if (kind === "fav") button.textContent = "♥";
        toast(kind === "fav" ? t.favDone : t.cmpDone);
      });
    }).catch(function () {
      toast(t.actFail);
      setTimeout(function () { location.href = productUrl; }, 900);
    }).then(function () { button.disabled = false; });
  }

  function renderEmpty(data, compact) {
    var h = "";
    var pop = (data.popular || []).slice(0, compact ? 5 : 8);
    if (pop.length) {
      h += '<div class="pas-h">' + esc(t.popular) + "</div>" +
        pop.map(function (q) { return sItem("↗", esc(q), 'data-pas-q="' + esc(q) + '"'); }).join("");
    }
    var cats = data.categories || [];
    if (cats.length) {
      h += '<div class="pas-h">' + esc(t.topCats) + "</div>" + (compact
        ? '<div class="pas-chips">' + cats.map(function (c) { return chip(c.name, c.url, ""); }).join("") + "</div>"
        : cats.map(function (c) { return sItem("▸", esc(c.name), target(c.name, c.url)); }).join(""));
    }
    return h ? '<div style="padding:4px 0">' + h + "</div>" : "";
  }

  function renderResults(data, isAi, compact, hasForm) {
    var q = data.query || "";
    var h = "";
    if (isAi) {
      if (data.ai && data.ai.summary) {
        h += '<div class="pas-summary"><span>✨ ' + esc(data.ai.summary) + '</span><span class="pas-fb" data-pas-fbbox>' +
          esc(t.helped) + ' <button type="button" data-pas-fb="up" aria-label="áno">👍</button>' +
          '<button type="button" data-pas-fb="down" aria-label="nie">👎</button></span></div>';
      }
    } else if (q.trim().length >= 3) {
      h += '<div class="pas-ai"><button type="button" data-pas-ai>✨ ' + esc(t.ai) + "</button>" +
        (compact ? "" : "<span>" + esc(t.aiHint) + "</span>") + "</div>";
    }
    var fixes = data.corrections ? Object.keys(data.corrections) : [];
    if (fixes.length) {
      var fixedQuery = q.split(/\s+/).map(function (w) { return data.corrections[fold(w)] || w; }).join(" ");
      h += '<div class="pas-fix">' + esc(t.fixed) + " <b>" + esc(fixedQuery) + "</b></div>";
    }

    var sug = isAi ? [] : (data.suggestions || []).slice(0, compact ? 4 : 6);
    var cats = isAi ? [] : (data.categories || []);
    var brands = isAi ? [] : (data.brands || []);
    var pages = isAi ? [] : (data.pages || []);
    var sugHtml = sug.map(function (s, i) {
      return sItem("⌕", suggestionHtml(s, q), 'data-pas-q="' + esc(s) + '"', i === 0 && !TOUCH && !compact ? "Tab" : "");
    }).join("");

    var products = "";
    if (!data.products || !data.products.length) {
      products += '<div class="pas-msg">' + esc(t.none) + "</div>";
    } else {
      products += data.products.map(function (p) { return productHtml(p, q); }).join("");
    }
    if (hasForm && data.total) products += '<a class="pas-foot pas-nav" data-pas-all>' + esc(t.all) + " (" + data.total + ") →</a>";

    if (compact) {
      // Phone: few suggestions, one row of chips, then straight to products.
      h += sugHtml;
      var chips = cats.map(function (c) { return chip(c.name, c.url, q); })
        .concat(brands.map(function (b) { return chip(b.name, b.url, q); }))
        .concat(pages.map(function (p) { return chip(p.title, p.url, q); }));
      if (chips.length) h += '<div class="pas-chips">' + chips.join("") + "</div>";
      return h + products;
    }

    var left = "";
    if (sugHtml) left += '<div class="pas-h">' + esc(t.sugg) + "</div>" + sugHtml;
    if (cats.length) left += '<div class="pas-h">' + esc(t.cats) + "</div>" + cats.map(function (c) {
      return sItem("▸", highlight(c.name, q), target(c.name, c.url));
    }).join("");
    if (brands.length) left += '<div class="pas-h">' + esc(t.brands) + "</div>" + brands.map(function (b) {
      return sItem("★", highlight(b.name, q), target(b.name, b.url));
    }).join("");
    if (pages.length) left += '<div class="pas-h">' + esc(t.pages) + "</div>" + pages.map(function (p) {
      return sItem("ℹ", highlight(p.title, q), 'href="' + esc(p.url) + '"');
    }).join("");
    if (!left) return h + products;
    return h + '<div class="pas-cols"><div class="pas-left">' + left + '</div><div class="pas-right">' +
      '<div class="pas-h">' + esc(t.products) + "</div>" + products + "</div></div>";
  }

  // ------------------------------------------------------------------ controller
  /* Binds one text field to one results box. Used for the desktop panel (field = the shop's
   * own input) and for the phone full-screen search (field = the overlay's input). */
  function controller(field, box, o) {
    var seq = 0, active = -1, lastQuery = null, lastData = null, idle = null, aiQuery = null, enterAt = 0;

    function setActive(i, items) {
      active = i;
      items.forEach(function (el, j) { el.classList.toggle("pas-active", j === i); });
      if (items[i]) items[i].scrollIntoView({ block: "nearest" });
    }
    function show(html) { if (html) { box.innerHTML = html; active = -1; o.show(); } else { o.hide(); } }

    var stepTimer = null;
    function loadingHtml() {
      var sk = "";
      for (var i = 0; i < 3; i++) {
        sk += '<div class="pas-sk"><i style="width:56px;height:56px;flex:none"></i><div style="flex:1">' +
          '<i style="height:12px;width:' + (80 - i * 12) + '%"></i><i style="height:10px;width:40%;margin-top:8px"></i></div>' +
          '<i style="width:48px;height:14px"></i></div>';
      }
      return '<div class="pas-bar"></div><div class="pas-load" role="status" aria-live="polite"><div class="pas-load-h">' +
        '<span class="pas-spin"></span><div><div class="pas-load-t">✨ ' + esc(t.thinking) + '</div>' +
        '<div class="pas-step" data-pas-step>' + esc(t.steps[0]) + "</div></div></div></div>" + sk;
    }
    function stopSteps() { clearInterval(stepTimer); stepTimer = null; }

    function search(q, ai) {
      var my = ++seq;
      stopSteps();
      aiQuery = ai ? q : null;
      var ctrl = window.AbortController ? new AbortController() : null;
      var timeout = null;
      if (ai) {
        show(loadingHtml());
        var step = 0;
        stepTimer = setInterval(function () {
          var el = box.querySelector("[data-pas-step]");
          if (!el || my !== seq) return stopSteps();
          step = Math.min(step + 1, t.steps.length - 1);
          el.textContent = t.steps[step];
        }, 1800);
        // Never leave the customer waiting: after 20 s show the normal results instead.
        if (ctrl) timeout = setTimeout(function () { ctrl.abort(); }, 20000);
      }
      var url = API + "/api/search?lang=" + encodeURIComponent(LANG) + "&limit=" + (ai ? 10 : (o.compact ? 8 : 6)) +
        "&ai=" + (ai ? 1 : 0) + "&q=" + encodeURIComponent(q) + (ai ? "&sid=" + SID : "");
      fetch(url, { credentials: "omit", signal: ctrl ? ctrl.signal : undefined }).then(function (r) { return r.json(); }).then(function (data) {
        clearTimeout(timeout);
        if (my !== seq) return; // a newer query is already running
        stopSteps();
        aiQuery = null;
        lastData = data;
        if (ai && !data.ai && !data.error) toast(t.aiSlow);
        show(q ? renderResults(data, ai && !!data.ai, o.compact, !!o.form()) : renderEmpty(data, o.compact));
        // A query the customer stopped typing at counts as a search in the statistics.
        clearTimeout(idle);
        if (q && !ai) idle = setTimeout(function () { if (field.value === q) track("search", q); }, 1500);
        if (ai && o.compact) field.blur(); // hide the phone keyboard so the AI answer is visible
      }).catch(function () {
        clearTimeout(timeout);
        if (my !== seq) return;
        stopSteps();
        aiQuery = null;
        if (ai) { toast(t.aiSlow); search(q, false); } // fall back to the instant results, never a blank panel
      });
    }
    function applyQuery(q) {
      field.value = q;
      lastQuery = q;
      track("suggestion", q);
      search(q, false);
      field.focus();
    }
    function submitAll() {
      var q = field.value.trim();
      track("all", q);
      o.submit(q);
    }

    var instant = debounce(function () {
      var q = field.value;
      if (q === lastQuery) return;
      if (aiQuery !== null && q.trim() === aiQuery) return; // the AI is already answering exactly this
      lastQuery = q;
      if (!q.trim()) return search("", false);
      if (q.trim().length < 2) { seq++; return o.compact ? search("", false) : o.hide(); }
      search(q, false);
    }, 120);

    function startAi(q) {
      instant.cancel();          // a pending as-you-type search must not replace the AI loader
      lastQuery = field.value;
      track("ai", q);
      search(q, true);
    }
    function enter() {
      var q = field.value.trim();
      if (ENTER_MODE === "ai" && q.length >= 3) { startAi(q); return true; }
      if (o.compact && q) { submitAll(); return true; }
      return false;
    }
    function takeOverEnter(e) {
      e.preventDefault();
      e.stopImmediatePropagation(); // the template's own Enter handler must not run
      enterAt = Date.now();
      submitBlock.form = field.form;
      submitBlock.until = Date.now() + 1500;
    }

    field.addEventListener("input", instant);
    // Some templates react on keypress / keyup instead of keydown - swallow those too.
    ["keypress", "keyup"].forEach(function (type) {
      field.addEventListener(type, function (e) {
        if (e.key === "Enter" && Date.now() - enterAt < 800) { e.preventDefault(); e.stopImmediatePropagation(); }
      }, true);
    });
    field.addEventListener("keydown", function (e) {
      var items = Array.prototype.slice.call(box.querySelectorAll(".pas-nav"));
      var open = o.isOpen();
      if ((e.key === "ArrowDown" || e.key === "ArrowUp") && open && items.length) {
        e.preventDefault();
        setActive((active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length, items);
      } else if (e.key === "Tab" && !o.compact && open && !e.shiftKey && lastData && lastData.suggestions &&
                 lastData.suggestions.length && field.selectionStart === field.value.length) {
        e.preventDefault();
        applyQuery(lastData.suggestions[0] + " ");
      } else if (e.key === "Enter") {
        if (active >= 0 && items[active]) { takeOverEnter(e); items[active].click(); return; }
        var q = field.value.trim();
        if ((ENTER_MODE === "ai" && q.length >= 3) || (o.compact && q)) { takeOverEnter(e); enter(); }
      } else if (e.key === "Escape") { o.close(); }
    }, true); // capture: runs before the template's own listeners on the same field
    box.addEventListener("mousedown", function (e) { if (!o.compact) e.preventDefault(); }); // keep focus in the input
    box.addEventListener("click", function (e) {
      var el;
      if ((el = e.target.closest("[data-pas-ai]"))) { e.preventDefault(); startAi(field.value.trim()); if (!o.compact) field.focus(); return; }
      if ((el = e.target.closest("[data-pas-q]"))) { e.preventDefault(); applyQuery(el.getAttribute("data-pas-q")); if (o.compact) field.blur(); return; }
      if ((el = e.target.closest("[data-pas-all]"))) { e.preventDefault(); submitAll(); return; }
      if ((el = e.target.closest("[data-pas-fb]"))) {
        e.preventDefault();
        var vote = el.getAttribute("data-pas-fb");
        try {
          fetch(API + "/api/track?type=ai_feedback&v=" + vote + "&lang=" + encodeURIComponent(LANG) + "&sid=" + SID +
            "&q=" + encodeURIComponent(field.value.trim()), { keepalive: true, credentials: "omit" });
        } catch (err) { /* ignore */ }
        var fbBox = el.closest("[data-pas-fbbox]");
        if (fbBox) fbBox.textContent = t.thanks;
        return;
      }
      if ((el = e.target.closest("[data-pas-act]"))) {
        e.preventDefault();
        e.stopPropagation();
        var item = el.closest("[data-pas-pid]");
        if (item) track("click", field.value, item.getAttribute("data-pas-pid"));
        shopAction(el.getAttribute("data-pas-act"), el.getAttribute("data-url"), el, o.close);
        return;
      }
      if ((el = e.target.closest("[data-pas-pid]"))) { track("click", field.value, el.getAttribute("data-pas-pid")); }
    });

    return {
      refresh: function () { lastQuery = null; instant(); },
      search: search,
      enter: enter
    };
  }

  // ------------------------------------------------------------------ phone: full-screen search
  var overlay = null;
  function phoneSearch() {
    if (overlay) return overlay;
    var ov = document.createElement("div");
    ov.className = "pas-ov";
    ov.style.display = "none";
    ov.setAttribute("role", "dialog");
    ov.innerHTML = '<form class="pas-ovh" action="#" role="search"><input type="search" enterkeyhint="search" autocomplete="off" ' +
      'autocorrect="off" autocapitalize="off" spellcheck="false" placeholder="' + esc(ds.placeholder || t.placeholder) + '">' +
      '<button type="button" class="pas-x" aria-label="' + esc(t.close) + '">✕</button></form><div class="pas-ovb"></div>';
    var field = ov.querySelector("input"), box = ov.querySelector(".pas-ovb");
    var phText = field.placeholder;
    var hint = document.createElement("div");
    hint.className = "pas-hint";
    hint.style.display = "none";
    ov.querySelector(".pas-ovh").insertAdjacentElement("afterend", hint);
    field.addEventListener("input", function () { if (!field.placeholder) hint.style.display = field.value ? "none" : "block"; });
    field.__pas = true; // never treat our own field as a shop search box
    document.body.appendChild(ov);
    var source = null, pushed = false;

    function close(fromHistory) {
      if (ov.style.display === "none") return;
      ov.style.display = "none";
      document.documentElement.classList.remove("pas-lock");
      if (source) source.value = field.value;
      if (pushed && !fromHistory) { pushed = false; history.back(); }
      pushed = false;
    }
    var ctl = controller(field, box, {
      compact: true,
      show: function () {}, hide: function () { box.innerHTML = ""; },
      isOpen: function () { return ov.style.display !== "none"; },
      close: function () { close(false); },
      form: function () { return source && source.form; },
      submit: function (q) {
        if (!source || !source.form) return;
        source.value = q;
        close(true); // leaving the page anyway; keep the history entry harmless
        if (source.form.requestSubmit) source.form.requestSubmit(); else source.form.submit();
      }
    });
    ov.querySelector(".pas-x").addEventListener("click", function () { close(false); });
    // Phone keyboards' "Search / Go" key submits this form even when it sends no Enter keydown.
    ov.querySelector("form").addEventListener("submit", function (e) { e.preventDefault(); ctl.enter(); });
    // Scrolling the results hides the keyboard, so customers see more products.
    box.addEventListener("touchstart", function () { field.blur(); }, { passive: true });
    window.addEventListener("popstate", function () { close(true); }); // phone Back button closes the search

    // Shrink the placeholder (not the typed text) so a long hint fits the phone's width.
    function fitPlaceholder() {
      try {
        var cs = getComputedStyle(field);
        var avail = field.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 30; // room for the clear (×) button
        var probe = document.createElement("span");
        probe.style.cssText = "position:absolute;visibility:hidden;white-space:nowrap;font-size:16px;font-family:" + cs.fontFamily;
        field.placeholder = phText;
        probe.textContent = phText;
        ov.appendChild(probe);
        var w = probe.getBoundingClientRect().width;
        probe.remove();
        var size = w > avail ? Math.floor(16 * avail / w * 10) / 10 : 16;
        if (size >= 12) {
          field.style.setProperty("--pas-ph", size + "px");
          hint.style.display = "none";
        } else {
          // Too long for this phone even at a small size: show it in full as a line under the field.
          field.placeholder = "";
          hint.textContent = phText;
          hint.style.display = field.value ? "none" : "block";
        }
      } catch (e) { /* keep default size */ }
    }

    overlay = {
      open: function (input) {
        source = input;
        field.value = input.value;
        ov.style.display = "flex";
        fitPlaceholder();
        document.documentElement.classList.add("pas-lock");
        try { history.pushState({ pasSearch: 1 }, ""); pushed = true; } catch (e) { pushed = false; }
        field.focus();
        ctl.refresh();
      }
    };
    return overlay;
  }

  // ------------------------------------------------------------------ desktop: panel under the box
  function attach(input) {
    if (input.__pas) return;
    input.__pas = true;
    input.setAttribute("autocomplete", "off");
    var panel = document.createElement("div");
    panel.className = "pas-panel";
    panel.style.display = "none";
    panel.setAttribute("role", "listbox");
    document.body.appendChild(panel);

    function place() {
      var r = input.getBoundingClientRect();
      var vw = document.documentElement.clientWidth;
      var width = Math.min(Math.max(r.width, 820), vw - 16);
      var left = Math.min(Math.max(8, r.left), vw - width - 8);
      panel.style.top = (r.bottom + window.scrollY + 6) + "px";
      panel.style.left = (left + window.scrollX) + "px";
      panel.style.width = width + "px";
    }
    var ctl = controller(input, panel, {
      compact: false,
      show: function () { place(); panel.style.display = "block"; },
      hide: function () { panel.style.display = "none"; },
      isOpen: function () { return panel.style.display !== "none"; },
      close: function () { panel.style.display = "none"; },
      form: function () { return input.form; },
      submit: function () {
        panel.style.display = "none";
        if (input.form.requestSubmit) input.form.requestSubmit(); else input.form.submit();
      }
    });

    function openPhone(e) {
      if (!isPhone()) return false;
      if (e) e.preventDefault();
      input.blur();
      phoneSearch().open(input);
      return true;
    }
    input.addEventListener("focus", function () {
      if (openPhone()) return;
      if (panel.innerHTML && panel.style.display === "none") { if (input.value.trim().length >= 2) { place(); panel.style.display = "block"; } }
      if (!input.value.trim()) ctl.search("", false);
    });
    input.addEventListener("click", function (e) { if (isPhone()) openPhone(e); });
    document.addEventListener("click", function (e) { if (e.target !== input && !panel.contains(e.target)) panel.style.display = "none"; });
    window.addEventListener("resize", function () { if (panel.style.display !== "none") place(); });
  }

  function init() { document.querySelectorAll(SELECTOR).forEach(attach); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
  // Upgates templates can render the search box lazily (mobile menu) – watch for it.
  new MutationObserver(debounce(init, 300)).observe(document.documentElement, { childList: true, subtree: true });
})();
