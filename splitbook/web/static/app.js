// HomeBook 漸進增強：買到了 bottom sheet 與清單勾選列。無 JS 時全部功能仍可用。
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
});
