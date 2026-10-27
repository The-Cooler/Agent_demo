// 发送消息、等待 Agent 返回、渲染结果。
let sending = false;

async function sendMessage() {
  if (sending) return;

  const input = document.getElementById("input");
  const content = input.value.trim();
  if (!content) return;

  if (!currentSessionId) {
    toast("请先新建或选择一个会话");
    return;
  }

  const sessionId = currentSessionId;
  sending = true;
  document.getElementById("send").disabled = true;
  input.value = "";
  input.style.height = "auto";

  renderMessage("user", content, null, null);

  const thinking = document.createElement("div");
  thinking.className = "msg assistant";
  thinking.innerHTML = '<div class="thinking">正在思考…</div>';
  const box = document.getElementById("messages");
  box.appendChild(thinking);
  box.scrollTop = box.scrollHeight;

  try {
    const result = await api(`/sessions/${sessionId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    thinking.remove();
    renderMessage("assistant", result.answer, result.trace, null);
    if (result.status !== "success" && result.status !== "max_steps") {
      toast("运行状态：" + result.status);
    }
    await refreshSessionTitle(sessionId);
  } catch (err) {
    thinking.remove();
    toast("发送失败：" + err.message);
  } finally {
    sending = false;
    document.getElementById("send").disabled = false;
    input.focus();
  }
}
