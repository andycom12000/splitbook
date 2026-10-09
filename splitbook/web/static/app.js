// HomeBook 漸進增強：買到了 bottom sheet、清單勾選列、指定金額分配提示。無 JS 時全部功能仍可用。
document.addEventListener("DOMContentLoaded", function () {
  // SSR 以 <dialog open> 呈現 sheet；有 JS 時升級成 modal（背景遮罩 + ESC 關閉）。
  var sheet = document.querySelector("dialog[data-sheet][open]");
  if (sheet && typeof sheet.showModal === "function") {
    sheet.removeAttribute("open");
    sheet.showModal();
    var amt = sheet.querySelector("input[name=amount]");
    if (amt) { amt.focus(); amt.select(); }
    sheet.addEventListener("cancel", function () {
      window.location.replace("/list");
    });
  }

  var buyForm = document.getElementById("buy-form");
  if (buyForm) {
    buyForm.classList.add("js");
    var bar = document.getElementById("buy-bar");
    var count = document.getElementById("buy-count");
    var update = function () {
      var n = buyForm.querySelectorAll("input[name=buy]:checked").length;
      bar.classList.toggle("active", n > 0);
      count.textContent = n > 1 ? "已勾 " + n + " 項，一起結成一筆" : "勾選買到的東西";
    };
    buyForm.addEventListener("change", update);
    update();
  }

  // 記一筆：依拆帳方式即時算出每人分攤（規則同 domain/split.py），指定金額時總額＝各人加總。
  var form = document.querySelector("[data-split-form]");
  if (form) initSplitForm(form);
});

function initSplitForm(form) {
  form.classList.add("js");
  var amount = form.querySelector("input[name=amount]");
  var amountLabel = form.querySelector("[data-amount-label]");
  var badge = form.querySelector("[data-auto-badge]");
  var title = form.querySelector("[data-split-title]");
  var hint = form.querySelector("[data-split-hint]");
  var submit = form.querySelector("[data-submit]");
  var submitLabel = submit.textContent;
  var receiptToggle = form.querySelector("[data-receipt-toggle]");
  var receiptRow = form.querySelector("[data-receipt-row]");
  var receipt = form.querySelector("[data-receipt]");
  var pill = form.querySelector("[data-receipt-pill]");
  var rows = Array.prototype.map.call(form.querySelectorAll("tr[data-member]"), function (tr) {
    var id = parseInt(tr.dataset.member, 10);
    return {
      id: id, tr: tr,
      part: tr.querySelector("input[name=p_" + id + "]"),
      weight: tr.querySelector("input[name=w_" + id + "]"),
      exact: tr.querySelector("input[name=x_" + id + "]"),
      fill: tr.querySelector("[data-fill]"),
      share: tr.querySelector("[data-share]"),
      bar: tr.querySelector("[data-bar]")
    };
  });
  var typedTotal = amount.value;
  var toInt = function (v) { return parseInt(v, 10) || 0; };
  var money = function (n) { return "$" + n.toLocaleString(); };
  var TITLES = { equal: "誰要分", weights: "每人幾份", exact: "每人花了多少" };

  function kind() {
    var r = form.querySelector("input[name=split_kind]:checked");
    return r ? r.value : "equal";
  }
  function payer() {
    var r = form.querySelector("input[name=payer_id]:checked");
    return r ? toInt(r.value) : 0;
  }

  function allocate(k, total) {
    var alloc = {}, ids, n, i;
    if (k === "equal") {
      ids = rows.filter(function (r) { return r.part.checked; }).map(function (r) { return r.id; }).sort(function (a, b) { return a - b; });
      n = ids.length;
      if (!n) return { alloc: alloc, hint: "至少勾一位參與。" };
      var base = Math.floor(total / n), rem = total - base * n;
      var start = ids.indexOf(payer()) >= 0 ? (ids.indexOf(payer()) + 1) % n : 0;
      ids.forEach(function (id) { alloc[id] = base; });
      for (i = 0; i < rem; i++) alloc[ids[(start + i) % n]] += 1;
      return { alloc: alloc, hint: rem ? "除不盡的 $" + rem + " 由付款人的下一位開始，每人多付 1 元。" : n + " 人均分。" };
    }
    if (k === "weights") {
      var w = {};
      rows.forEach(function (r) { var v = toInt(r.weight.value); if (v > 0) w[r.id] = v; });
      ids = Object.keys(w).map(Number);
      var tw = ids.reduce(function (s, id) { return s + w[id]; }, 0);
      if (!tw) return { alloc: alloc, hint: "至少一人份數大於 0。" };
      ids.forEach(function (id) { alloc[id] = Math.floor(total * w[id] / tw); });
      var left = total - ids.reduce(function (s, id) { return s + alloc[id]; }, 0);
      ids.sort(function (a, b) { return ((total * w[b]) % tw) - ((total * w[a]) % tw) || a - b; });
      for (i = 0; i < left; i++) alloc[ids[i]] += 1;
      return { alloc: alloc, hint: "共 " + tw + " 份；份數留白或 0 代表不分攤。" };
    }
    rows.forEach(function (r) { var v = toInt(r.exact.value); if (v) alloc[r.id] = v; });
    return { alloc: alloc, hint: "總額會自動等於各人加總，不需要另外算。" };
  }

  function refresh() {
    var k = kind(), exact = k === "exact";
    var sum = rows.reduce(function (s, r) { return s + toInt(r.exact.value); }, 0);
    amount.readOnly = exact;
    amount.required = !exact;
    badge.hidden = !exact;
    amountLabel.textContent = exact ? "金額（各人加總）" : "金額";
    if (exact) amount.value = sum ? sum : "";
    else if (amount.value !== typedTotal) amount.value = typedTotal;
    var total = toInt(amount.value);
    var res = allocate(k, total);
    title.textContent = TITLES[k];
    hint.textContent = res.hint;

    var checking = exact && receiptToggle.checked;
    receiptRow.hidden = !checking;
    var diff = toInt(receipt.value) - sum;
    pill.className = "pill " + (diff === 0 ? "is-ok" : diff > 0 ? "is-under" : "is-over");
    pill.textContent = diff === 0 ? "對上了" : diff > 0 ? "還差 " + money(diff) : "多了 " + money(-diff);

    rows.forEach(function (r) {
      var a = res.alloc[r.id];
      var inPlay = a !== undefined;
      r.share.textContent = inPlay ? money(a) : "不分攤";
      r.share.classList.toggle("is-out", !inPlay);
      r.bar.style.width = inPlay && total > 0 ? Math.max(0, Math.min(100, a / total * 100)) + "%" : "0";
      r.fill.hidden = !(checking && diff > 0);
      r.fill.textContent = "＋" + money(diff);
    });

    var block = "";
    if (exact) {
      if (!sum) block = "先填每人金額";
      else if (checking && diff > 0) block = "還差 " + money(diff) + " 沒分";
      else if (checking && diff < 0) block = "比收據多 " + money(-diff);
    } else if (total <= 0) block = "先填金額";
    else if (!Object.keys(res.alloc).length) block = "至少一人分攤";
    submit.disabled = !!block;
    var grand = exact ? sum : total;
    submit.textContent = block || submitLabel + (grand ? " " + money(grand) : "");
  }

  amount.addEventListener("input", function () { if (kind() !== "exact") typedTotal = amount.value; });
  receiptToggle.addEventListener("change", function () {
    if (receiptToggle.checked && !receipt.value) receipt.focus();
  });
  rows.forEach(function (r) {
    r.fill.addEventListener("click", function () {
      var diff = toInt(receipt.value) - rows.reduce(function (s, x) { return s + toInt(x.exact.value); }, 0);
      if (diff > 0) { r.exact.value = toInt(r.exact.value) + diff; refresh(); }
    });
  });
  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  form.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !submit.disabled) form.requestSubmit(submit);
  });
  refresh();
}
