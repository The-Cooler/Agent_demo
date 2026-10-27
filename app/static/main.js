// 页面初始化与事件绑定。
function bindEvents() {
  document.getElementById("newSession").addEventListener("click", createSession);
  document.getElementById("send").addEventListener("click", sendMessage);

  const input = document.getElementById("input");
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });
  input.addEventListener("input", (event) => {
    event.target.style.height = "auto";
    event.target.style.height = Math.min(event.target.scrollHeight, 160) + "px";
  });
}

async function init() {
  bindEvents();
  initAboutModal();
  try {
    await loadSessions();
    const first = document.querySelector(".session-item");
    if (first) first.click();
  } catch (err) {
    toast("加载会话失败：" + err.message);
  }
}

init();
