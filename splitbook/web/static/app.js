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

  // 指定金額：即時顯示分配狀態；總額未手動輸入時以各人加總自動帶入。
  var status = document.querySelector("[data-split-status]");
  if (status) {
    var form = status.closest("form");
    var amount = form.querySelector("input[name=amount]");
    var text = status.querySelector("[data-split-text]");
    var useSum = status.querySelector("[data-split-use-sum]");
    var exacts = form.querySelectorAll("input[name^=x_]");
    var manual = amount.value !== "";
    var toInt = function (v) { return parseInt(v, 10) || 0; };
    var refresh = function () {
      var kind = form.querySelector("input[name=split_kind]:checked");
      var exact = kind && kind.value === "exact";
      amount.required = !exact;
      status.hidden = !exact;
      if (!exact) return;
      var sum = 0;
      exacts.forEach(function (i) { sum += toInt(i.value); });
      if (!manual) amount.value = sum ? sum : "";
      var diff = toInt(amount.value) - sum;
      status.classList.toggle("is-ok", diff === 0);
      status.classList.toggle("is-under", diff > 0);
      status.classList.toggle("is-over", diff < 0);
      useSum.hidden = !manual || diff === 0;
      text.textContent = !manual ? "總額 = 各人加總 $" + sum + "（自動帶入）"
        : diff === 0 ? "已全部分完 $" + sum
        : diff > 0 ? "已分 $" + sum + "，還差 $" + diff
        : "已分 $" + sum + "，超出總額 $" + (-diff);
    };
    amount.addEventListener("input", function () { manual = amount.value !== ""; });
    useSum.addEventListener("click", function () { manual = false; refresh(); });
    form.addEventListener("input", refresh);
    form.addEventListener("change", refresh);
    refresh();
  }
});
