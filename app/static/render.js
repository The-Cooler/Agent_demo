// 消息气泡、工具调用记录、执行过程与提示条。
function toast(text) {
  const el = document.getElementById("toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.remove("show"), 2600);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderTrace(trace) {
  const details = document.createElement("details");
  details.className = "trace";
  const summary = document.createElement("summary");
  summary.textContent = `执行过程（${trace.length} 步）`;
  details.appendChild(summary);

  for (const step of trace) {
    const div = document.createElement("div");
    div.className = "step";
    const status = `<span class="status ${step.status}">${step.status}</span>`;
    let html = `<div class="row"><span class="k">步骤</span><span class="v">#${step.step_no} ${status}</span></div>`;
    if (step.thought) {
      html += `<div class="row"><span class="k">思考</span><span class="v">${escapeHtml(step.thought)}</span></div>`;
    }
    if (step.action) {
      const args = escapeHtml(JSON.stringify(step.args || {}));
      html += `<div class="row"><span class="k">调用</span><span class="v">${escapeHtml(step.action)}(${args})</span></div>`;
    }
    if (step.observation) {
      html += `<div class="row"><span class="k">结果</span><span class="v">${escapeHtml(step.observation)}</span></div>`;
    }
    if (step.duration_ms) {
      html += `<div class="row"><span class="k">耗时</span><span class="v">${step.duration_ms} ms</span></div>`;
    }
    div.innerHTML = html;
    details.appendChild(div);
  }
  return details;
}

function renderToolCalls(metaJson) {
  if (!metaJson) return null;
  let meta;
  try {
    meta = JSON.parse(metaJson);
  } catch (e) {
    return null;
  }
  const toolCalls = (meta && meta.tool_calls) || [];
  if (!toolCalls.length) return null;
  const chip = document.createElement("div");
  chip.className = "meta";
  chip.textContent = "调用工具：" + toolCalls.map((t) => t.name).join("、");
  return chip;
}

function renderMessage(role, content, trace, metaJson) {
  const box = document.getElementById("messages");
  const emptyEl = box.querySelector(".empty");
  if (emptyEl) emptyEl.remove();

  const wrap = document.createElement("div");
  wrap.className = "msg " + role;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;
  wrap.appendChild(bubble);

  const chip = renderToolCalls(metaJson);
  if (chip) wrap.appendChild(chip);

  if (trace && trace.length) wrap.appendChild(renderTrace(trace));

  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
  return wrap;
}

function renderEmpty(text) {
  const box = document.getElementById("messages");
  box.innerHTML = `<div class="empty"><strong>开始对话</strong>${escapeHtml(text)}</div>`;
}
