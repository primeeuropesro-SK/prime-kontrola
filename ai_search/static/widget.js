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
          thinking: "AI hľadá najvhodnejšie produkty…", all: "Zobraziť všetky výsledky", none: "Nič sme nenašli. Skúste to opísať inak.",
          inStock: "Skladom", outStock: "Na objednávku", from: "od ", cats: "Kategórie", close: "Zavrieť" },
    hu: { ai: "Kérdezd az AI-t", aiHint: "Írd le, mire van szükséged – pl. „téli kesztyű 3000 Ft alatt”",
          thinking: "Az AI keresi a legjobb termékeket…", all: "Összes találat", none: "Nincs találat. Próbáld másképp leírni.",
          inStock: "Raktáron", outStock: "Rendelésre", from: "", cats: "Kategóriák", close: "Bezár" }
  };
  var t = T[LANG] || T.sk;

  var css = "" +
    ".pas-panel{position:absolute;z-index:99999;background:#fff;color:#222;border:1px solid #ddd;border-radius:10px;" +
    "box-shadow:0 12px 32px rgba(0,0,0,.18);font:14px/1.4 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;" +
    "max-height:75vh;overflow:auto;min-width:320px;box-sizing:border-box}" +
    ".pas-panel *{box-sizing:border-box}" +
    ".pas-ai{display:flex;gap:8px;align-items:center;padding:10px 12px;border-bottom:1px solid #eee;background:#fafafa}" +
    ".pas-ai button{border:0;border-radius:999px;padding:7px 14px;font-weight:600;cursor:pointer;" +
    "background:linear-gradient(90deg,#f39200,#e4572e);color:#fff;white-space:nowrap}" +
    ".pas-ai span{color:#666;font-size:12px}" +
    ".pas-summary{padding:10px 12px;background:#fff8ec;border-bottom:1px solid #f3e2c2;font-weight:600}" +
    ".pas-cats{padding:8px 12px;display:flex;flex-wrap:wrap;gap:6px;border-bottom:1px solid #eee}" +
    ".pas-cats b{width:100%;font-size:11px;text-transform:uppercase;color:#888}" +
    ".pas-cats span{background:#f1f1f1;border-radius:999px;padding:3px 10px;font-size:12px}" +
    ".pas-item{display:flex;gap:12px;padding:8px 12px;text-decoration:none;color:inherit;border-bottom:1px solid #f3f3f3}" +
    ".pas-item:hover,.pas-item.pas-active{background:#f6f8fb}" +
    ".pas-item img{width:56px;height:56px;object-fit:contain;flex:none;background:#fff}" +
    ".pas-item .pas-t{font-weight:600}" +
    ".pas-item .pas-r{color:#2f7d32;font-size:12px;margin-top:2px}" +
    ".pas-item .pas-m{display:flex;gap:10px;font-size:12px;color:#777;margin-top:2px}" +
    ".pas-item .pas-p{margin-left:auto;font-weight:700;color:#111;white-space:nowrap;align-self:center}" +
    ".pas-ok{color:#2f7d32}.pas-no{color:#b26a00}" +
    ".pas-foot{display:block;padding:10px 12px;text-align:center;color:#e4572e;font-weight:600;cursor:pointer;text-decoration:none}" +
    ".pas-msg{padding:16px 12px;color:#666}" +
    ".pas-spin{display:inline-block;width:14px;height:14px;border:2px solid #f39200;border-right-color:transparent;" +
    "border-radius:50%;animation:pasr .7s linear infinite;vertical-align:-2px;margin-right:8px}" +
    "@keyframes pasr{to{transform:rotate(360deg)}}" +
    "@media(max-width:600px){.pas-panel{left:8px!important;right:8px;width:auto!important;min-width:0}}";
  var style = document.createElement("style");
  style.textContent = css;
  document.head.appendChild(style);

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function money(v, cur) {
    if (v == null) return "";
    try { return new Intl.NumberFormat(LANG, { style: "currency", currency: cur || "EUR", maximumFractionDigits: cur === "HUF" ? 0 : 2 }).format(v); }
    catch (e) { return v + " " + (cur || ""); }
  }
  function debounce(fn, ms) {
    var h; return function () { var a = arguments, s = this; clearTimeout(h); h = setTimeout(function () { fn.apply(s, a); }, ms); };
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
    var seq = 0, active = -1, lastQuery = "";

    function place() {
      var r = input.getBoundingClientRect();
      panel.style.top = (r.bottom + window.scrollY + 6) + "px";
      panel.style.left = Math.max(8, r.left + window.scrollX) + "px";
      panel.style.width = Math.max(r.width, Math.min(560, window.innerWidth - 16)) + "px";
    }
    function show(html) { place(); panel.innerHTML = html; panel.style.display = "block"; active = -1; }
    function hide() { panel.style.display = "none"; }

    function render(data, isAi) {
      var h = "";
      if (!isAi) {
        h += '<div class="pas-ai"><button type="button" data-pas-ai>✨ ' + esc(t.ai) + "</button><span>" + esc(t.aiHint) + "</span></div>";
      } else if (data.ai && data.ai.summary) {
        h += '<div class="pas-summary">✨ ' + esc(data.ai.summary) + "</div>";
      }
      if (!isAi && data.categories && data.categories.length) {
        h += '<div class="pas-cats"><b>' + esc(t.cats) + "</b>" +
          data.categories.map(function (c) { return "<span>" + esc(c) + "</span>"; }).join("") + "</div>";
      }
      if (!data.products || !data.products.length) {
        h += '<div class="pas-msg">' + esc(t.none) + "</div>";
      }
      (data.products || []).forEach(function (p) {
        var price = (p.price_max && p.price_max > p.price ? t.from : "") + money(p.price, p.currency);
        h += '<a class="pas-item" role="option" href="' + esc(p.url) + '">' +
          (p.image ? '<img loading="lazy" alt="" src="' + esc(p.image) + '">' : "") +
          "<div><div class=\"pas-t\">" + esc(p.title) + "</div>" +
          (p.reason ? '<div class="pas-r">✔ ' + esc(p.reason) + "</div>" : "") +
          '<div class="pas-m"><span class="' + (p.in_stock ? "pas-ok" : "pas-no") + '">' +
          esc(p.in_stock ? (p.availability || t.inStock) : t.outStock) + "</span>" +
          (p.manufacturer ? "<span>" + esc(p.manufacturer) + "</span>" : "") + "</div></div>" +
          '<div class="pas-p">' + esc(price) + "</div></a>";
      });
      if (input.form) h += '<a class="pas-foot" data-pas-all>' + esc(t.all) + " (" + (data.total || 0) + ") →</a>";
      show(h);
    }

    function search(q, ai) {
      var my = ++seq;
      if (ai) show('<div class="pas-msg"><span class="pas-spin"></span>' + esc(t.thinking) + "</div>");
      var url = API + "/api/search?lang=" + encodeURIComponent(LANG) + "&limit=" + (ai ? 10 : 6) +
        "&ai=" + (ai ? 1 : 0) + "&q=" + encodeURIComponent(q);
      fetch(url, { credentials: "omit" }).then(function (r) { return r.json(); }).then(function (data) {
        if (my !== seq) return; // a newer query is already running
        render(data, ai);
      }).catch(function () { if (my === seq && ai) hide(); });
    }

    var instant = debounce(function () {
      var q = input.value.trim();
      if (q === lastQuery) return;
      lastQuery = q;
      if (q.length < 2) { seq++; return hide(); }
      search(q, false);
    }, 150);

    input.addEventListener("input", instant);
    input.addEventListener("focus", function () { if (panel.innerHTML && input.value.trim().length >= 2) { place(); panel.style.display = "block"; } });
    input.addEventListener("keydown", function (e) {
      var items = panel.querySelectorAll(".pas-item");
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!items.length || panel.style.display === "none") return;
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach(function (el, i) { el.classList.toggle("pas-active", i === active); });
        items[active].scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") {
        if (active >= 0 && items[active]) { e.preventDefault(); window.location.href = items[active].href; return; }
        if (ENTER_MODE === "ai" && input.value.trim().length >= 3) { e.preventDefault(); search(input.value.trim(), true); }
      } else if (e.key === "Escape") { hide(); }
    });
    panel.addEventListener("click", function (e) {
      if (e.target.closest("[data-pas-ai]")) { e.preventDefault(); search(input.value.trim(), true); input.focus(); }
      if (e.target.closest("[data-pas-all]")) {
        e.preventDefault();
        hide();
        if (input.form.requestSubmit) input.form.requestSubmit(); else input.form.submit();
      }
    });
    document.addEventListener("click", function (e) { if (e.target !== input && !panel.contains(e.target)) hide(); });
    window.addEventListener("resize", function () { if (panel.style.display !== "none") place(); });
  }

  function init() { document.querySelectorAll(SELECTOR).forEach(attach); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
  // Upgates templates can render the search box lazily (mobile menu) – watch for it.
  new MutationObserver(debounce(init, 300)).observe(document.documentElement, { childList: true, subtree: true });
})();
