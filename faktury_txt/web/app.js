(() => {
  const $ = s => document.querySelector(s);
  const list = $("#list"), statusEl = $("#status"), fileInput = $("#file"), drop = $("#drop");
  let pdfReady = false, downloads = null, nextId = 1;
  const docs = [];

  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} }
  };
  let skip = new Set(store.get("skipEans", []));
  const refreshSkipBtn = () => { $("#resetSkip").hidden = skip.size === 0; $("#resetSkip").textContent = `Zrušiť zapamätané vynechané EAN (${skip.size})`; };
  refreshSkipBtn();
  $("#resetSkip").onclick = () => { skip = new Set(); store.set("skipEans", []); refreshSkipBtn(); };

  const setStatus = (t, cls = "") => { statusEl.textContent = t; statusEl.className = "status " + cls; };
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const money = v => FP.fmt(v, 2).replace(".", ",");
  const short = v => { let s = FP.fmt(v); s = s.replace(/0+$/, "").replace(/\.$/, ""); return s.replace(".", ","); };

  if (window.pdfjsLib) {
    pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
    pdfReady = true; setStatus("Pripravené. Nahrajte PDF faktúru.");
  } else setStatus("Čítačku PDF sa nepodarilo načítať. Obnovte stránku.", "err");

  window.claude?.use?.("downloads").then(d => { downloads = d; renderAll(); }).catch(() => {});

  async function readPdf(file) {
    const buf = await file.arrayBuffer();
    const pdf = await pdfjsLib.getDocument({ data: buf }).promise;
    const pages = [];
    for (let p = 1; p <= pdf.numPages; p++) {
      const page = await pdf.getPage(p);
      const tc = await page.getTextContent();
      pages.push(FP.linesFromItems(tc.items.map(it => ({
        str: it.str, x: it.transform[4], y: it.transform[5], w: it.width, h: Math.abs(it.height || it.transform[3]) || 8
      }))));
    }
    return pages;
  }

  async function addFiles(files) {
    if (!pdfReady) return;
    const pdfs = [...files].filter(f => /\.pdf$/i.test(f.name) || f.type === "application/pdf");
    if (!pdfs.length) { setStatus("Vyberte súbor vo formáte PDF.", "err"); return; }
    for (const f of pdfs) {
      setStatus(`Spracúvam ${f.name}…`);
      try {
        const inv = FP.parsePages(await readPdf(f));
        inv.items.forEach(it => { it.on = !skip.has(it.ean); });
        const base = f.name.replace(/\.pdf$/i, "");
        removeExample();
        docs.unshift({ id: nextId++, name: f.name, inv, fname: base, msg: "" });
      } catch (e) {
        docs.unshift({ id: nextId++, name: f.name, inv: { items: [], totals: [], warnings: ["PDF sa nedá prečítať: " + (e.message || e)], currency: "EUR", number: "" }, fname: f.name, msg: "" });
      }
    }
    setStatus(`Spracované: ${pdfs.length} ${pdfs.length === 1 ? "faktúra" : pdfs.length < 5 ? "faktúry" : "faktúr"}.`, "okm");
    renderAll();
  }

  function removeExample() { const i = docs.findIndex(d => d.example); if (i >= 0) docs.splice(i, 1); }

  drop.onclick = () => fileInput.click();
  drop.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fileInput.click(); } };
  fileInput.onchange = () => { addFiles(fileInput.files); fileInput.value = ""; };
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => addFiles(e.dataTransfer.files));
  document.addEventListener("dragover", e => e.preventDefault());
  document.addEventListener("drop", e => { if (!drop.contains(e.target)) { e.preventDefault(); addFiles(e.dataTransfer.files); } });

  const activeItems = d => d.inv.items.filter(it => it.on);

  function ruler() {
    const a = "1234567890".repeat(5).slice(0, 47);
    return `<span class="ruler">${"EAN".padEnd(14)}${"POČET MJ".padStart(15)}${"CENA MJ".padStart(15)}MEN\n${a}</span>\n`;
  }

  function render(d) {
    const items = activeItems(d), ok = FP.totalOk(d.inv, items);
    const chip = ok === true ? `<span class="chip ok">Súčet sedí s faktúrou</span>`
      : ok === false ? `<span class="chip bad">Súčet nesedí s faktúrou</span>` : `<span class="chip none">Súčet na faktúre nenájdený</span>`;
    const warn = [...d.inv.warnings];
    if (ok === false) warn.unshift(`Súčet položiek ${money(FP.total(items))} sa nezhoduje so sumou na faktúre (${d.inv.totals.slice(0, 4).map(money).join("; ")}). Skontrolujte riadky alebo zapnite vypnuté riadky.`);
    const rows = d.inv.items.map((it, n) => `
      <tr class="${it.on ? "" : "off"}" data-n="${n}">
        <td><input type="checkbox" id="on-${d.id}-${n}" ${it.on ? "checked" : ""} aria-label="Zahrnúť riadok"></td>
        <td class="ean"><input type="text" id="ean-${d.id}-${n}" data-k="ean" value="${esc(it.ean)}" inputmode="numeric"></td>
        <td class="num qty"><input type="text" id="qty-${d.id}-${n}" data-k="qty" value="${short(it.qty)}" inputmode="decimal"></td>
        <td class="num price"><input type="text" id="price-${d.id}-${n}" data-k="price" value="${short(it.price)}" inputmode="decimal"></td>
        <td class="num">${money(FP.amount(it))}</td>
        <td><button class="btn" type="button" data-skip="${n}" style="padding:2px 8px;font-size:12px" title="Tento EAN pri ďalších faktúrach automaticky odškrtnúť">vždy vynechať</button></td>
        <td class="src" title="${esc(it.line)}">${esc(it.line)}</td>
      </tr>`).join("");
    const canDl = !!downloads;
    return `
    <section class="card${d.example ? " example" : ""}" data-id="${d.id}">
      <div class="card-head">
        <div class="title"><h2>${esc(d.name)}</h2>
          <div class="meta">${d.example ? "Ukážka s vymyslenými údajmi. Zmizne po nahratí prvej faktúry." : `${d.inv.number ? "Doklad " + esc(d.inv.number) + " · " : ""}${d.inv.items.length} riadkov s EAN`}</div></div>
        ${chip}
        ${d.example ? "" : `<button class="btn" type="button" data-remove title="Odstrániť zo zoznamu">Odstrániť</button>`}
      </div>
      <div class="controls">
        <label class="f" for="cur-${d.id}">Mena
          <select id="cur-${d.id}" data-cur>${FP.CURRENCIES.map(c => `<option${c === d.inv.currency ? " selected" : ""}>${c}</option>`).join("")}</select></label>
        <label class="f" for="fn-${d.id}">Názov TXT (číslo dokladu)
          <input type="text" class="fname" id="fn-${d.id}" data-fname value="${esc(d.fname)}" spellcheck="false"></label>
        <span class="spacer"></span>
        <button class="btn" type="button" data-copy>Kopírovať obsah TXT</button>
        <button class="btn primary" type="button" data-dl ${canDl ? "" : "hidden"}>Stiahnuť ${esc(d.fname)}.txt</button>
      </div>
      ${warn.length ? `<p class="warn">${warn.map(esc).join("<br>")}</p>` : ""}
      <div class="tbl"><table>
        <thead><tr><th>✓</th><th>EAN</th><th class="num">Počet MJ</th><th class="num">Cena MJ</th><th class="num">Spolu</th><th></th><th>Riadok z faktúry</th></tr></thead>
        <tbody>${rows || `<tr><td colspan="7" style="padding:14px 10px;color:var(--muted)">Žiadne položky s EAN.</td></tr>`}</tbody>
      </table></div>
      <div class="foot">
        <span>Do TXT ide <b>${items.length}</b> z ${d.inv.items.length} riadkov</span>
        <span>Spolu <b>${money(FP.total(items))} ${esc(d.inv.currency)}</b></span>
        <span class="status ${d.msgCls || ""}" data-msg>${esc(d.msg || "")}</span>
      </div>
      <details class="preview"><summary>Náhľad TXT presne tak, ako sa uloží</summary>
        <pre class="txt">${ruler()}${esc(FP.toTxt(items, d.inv.currency).replace(/\r/g, ""))}</pre></details>
    </section>`;
  }

  function renderAll() {
    const open = new Set([...list.querySelectorAll("details[open]")].map(x => x.closest(".card").dataset.id));
    list.innerHTML = docs.map(render).join("");
    open.forEach(id => { const el = list.querySelector(`.card[data-id="${id}"] details`); if (el) el.open = true; });
  }

  const docOf = el => docs.find(d => d.id === +el.closest(".card").dataset.id);

  list.addEventListener("change", e => {
    const t = e.target, d = docOf(t); if (!d) return;
    const tr = t.closest("tr[data-n]");
    if (t.type === "checkbox" && tr) { d.inv.items[+tr.dataset.n].on = t.checked; return renderAll(); }
    if (t.matches("[data-cur]")) { d.inv.currency = t.value; return renderAll(); }
    if (t.matches("[data-fname]")) { d.fname = t.value.trim().replace(/\.txt$/i, "") || d.fname; return renderAll(); }
    if (t.dataset.k && tr) {
      const it = d.inv.items[+tr.dataset.n], v = t.value.trim();
      if (t.dataset.k === "ean") {
        if (!/^\d{0,14}$/.test(v)) { t.classList.add("bad"); return; }
        it.ean = v;
      } else {
        const num = FP.toFixed(v.replace(/\s/g, ""));
        if (num === null || num < 0n) { t.classList.add("bad"); return; }
        it[t.dataset.k] = num;
      }
      renderAll();
    }
  });

  list.addEventListener("click", async e => {
    const b = e.target.closest("button"); if (!b) return;
    const d = docOf(b); if (!d) return;
    if (b.hasAttribute("data-remove")) { docs.splice(docs.indexOf(d), 1); return renderAll(); }
    if (b.dataset.skip !== undefined) {
      const ean = d.inv.items[+b.dataset.skip].ean;
      skip.add(ean); store.set("skipEans", [...skip]); refreshSkipBtn();
      docs.forEach(x => x.inv.items.forEach(it => { if (it.ean === ean) it.on = false; }));
      return renderAll();
    }
    const txt = FP.toTxt(activeItems(d), d.inv.currency);
    const say = (m, cls) => { d.msg = m; d.msgCls = cls; const el = b.closest(".card").querySelector("[data-msg]"); el.textContent = m; el.className = "status " + cls; };
    if (b.hasAttribute("data-copy")) {
      try { await navigator.clipboard.writeText(txt); say("Obsah TXT je skopírovaný.", "okm"); }
      catch { const pre = b.closest(".card").querySelector("details"); pre.open = true;
        const r = document.createRange(); r.selectNodeContents(pre.querySelector("pre")); getSelection().removeAllRanges(); getSelection().addRange(r);
        say("Kopírovanie nie je povolené. Náhľad je označený, skopírujte ho cez Ctrl+C.", ""); }
      return;
    }
    if (b.hasAttribute("data-dl")) {
      if (!activeItems(d).length) return say("Nie je zapnutý žiadny riadok.", "err");
      try { await downloads.save({ filename: d.fname + ".txt", data: txt }); say(`Uložené ako ${d.fname}.txt`, "okm"); }
      catch (err) {
        const c = err && err.code;
        say(c === "declined" ? "Ukladanie bolo zrušené." : c === "rate_limited" ? "Chvíľu počkajte a skúste znova." : "Stiahnutie tu nie je dostupné. Použite Kopírovať obsah TXT.", c === "declined" ? "" : "err");
      }
    }
  });

  // Ukážka (vymyslené údaje), kým nenahráte prvú faktúru
  const ex = FP.parsePages([[
    "No  Názov                         EAN             Množstvo  MJ   Cena    Zľava  Cena po zľave  Hodnota",
    " 1  Ukážková bunda XL             8580000000016          3  ks   20,00   10%    18,00          54,00",
    " 2  Ukážkové rukavice             8580000000023         12  pár   2,45   0%      2,45          29,40",
    " 3  Ukážková obuv S3 vel. 43      8580000000030          2  pár  31,50   0%     31,50          63,00",
    " Total:                                                                                146,40 EUR"].join("\n")]);
  docs.push({ id: nextId++, name: "Ukážka – Vzorový dodávateľ", inv: ex, fname: "PPEC260000", example: true, msg: "" });
  renderAll();
})();
