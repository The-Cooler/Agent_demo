// 项目说明弹窗：打开、关闭、点击遮罩关闭、Esc 关闭。
function initAboutModal() {
  const mask = document.getElementById("aboutModal");
  const openBtn = document.getElementById("aboutBtn");
  const closeBtn = document.getElementById("aboutClose");

  function open() {
    mask.hidden = false;
  }

  function close() {
    mask.hidden = true;
  }

  openBtn.addEventListener("click", open);
  closeBtn.addEventListener("click", close);
  mask.addEventListener("click", (event) => {
    if (event.target === mask) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !mask.hidden) close();
  });
}
