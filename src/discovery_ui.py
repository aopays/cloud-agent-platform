"""Small dependency-free web UI for requirement discovery conversations."""

DISCOVERY_UI = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>需求发现 Agent</title>
  <style>
    :root { color-scheme: light; font-family: Inter, "Microsoft YaHei", sans-serif; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #f4f7fb; color: #172033; }
    main { max-width: 1120px; margin: 28px auto; padding: 0 18px; }
    header { margin-bottom: 18px; }
    h1 { margin: 0 0 8px; font-size: 28px; }
    header p { margin: 0; color: #5d687c; }
    .grid { display: grid; grid-template-columns: 350px 1fr; gap: 18px; }
    .card { background: white; border: 1px solid #dfe5ef; border-radius: 14px;
      box-shadow: 0 7px 24px rgba(30, 50, 80, .06); padding: 18px; }
    label { display: block; font-size: 13px; font-weight: 700; margin: 14px 0 6px; }
    label:first-child { margin-top: 0; }
    input, textarea { width: 100%; border: 1px solid #cbd4e2; border-radius: 9px;
      padding: 10px 11px; font: inherit; background: #fbfcfe; }
    textarea { min-height: 105px; resize: vertical; }
    button { border: 0; border-radius: 9px; padding: 10px 14px; font-weight: 700;
      cursor: pointer; background: #155eef; color: white; }
    button.secondary { background: #e9eef7; color: #22304a; }
    button.success { background: #087a55; }
    button:disabled { cursor: not-allowed; opacity: .5; }
    .buttons { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
    #chat { min-height: 470px; max-height: 620px; overflow-y: auto; padding-right: 5px; }
    .message { max-width: 88%; margin: 10px 0; padding: 11px 13px; border-radius: 12px;
      line-height: 1.65; white-space: pre-wrap; }
    .assistant { background: #eef4ff; border: 1px solid #d5e3ff; }
    .user { margin-left: auto; background: #eaf8f2; border: 1px solid #cbeadd; }
    .meta { color: #69768b; font-size: 12px; margin-bottom: 5px; }
    .status { display: inline-block; margin-top: 10px; padding: 4px 9px; border-radius: 999px;
      background: #eef1f6; color: #4d5970; font-size: 12px; font-weight: 700; }
    #answer { min-height: 90px; }
    #error { display: none; margin-top: 10px; padding: 10px; color: #9d1c20;
      background: #fff0f0; border-radius: 8px; white-space: pre-wrap; }
    #reportPanel { display: none; margin-top: 18px; }
    #report { max-height: 460px; overflow: auto; white-space: pre-wrap; line-height: 1.6;
      padding: 14px; background: #101827; color: #dbe6f5; border-radius: 10px; }
    @media (max-width: 820px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<main>
  <header>
    <h1>需求发现 Agent</h1>
    <p>输入模糊需求，经过多轮澄清后生成可下载的软件设计报告。</p>
  </header>
  <div class="grid">
    <section class="card">
      <label for="token">本地访问令牌</label>
      <input id="token" type="password" value="local-demo-token" autocomplete="off">
      <label for="requirement">模糊需求</label>
      <textarea id="requirement">设计一个物流司机排班用的软件</textarea>
      <label for="context">已知前置条件（可选）</label>
      <textarea id="context"
        placeholder="例如：6 周交付、先做 Web 管理端、约 100 名司机"></textarea>
      <div class="buttons">
        <button id="start">开始需求挖掘</button>
        <button id="reset" class="secondary">新建会话</button>
      </div>
      <div id="status" class="status">尚未开始</div>
      <div id="error"></div>
    </section>
    <section class="card">
      <div id="chat"><div class="meta">Agent 的问题和你的回答会显示在这里。</div></div>
      <label for="answer">回答 Agent</label>
      <textarea id="answer" disabled placeholder="先点击左侧“开始需求挖掘”"></textarea>
      <div class="buttons">
        <button id="send" disabled>发送回答</button>
        <button id="finalize" class="success" disabled>生成软件设计报告</button>
      </div>
    </section>
  </div>
  <section id="reportPanel" class="card">
    <h2>软件设计报告</h2>
    <div class="buttons"><button id="download" class="success">下载 Markdown 报告</button></div>
    <pre id="report"></pre>
  </section>
</main>
<script>
  let session = null;
  const byId = id => document.getElementById(id);
  const headers = () => ({
    "Authorization": `Bearer ${byId("token").value.trim()}`,
    "Content-Type": "application/json"
  });
  function setBusy(value) {
    byId("start").disabled = value || !!session;
    byId("send").disabled = value || !session || session.status === "FINALIZED";
    byId("finalize").disabled = value || !session || session.status === "FINALIZED";
    byId("answer").disabled = value || !session || session.status === "FINALIZED";
  }
  function showError(message) {
    byId("error").style.display = message ? "block" : "none";
    byId("error").textContent = message || "";
  }
  async function request(path, options = {}) {
    showError("");
    const response = await fetch(path, {...options, headers: headers()});
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.message || `请求失败：HTTP ${response.status}`);
    return data;
  }
  function render() {
    if (!session) return;
    byId("status").textContent = `${session.status} · 已回答 ${session.currentRound} 轮`;
    byId("chat").innerHTML = session.messages.map(item => `
      <div class="message ${item.role}">
        <div class="meta">${item.role === "user" ? "你" : "需求发现 Agent"}</div>
        ${escapeHtml(item.content)}
      </div>`).join("");
    byId("chat").scrollTop = byId("chat").scrollHeight;
    if (session.report) {
      byId("reportPanel").style.display = "block";
      byId("report").textContent = session.report;
    }
    setBusy(false);
  }
  function escapeHtml(value) {
    const element = document.createElement("div");
    element.textContent = value;
    return element.innerHTML;
  }
  byId("start").onclick = async () => {
    const requirement = byId("requirement").value.trim();
    if (!requirement) return showError("请先输入一个需求。");
    setBusy(true);
    try {
      session = await request("/v1/discovery-sessions", {
        method: "POST",
        body: JSON.stringify({requirement, context: byId("context").value.trim() || null})
      });
      render();
    } catch (error) { showError(error.message); setBusy(false); }
  };
  byId("send").onclick = async () => {
    const content = byId("answer").value.trim();
    if (!content) return showError("请先填写回答。");
    setBusy(true);
    try {
      session = await request(`/v1/discovery-sessions/${session.id}/messages`, {
        method: "POST", body: JSON.stringify({content})
      });
      byId("answer").value = "";
      render();
    } catch (error) { showError(error.message); setBusy(false); }
  };
  byId("finalize").onclick = async () => {
    setBusy(true);
    try {
      session = await request(`/v1/discovery-sessions/${session.id}/finalize`, {method: "POST"});
      render();
      byId("reportPanel").scrollIntoView({behavior: "smooth"});
    } catch (error) { showError(error.message); setBusy(false); }
  };
  byId("download").onclick = async () => {
    try {
      const response = await fetch(`/v1/discovery-sessions/${session.id}/report`, {
        headers: {"Authorization": `Bearer ${byId("token").value.trim()}`}
      });
      if (!response.ok) throw new Error(`下载失败：HTTP ${response.status}`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = "software-design-report.md"; link.click();
      URL.revokeObjectURL(url);
    } catch (error) { showError(error.message); }
  };
  byId("reset").onclick = () => location.reload();
</script>
</body>
</html>"""
