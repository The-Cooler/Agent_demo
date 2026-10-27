// 会话列表：加载、新建、切换、删除。
let currentSessionId = null;

function sessionDisplayTitle(session) {
  return session.title || "未命名会话";
}

async function loadSessions() {
  const sessions = await api("/sessions");
  const box = document.getElementById("sessions");
  box.innerHTML = "";

  if (!sessions.length) {
    const empty = document.createElement("div");
    empty.className = "sessions-empty";
    empty.textContent = "还没有会话";
    box.appendChild(empty);
    return;
  }

  for (const session of sessions) {
    const item = document.createElement("div");
    item.className = "session-item" + (session.id === currentSessionId ? " active" : "");

    const title = document.createElement("span");
    title.className = "title";
    title.textContent = sessionDisplayTitle(session);

    const del = document.createElement("button");
    del.className = "del";
    del.title = "删除会话";
    del.textContent = "×";

    item.appendChild(title);
    item.appendChild(del);
    item.addEventListener("click", () => selectSession(session.id));
    del.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteSession(session.id);
    });
    box.appendChild(item);
  }
}

async function createSession() {
  try {
    const session = await api("/sessions", {
      method: "POST",
      body: JSON.stringify({ title: "" }),
    });
    currentSessionId = session.id;
    await refreshSessionList();
    await selectSession(session.id);
    document.getElementById("input").focus();
  } catch (err) {
    toast("创建失败：" + err.message);
  }
}

async function deleteSession(sessionId) {
  if (!confirm("删除这个会话？会话中的消息和待办都会一起删除。")) return;
  try {
    await api(`/sessions/${sessionId}`, { method: "DELETE" });
    if (sessionId === currentSessionId) {
      currentSessionId = null;
      document.getElementById("sessionTitle").textContent = "未选择会话";
      renderEmpty("新建一个会话，然后输入问题");
    }
    await refreshSessionList();
  } catch (err) {
    toast("删除失败：" + err.message);
  }
}

async function selectSession(sessionId) {
  currentSessionId = sessionId;
  try {
    const session = await api(`/sessions/${sessionId}`);
    document.getElementById("sessionTitle").textContent = sessionDisplayTitle(session);
    await refreshSessionList();

    const messages = await api(`/sessions/${sessionId}/messages`);
    const box = document.getElementById("messages");
    box.innerHTML = "";
    if (!messages.length) {
      renderEmpty("这个会话还没有消息");
      return;
    }
    for (const message of messages) {
      renderMessage(message.role, message.content, message.trace, message.meta_json);
    }
    box.scrollTop = box.scrollHeight;
  } catch (err) {
    toast("加载会话失败：" + err.message);
  }
}

async function refreshSessionList() {
  await loadSessions();
}

// 发送成功后，后端会用首条消息生成会话标题，这里同步更新列表和标题栏。
async function refreshSessionTitle(sessionId) {
  const session = await api(`/sessions/${sessionId}`);
  document.getElementById("sessionTitle").textContent = sessionDisplayTitle(session);
  await refreshSessionList();
}
