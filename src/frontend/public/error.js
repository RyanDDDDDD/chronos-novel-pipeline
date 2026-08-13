// Cosmetic countdown only -- the actual app-exit timer lives in the Rust side
// (src-tauri/src/lib.rs), started right before this page is navigated to. This
// script never calls back into Tauri; it just mirrors that timer visually.
(function () {
  var seconds = 10;
  var el = document.getElementById("countdown");

  function render() {
    el.textContent = seconds > 0 ? seconds + " 秒后自动关闭…" : "正在关闭…";
  }

  render();
  var timer = setInterval(function () {
    seconds -= 1;
    if (seconds <= 0) {
      clearInterval(timer);
    }
    render();
  }, 1000);
})();
