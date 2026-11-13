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
        const base = f.name.replace(/\.pdf$/i, "") + "_" + stamp();
        removeExample();
        docs.unshift({ id: nextId++, name: f.name, inv, fname: base, msg: "", loaded: new Date().toLocaleString("sk-SK") });
      } catch (e) {
        docs.unshift({ id: nextId++, name: f.name, inv: { items: [], totals: [], warnings: ["PDF sa nedá prečítať: " + (e.message || e)], currency: "EUR", number: "" }, fname: f.name, msg: "" });
      }
    }
    setStatus(`Spracované: ${pdfs.length} ${pdfs.length === 1 ? "faktúra" : pdfs.length < 5 ? "faktúry" : "faktúr"}.`, "okm");
    renderAll();
  }

  function stamp() {
    const d = new Date(), z = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}_${z(d.getHours())}-${z(d.getMinutes())}`;
  }
  const r2 = v => ((v + (v >= 0n ? 5000n : -5000n)) / 10000n) * 10000n;
  const rowDiff = it => (it.value === undefined ? 0n : r2(it.value) - FP.amount(it));

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
    const items = activeItems(d), chk = FP.totalCheck(d.inv, items);
    const cur = esc(d.inv.currency);
    const warn = [...d.inv.warnings];
    const offItems = d.inv.items.filter(it => !it.on), offSum = FP.total(offItems);
    const orphSum = d.inv.orphans.reduce((s, o) => s + FP.amount(o), 0n);
    const rounding = items.filter(it => rowDiff(it) !== 0n);
    const verified = items.filter(it => it.value !== undefined && rowDiff(it) === 0n).length;
    const absd = v => (v < 0n ? -v : v);
    const explained = chk.ok === false && absd(chk.diff - offSum - orphSum) <= FP.TOLERANCE && (offItems.length || d.inv.orphans.length);
    const state = chk.ok === true ? "ok" : explained ? "explained" : chk.ok === false ? "bad" : "none";
    const kind = o => (/transport|doprav|shipping|freight|delivery|przesy|dostaw|fracht|versand|po[šs]tovn|logist|packing|repack/i.test(o.line) ? "Doprava" : "Riadok bez EAN");
    const chip = state === "ok" ? `<span class="chip ok">Súčet sedí s faktúrou${chk.diff ? ` (rozdiel ${money(chk.diff)} – zaokrúhlenie)` : ""}</span>`
      : state === "explained" ? `<span class="chip ok">Položky aj ceny sedia</span>`
      : state === "bad" ? `<span class="chip bad">Rozdiel ${money(chk.diff)} ${cur}</span>` : `<span class="chip none">Súčet na faktúre nenájdený</span>`;
    const orphRows = d.inv.orphans.map((o, k) => `<li><b>${kind(o)}: ${money(FP.amount(o))} ${cur}</b> (str. ${o.page}) – <span class="src">${esc(o.line)}</span>${o.badEan ? " <b>(EAN má chybnú kontrolnú číslicu)</b>" : ""} <button class="btn mini" type="button" data-orphan="${k}">Pridať do TXT</button></li>`);
    const offRow = offItems.length ? [`<li>Vypnuté riadky: ${offItems.length} ks za <b>${money(offSum)} ${cur}</b></li>`] : [];
    const validLine = `<b>${items.length} položiek s EAN je v poriadku</b>${verified ? ` – pri ${verified === items.length ? "všetkých" : verified} sedí počet × cena so sumou riadku na faktúre` : ""}.`;
    let diag = "";
    if (state === "explained") {
      diag = `<div class="diag good"><div>${validLine}</div>
        <div class="diag-sum"><span>Tovar v TXT <b>${money(chk.sum)}</b></span>${d.inv.orphans.length ? `<span>${d.inv.orphans.every(o => kind(o) === "Doprava") ? "Doprava" : "Bez EAN"} <b>${money(orphSum)}</b></span>` : ""}${offItems.length ? `<span>Vypnuté <b>${money(offSum)}</b></span>` : ""}<span>Spolu na faktúre <b>${money(chk.doc)} ${cur}</b></span></div>
        <div>Rozdiel oproti faktúre tvorí len to, čo do skladu nejde:</div><ul>${orphRows.concat(offRow).join("")}</ul></div>`;
    } else if (state === "bad") {
      const tips = orphRows.concat(offRow);
      if (rounding.length) tips.push(`<li>${rounding.length} riadkov má na faktúre inú sumu ako počet × cena (zaokrúhlenie ceny). Sú v tabuľke označené žlto, spolu ${money(rounding.reduce((s, it) => s + rowDiff(it), 0n))}.</li>`);
      if (!tips.length) tips.push(`<li>Nenašiel som riadok, ktorý by chýbal. Suma na faktúre môže obsahovať DPH alebo zľavu na celý doklad.</li>`);
      diag = `<div class="diag"><div class="diag-sum"><span>Na faktúre <b>${money(chk.doc)}</b></span><span>V TXT <b>${money(chk.sum)}</b></span><span>Rozdiel <b>${money(chk.diff)} ${cur}</b></span></div>
        <div style="font-weight:600">Kde môže byť rozdiel:</div><ul>${tips.join("")}</ul></div>`;
    } else if (state === "ok" && items.length) {
      diag = `<div class="diag good"><div>${validLine} Súčet ${money(chk.sum)} ${cur} sa zhoduje s faktúrou.</div></div>`;
    }
    const rows = d.inv.items.map((it, n) => `
      <tr class="${it.on ? "" : "off"} ${rowDiff(it) !== 0n ? "rd" : ""}" data-n="${n}">
        <td><input type="checkbox" id="on-${d.id}-${n}" ${it.on ? "checked" : ""} aria-label="Zahrnúť riadok"></td>
        <td class="ean"><input type="text" id="ean-${d.id}-${n}" data-k="ean" value="${esc(it.ean)}" inputmode="numeric"></td>
        <td class="num qty"><input type="text" id="qty-${d.id}-${n}" data-k="qty" value="${short(it.qty)}" inputmode="decimal"></td>
        <td class="num price"><input type="text" id="price-${d.id}-${n}" data-k="price" value="${short(it.price)}" inputmode="decimal"></td>
        <td class="num">${money(FP.amount(it))}${rowDiff(it) !== 0n ? `<div class="rdn">na faktúre ${money(r2(it.value))}</div>` : ""}</td>
        <td><button class="btn" type="button" data-skip="${n}" style="padding:2px 8px;font-size:12px" title="Tento EAN pri ďalších faktúrach automaticky odškrtnúť">vždy vynechať</button></td>
        <td class="src" title="${esc(it.line)}">${esc(it.line)}</td>
      </tr>`).join("");
    const canDl = !!downloads;
    return `
    <section class="card${d.example ? " example" : ""}" data-id="${d.id}">
      <div class="card-head">
        <div class="title"><h2>${esc(d.name)}</h2>
          <div class="meta">${d.example ? "Ukážka s vymyslenými údajmi. Zmizne po nahratí prvej faktúry." : `${d.inv.number ? "Doklad " + esc(d.inv.number) + " · " : ""}${d.inv.date ? "Dátum faktúry " + esc(d.inv.date) + " · " : ""}${d.inv.items.length} riadkov s EAN · načítané ${esc(d.loaded || "")}`}</div></div>
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
      ${diag}
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
    if (b.dataset.orphan !== undefined) {
      const o = d.inv.orphans.splice(+b.dataset.orphan, 1)[0];
      d.inv.items.push({ ean: o.code.length <= 14 ? o.code : "", qty: o.qty, price: o.price, value: o.value, line: o.line, page: o.page, on: true });
      return renderAll();
    }
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
