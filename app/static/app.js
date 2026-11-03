const byId = (id) => document.getElementById(id);
const state = {sessionId: null, assets: [], busy: false, results: 0, source: null, pending: null, view: "home", folderPicking: false, flowConfig: null, flowRun: false, runId: null};
const toolNames = {detect_bubbles: "YOLO · 单图气泡检测", batch_detect_bubbles: "YOLO · 实验批次分析", inspect_csv: "CSV · 数据结构检查", analyze_csv: "CSV · 科研数据分析", calculate_bubble_statistics: "气泡尺寸 · 统计分析", compare_experiments: "实验结果 · 交叉比较", calculate_bubble_velocity: "气泡运动 · 速度计算", list_files: "实验目录 · 文件检查", analyze_flow_warning: "流态监测 · 基线与持续异常分析", inspect_flow_event: "流态监测 · 事件依据查询"};
const flowStateLabels = {normal: "正常", attention: "关注", warning: "预警", insufficient: "数据不足"};
const flowEndLabels = {recovered: "指标已恢复", data_gap: "数据中断", stopped: "用户停止", end_of_sequence: "序列结束"};
const examplePrompts = {image: "检测这张气泡图片，统计气泡数量、平均直径和尺寸分布。", folder: "分析这个文件夹里的全部气泡图片，统计尺寸分布并导出 CSV。", csv: "分析这个合成示例 CSV，看看气速和气泡直径的关系，并比较不同工况。"};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    const detail = typeof data.detail === "string" ? data.detail : "请求参数不正确，请检查输入。";
    throw new Error(detail || "请求失败，请检查服务。");
  }
  return data;
}

function post(path, data) {
  return api(path, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(data)});
}

function toast(message) {
  byId("toast").textContent = message;
  byId("toast").hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => { byId("toast").hidden = true; }, 6500);
}

function showView(view) {
  const home = view === "home";
  const flow = view === "flow";
  state.view = home ? "home" : flow ? "flow" : "workbench";
  byId("home-view").hidden = !home;
  byId("workbench-view").hidden = home || flow;
  byId("flow-view").hidden = !flow;
  byId("view-title").textContent = home ? "首页" : flow ? "流态监测预警" : view === "csv" ? "实验数据分析" : "实验分析工作台";
  document.querySelectorAll(".nav-item[data-nav]").forEach((button) => {
    const active = button.dataset.nav === (home ? "home" : flow ? "flow" : view === "csv" ? "csv" : "workbench");
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  if (!home && !flow) byId("message-input").focus({preventScroll: true});
  window.scrollTo({top: 0, behavior: "instant"});
}

async function pickFolderSelection() {
  if (window.bifbDesktopReady) {
    const desktop = await window.bifbDesktopReady;
    return JSON.parse(await new Promise((resolve) => desktop.chooseFolder(resolve)));
  }
  return api("/api/dialog/folder");
}

async function chooseFolder() {
  if (state.busy || state.folderPicking) return toast("请先完成当前分析或文件夹选择。");
  if (!state.sessionId) return toast("正在连接本地服务，请稍候。");
  state.folderPicking = true;
  byId("browse-folder").disabled = true;
  byId("home-folder").disabled = true;
  try {
    const selected = await pickFolderSelection();
    if (selected.cancelled || !selected.path) return;
    const asset = await post(`/api/sessions/${state.sessionId}/paths`, {path: selected.path});
    addAssets([asset]);
    if (!byId("home-input").value.trim()) byId("home-input").value = examplePrompts.folder;
    toast("已读取本地文件夹，图片无需上传。输入任务即可开始分析。");
  } catch (error) {
    toast(error.message);
  } finally {
    state.folderPicking = false;
    byId("browse-folder").disabled = state.busy;
    byId("home-folder").disabled = state.busy;
  }
}

function setBusy(busy) {
  state.busy = busy;
  byId("send-button").disabled = busy;
  byId("home-send").disabled = busy;
  byId("home-folder").disabled = busy || state.folderPicking;
  byId("new-session").disabled = busy;
  byId("settings-open").disabled = busy;
  byId("file-input").disabled = busy;
  byId("flow-fields").disabled = busy;
  byId("flow-stop").hidden = !busy;
  byId("chat-stop").hidden = !busy;
  byId("flow-stop").disabled = false;
  byId("chat-stop").disabled = false;
  byId("browse-folder").disabled = busy || state.folderPicking;
  byId("activity-dot").classList.toggle("busy", busy);
  byId("activity-state").textContent = busy ? "Agent 正在行动" : "行动过程可追溯";
  byId("composer-context").textContent = busy ? "正在分析，请稍候…" : "支持多轮实验分析";
}

function inlineText(target, text) {
  for (const token of text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)) {
    if (token.startsWith("**") && token.endsWith("**")) target.append(element("strong", "", token.slice(2, -2)));
    else if (token.startsWith("`") && token.endsWith("`")) target.append(element("code", "", token.slice(1, -1)));
    else target.append(document.createTextNode(token));
  }
}

function renderMarkdown(target, text) {
  const lines = String(text).split("\n");
  let list = null;
  let table = null;
  for (const line of lines) {
    if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
      const cells = line.trim().slice(1, -1).split("|").map((cell) => cell.trim());
      if (cells.every((cell) => /^:?-+:?$/.test(cell))) continue;
      if (!table) { table = element("table"); target.append(table); }
      const row = element("tr");
      for (const cell of cells) { const node = element(table.children.length ? "td" : "th"); inlineText(node, cell); row.append(node); }
      table.append(row);
      continue;
    }
    table = null;
    if (/^\s*[-*]\s+/.test(line)) {
      if (!list) { list = element("ul"); target.append(list); }
      const item = element("li"); inlineText(item, line.replace(/^\s*[-*]\s+/, "")); list.append(item);
      continue;
    }
    list = null;
    if (!line.trim()) continue;
    const heading = /^#{1,6}\s+/.test(line);
    const node = element(heading ? "h3" : "p");
    inlineText(node, heading ? line.replace(/^#{1,6}\s+/, "") : line);
    target.append(node);
  }
}

function addMessage(role, text, extra = "") {
  byId("welcome")?.remove();
  const node = element("article", `chat-message ${role} ${extra}`);
  node.append(element("div", "message-label", role === "user" ? "你 · 研究任务" : "BIFB · 科研助手"));
  const body = element("div", "message-body");
  renderMarkdown(body, text);
  node.append(body);
  byId("messages").append(node);
  byId("messages").scrollTop = byId("messages").scrollHeight;
  return node;
}

function safeArtifactUrl(url) { return typeof url === "string" && url.startsWith("/artifacts/") && !url.includes("..") ? url : null; }

function appendArtifacts(target, artifacts = []) {
  const images = element("div", "artifact-grid");
  const links = element("div", "artifact-links");
  for (const artifact of artifacts) {
    const url = safeArtifactUrl(artifact.url);
    if (!url) continue;
    if (artifact.kind === "image") {
      const figure = element("figure", "artifact-image");
      const image = element("img"); image.src = url; image.alt = artifact.title; image.loading = "lazy";
      image.tabIndex = 0;
      const expand = () => { byId("expanded-image").src = url; byId("expanded-image").alt = artifact.title; byId("image-dialog").showModal(); };
      image.addEventListener("click", expand);
      image.addEventListener("keydown", (event) => { if (event.key === "Enter") expand(); });
      figure.append(image, element("figcaption", "", artifact.title)); images.append(figure);
    } else {
      const link = element("a", "artifact-link", "↓ " + artifact.title); link.href = url; link.download = ""; links.append(link);
    }
  }
  if (images.children.length) target.append(images);
  if (links.children.length) target.append(links);
}

function formatNumber(value, decimals = 2) { return value === null || value === undefined ? "—" : Number(value).toLocaleString("zh-CN", {maximumFractionDigits: decimals}); }

function addResult(result, tool) {
  if (result.status === "error") return;
  if (result.kind === "flow_warning") renderFlowResult(result);
  byId("result-empty")?.remove();
  const card = element("article", "result-card");
  const header = element("div", "result-card-header");
  header.append(element("div", "result-badge", result.status === "partial" ? "部分完成" : "已计算"), element("h3", "", toolNames[tool] || tool), element("span", "", "#" + (result.result_id || "")));
  card.append(header);
  let metrics = [];
  if (result.kind === "flow_warning") metrics = [[result.processed_frames, "待测帧数"], [result.window_count, "时间窗口数"], [result.event_count, "预警事件数"]];
  else if ("bubble_count" in result) metrics = [[result.bubble_count, result.image_count ? "累计气泡检测次数" : "气泡数量"], [result.statistics?.mean, `平均等效直径 / ${result.unit}`], [result.mean_confidence === null ? null : result.mean_confidence * 100, "平均置信度 / %"]];
  else if (result.row_count !== undefined) metrics = [[result.row_count, "数据行数"], [result.columns?.length, "数据列数"], [result.correlation?.pearson_r, "Pearson 相关系数 r"]];
  else if (result.source_result_id) metrics = [[result.statistics?.count, "测量样本数"], [result.statistics?.mean, `平均直径 / ${result.unit}`], [result.statistics?.std, "样本标准差"]];
  else if (tool === "compare_experiments") metrics = [[result.left?.mean, `左侧均值 / ${result.left?.unit}`], [result.right?.mean, `右侧均值 / ${result.right?.unit}`], [result.mean_difference_right_minus_left, "均值差 / 右 − 左"]];
  else if (tool === "calculate_bubble_velocity") metrics = [[result.speed, `速度 / ${result.unit}`], [result.vx, "水平方向"], [result.vy, "竖直方向"]];
  if (metrics.length) {
    const grid = element("div", "result-metrics");
    for (const [value, label] of metrics) { const metric = element("div", "metric"); metric.append(element("strong", "", formatNumber(value, label.includes("Pearson") ? 3 : 2)), element("span", "", label)); grid.append(metric); }
    card.append(grid);
  }
  appendArtifacts(card, result.artifacts);
  if (result.limitations?.length) card.append(element("div", "result-limitation", result.limitations.join(" ")));
  const details = element("details", "result-details");
  details.append(element("summary", "", "查看结构化结果与计算依据"), element("pre", "", JSON.stringify(result, null, 2)));
  card.append(details); byId("results").prepend(card);
  state.results += 1; byId("result-count").textContent = state.results;
  byId("result-state").textContent = "结果已保存 · 可下载与复核";
}

function activity(event) {
  byId("activity").querySelector(".activity-empty")?.remove();
  const isError = event.type === "error" || event.type === "tool_error" || event.result?.status === "error";
  const row = element("div", `activity-row${isError ? " error" : ""}`);
  const content = element("div", "activity-content");
  content.append(element("div", "", event.type === "tool_start" ? (toolNames[event.tool] || event.tool) : event.message));
  const detail = event.arguments || event.result;
  if (detail) { const disclosure = element("details"); disclosure.append(element("summary", "", event.arguments ? "调用参数" : `工具返回 · ${event.elapsed_seconds ?? 0}s`), element("pre", "", JSON.stringify(detail, null, 2))); content.append(disclosure); }
  row.append(element("span", "activity-time", event.time), element("span", "activity-symbol", isError ? "!" : event.type === "tool_result" ? "✓" : "·"), content);
  byId("activity").append(row); byId("activity").scrollTop = byId("activity").scrollHeight;
}

function connectEvents(runId) {
  state.runId = runId;
  sessionStorage.setItem("bifb-run", runId);
  if (state.flowRun) sessionStorage.setItem("bifb-flow-run", runId);
  state.source?.close();
  state.source = new EventSource(`/api/runs/${runId}/events`);
  const seen = new Set();
  state.source.onmessage = (received) => {
    const event = JSON.parse(received.data);
    if (seen.has(event.id)) return;
    seen.add(event.id);
    if (event.type === "flow_window") renderFlowWindow(event.window);
    if (state.flowRun && ["status", "thinking", "progress"].includes(event.type)) byId("flow-progress").textContent = event.message;
    if (event.type !== "final" && event.type !== "done") activity(event);
    if (event.type === "tool_result") addResult(event.result, event.tool);
    if (event.type === "final") { state.pending?.remove(); state.pending = null; const message = addMessage("assistant", event.message); appendArtifacts(message, event.artifacts); if (state.flowRun) { byId("flow-explanation").replaceChildren(); renderMarkdown(byId("flow-explanation"), event.message); appendArtifacts(byId("flow-explanation"), event.artifacts); } }
    if (event.type === "error") { state.pending?.remove(); state.pending = null; addMessage("assistant", event.message, "error"); if (state.flowRun) { byId("flow-explanation").textContent = event.message + " 已生成的工具结果可在下方查看。"; byId("flow-progress").textContent = "本轮分析未全部完成"; } }
    if (event.type === "done") { state.source.close(); state.source = null; sessionStorage.removeItem("bifb-run"); sessionStorage.removeItem("bifb-flow-run"); state.pending?.remove(); setBusy(false); if (state.flowRun && event.success) byId("flow-progress").textContent = "本轮监测与状态解释已完成"; state.runId = null; }
  };
  state.source.onerror = () => {
    toast("连接暂时中断，正在尝试恢复行动记录。");
  };
}

async function submitTask(event) {
  event.preventDefault();
  const message = byId("message-input").value.trim();
  if (!message || state.busy) return;
  if (!state.sessionId) return toast("正在连接本地服务，请稍候。");
  showView("workbench");
  state.flowRun = false;
  setBusy(true);
  try {
    const data = await post(`/api/sessions/${state.sessionId}/chat`, {message});
    byId("home-input").value = "";
    addMessage("user", message); byId("message-input").value = "";
    state.pending = addMessage("assistant", "正在理解任务并组织分析…", "pending");
    connectEvents(data.run_id);
  } catch (error) { setBusy(false); toast(error.message); }
}

function renderAssets() {
  byId("source-list").replaceChildren();
  byId("asset-count").textContent = state.assets.length;
  byId("home-asset-count").textContent = state.assets.length ? `已添加 ${state.assets.length} 个数据源` : "尚未添加数据";
  if (!state.assets.length) byId("source-list").append(element("div", "source-empty", "尚未添加数据源"));
  for (const asset of state.assets) {
    const node = element("div", "asset"); node.title = asset.path;
    const info = element("div", "asset-info"); info.append(element("strong", "", asset.name), element("span", "", {image: "图像 · 已就绪", csv: "CSV · 已就绪", folder: "文件夹 · 递归分析", video: "视频 · 本地直读"}[asset.kind]));
    const remove = element("button", "", "×"); remove.title = "移除数据源"; remove.setAttribute("aria-label", `移除 ${asset.name}`);
    remove.addEventListener("click", async () => { if (state.busy) return toast("请等待当前分析结束。"); try { await api(`/api/sessions/${state.sessionId}/assets/${asset.id}`, {method: "DELETE"}); state.assets = state.assets.filter((item) => item.id !== asset.id); renderAssets(); } catch (error) { toast(error.message); } });
    node.append(element("span", "asset-icon", {image: "IMG", csv: "CSV", folder: "DIR", video: "VID"}[asset.kind]), info, remove); byId("source-list").append(node);
  }
}

function addAssets(assets) {
  for (const asset of assets) if (!state.assets.some((item) => item.id === asset.id)) state.assets.push(asset);
  renderAssets();
  const preview = assets.find((asset) => asset.kind === "image");
  if (preview && !state.results) {
    byId("result-empty")?.remove(); byId("results").querySelector(".source-preview")?.parentElement.remove();
    const card = element("article", "result-card"); const header = element("div", "result-card-header");
    header.append(element("div", "result-badge", "原始数据"), element("h3", "", preview.name));
    const area = element("div", "source-preview"); const image = element("img"); image.alt = preview.name; image.src = `/api/sessions/${state.sessionId}/assets/${preview.id}/preview`; area.append(image);
    card.append(header, area); byId("results").append(card); byId("result-state").textContent = "数据已就绪 · 请描述研究任务";
  }
}

async function upload(files, folder = false) {
  if (state.busy) return toast("请等待当前分析结束后添加文件。");
  if (!state.sessionId) return toast("正在连接本地服务，请稍候。");
  if ([...files].some((file) => /\.(mp4|avi|mov|mkv)$/i.test(file.name))) return toast("视频请在流态监测页面填写本地文件路径，无需上传。");
  if ([...files].some((file) => /\.(pdf|docx?|txt|md)$/i.test(file.name))) return toast("文献知识库功能正在推进中。");
  const supported = [...files].filter((file) => /\.(jpe?g|png|tiff?|bmp|webp|csv)$/i.test(file.name));
  if (!supported.length) return toast("请选择图片或 CSV 文件。");
  if (supported.some((file) => file.size > 50 * 1024 * 1024)) return toast("单个文件不能超过 50 MB，大文件请用本地路径。");
  const body = new FormData();
  for (const file of supported) body.append("files", file, folder ? file.webkitRelativePath || file.name : file.name);
  try { toast("正在上传实验数据…"); const data = await api(`/api/sessions/${state.sessionId}/uploads?folder=${folder}`, {method: "POST", body}); addAssets(data.assets); toast(`已添加 ${supported.length} 个文件，可以开始提问。`); } catch (error) { toast(error.message); }
}

async function refreshSettings() {
  const settings = await api("/api/settings"); state.settings = settings;
  const badge = byId("system-status"); badge.replaceChildren(element("i"), document.createTextNode(settings.llm_ready ? "本地服务已就绪" : "待配置 LLM")); badge.classList.toggle("ready", settings.llm_ready);
  byId("calibration-label").textContent = settings.mm_per_pixel ? `空间标定 · ${settings.mm_per_pixel} mm / px` : "未标定 · 图像尺寸以 px 显示";
  if (!state.flowConfig && !byId("flow-form").elements.mm_per_pixel.value && settings.mm_per_pixel) byId("flow-form").elements.mm_per_pixel.value = settings.mm_per_pixel;
  return settings;
}

async function openSettings() {
  try {
    const settings = await refreshSettings();
    const form = byId("settings-form");
    for (const [key, value] of Object.entries(settings)) if (form.elements.namedItem(key)) form.elements.namedItem(key).value = value ?? "";
    form.elements.llm_api_key.value = ""; form.elements.clear_api_key.checked = false;
    form.elements.llm_api_key.placeholder = settings.has_api_key ? "已保存，留空保持不变" : "输入 API Key";
    byId("settings-feedback").textContent = settings.model_exists && settings.tracker_exists ? "已找到 YOLOTracker 与模型权重。" : "请检查 YOLOTracker 与气泡模型路径。";
    byId("settings-dialog").showModal();
  } catch (error) { toast(error.message); }
}

async function saveSettings(test = false) {
  const form = byId("settings-form");
  if (!form.reportValidity()) return;
  const values = Object.fromEntries(new FormData(form));
  values.confidence = Number(values.confidence);
  values.mm_per_pixel = values.mm_per_pixel.trim() ? Number(values.mm_per_pixel) : null;
  values.clear_api_key = form.elements.clear_api_key.checked;
  if (!values.llm_api_key) delete values.llm_api_key;
  const buttons = [...form.querySelectorAll(".dialog-actions button")]; buttons.forEach((button) => { button.disabled = true; });
  try {
    await post("/api/settings", values); form.elements.llm_api_key.value = ""; await refreshSettings();
    if (test) { byId("settings-feedback").textContent = "配置已保存，正在测试真实 API 与 Tool Calling…"; const result = await post("/api/settings/test", {}); byId("settings-feedback").textContent = result.message; }
    else { byId("settings-dialog").close(); toast("配置已保存。"); }
  } catch (error) { byId("settings-feedback").textContent = error.message; }
  finally { buttons.forEach((button) => { button.disabled = false; }); }
}

async function fetchModels() {
  const form = byId("settings-form");
  const baseUrl = form.elements.llm_base_url.value.trim();
  const apiKey = form.elements.llm_api_key.value;
  if (!baseUrl) { byId("settings-feedback").textContent = "请先填写 API Base URL。"; return; }
  const button = byId("fetch-models");
  button.disabled = true;
  byId("settings-feedback").textContent = "正在从 /models 获取模型列表…";
  try {
    const data = await post("/api/settings/models", {llm_base_url: baseUrl, llm_api_key: apiKey});
    const datalist = byId("llm-model-options");
    datalist.replaceChildren(...data.models.map((model) => { const option = element("option"); option.value = model; return option; }));
    if (!form.elements.llm_model.value) form.elements.llm_model.value = data.models[0];
    byId("settings-feedback").textContent = `已获取 ${data.count} 个模型，请选择或填写模型名称。`;
  } catch (error) {
    byId("settings-feedback").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function initialize() {
  await refreshSettings();
  const previous = sessionStorage.getItem("bifb-session");
  let session = null;
  if (previous) { try { session = await api(`/api/sessions/${previous}`); } catch { sessionStorage.removeItem("bifb-run"); } }
  if (!session) session = await post("/api/sessions", {});
  state.sessionId = session.session_id; sessionStorage.setItem("bifb-session", state.sessionId);
  state.assets = session.assets || []; renderAssets();
  if (session.flow_config) {
    state.flowConfig = session.flow_config;
    for (const [key, value] of Object.entries(session.flow_config)) {
      const input = byId("flow-form").elements.namedItem(key);
      if (input) { if (input.type === "checkbox") input.checked = Boolean(value); else input.value = value; }
    }
  }
  for (const message of session.history || []) addMessage(message.role, message.content);
  const activeRun = sessionStorage.getItem("bifb-run");
  if (activeRun) { state.flowRun = sessionStorage.getItem("bifb-flow-run") === activeRun; if (state.flowRun) showView("flow"); setBusy(true); connectEvents(activeRun); }
}

function renderFlowWindow(window) {
  const metrics = window.metrics;
  const descriptions = {
    appearance: `面积 ${formatNumber(metrics.area_ratio)}% · 每帧数量均值 ${formatNumber(metrics.bubble_count)}`,
    size: `大泡比例 ${formatNumber(metrics.large_fraction === null ? null : metrics.large_fraction * 100)}% · D90 ${formatNumber(metrics.d90)} mm`,
    motion: `向上速度 ${formatNumber(metrics.rise_median)} mm/s · 下行 ${formatNumber(metrics.down_fraction === null ? null : metrics.down_fraction * 100)}%`
  };
  for (const group of ["appearance", "size", "motion"]) {
    const panel = byId("flow-state-" + group);
    panel.dataset.state = window.groups[group].state;
    panel.querySelector("strong").textContent = flowStateLabels[window.groups[group].state];
    panel.querySelector("p").textContent = descriptions[group] + "；" + window.groups[group].reason;
  }
  byId("flow-progress").textContent = `${formatNumber(window.start_time)}–${formatNumber(window.end_time)} s · ${flowStateLabels[window.state]} · 有效覆盖 ${formatNumber(window.valid_fraction * 100)}%`;
}

function renderFlowResult(result) {
  state.flowRun = true;
  if (result.latest_window) renderFlowWindow(result.latest_window);
  else for (const group of ["appearance", "size", "motion"]) { const panel = byId("flow-state-" + group); panel.dataset.state = "insufficient"; panel.querySelector("strong").textContent = "数据不足"; panel.querySelector("p").textContent = "未形成有效监测窗口"; }
  const card = element("article", "result-card");
  const header = element("div", "result-card-header");
  header.append(element("div", "result-badge", result.stopped ? "已停止 · 部分结果" : "计算完成"), element("h3", "", "监测依据与预警事件"), element("span", "", "#" + result.result_id));
  card.append(header);
  const metrics = element("div", "result-metrics");
  for (const [value, label] of [[result.baseline_frames, "基线帧数"], [result.processed_frames, "待测帧数"], [result.event_count, "预警事件数"]]) {
    const item = element("div", "metric"); item.append(element("strong", "", formatNumber(value)), element("span", "", label)); metrics.append(item);
  }
  card.append(metrics);
  const countText = Object.entries(result.window_state_counts).map(([label, count]) => `${flowStateLabels[label]} ${count} 窗口`).join(" · ");
  card.append(element("p", "flow-result-note", `末窗口：${flowStateLabels[result.latest_state]}。${countText || "尚无窗口"}。没有预警事件不等于数据充分或流动正常。`));
  const eventList = (result.events || []).filter((event) => event.id !== undefined);
  if (eventList.length) {
    const container = element("div", "flow-event-table"); const table = element("table"); const heading = element("tr");
    ["事件", "起始 → 触发 → 结束 (s)", "原因与结束方式", "证据"].forEach((text) => heading.append(element("th", "", text))); table.append(heading);
    for (const event of eventList) {
      const row = element("tr");
      row.append(element("td", "", `${event.id} · ${event.group_label}`), element("td", "", [event.start_time, event.trigger_time, event.end_time].map((value) => formatNumber(value)).join(" → ")),
        element("td", "", event.reason + "；" + (flowEndLabels[event.end_reason] || "尚未结束")));
      const evidence = element("td"); const url = safeArtifactUrl(event.evidence?.url);
      if (url) { const button = element("button", "event-evidence", `第 ${event.evidence_frame} 帧`); button.addEventListener("click", () => { byId("expanded-image").src = url; byId("expanded-image").alt = `事件 ${event.id} 触发证据`; byId("image-dialog").showModal(); }); evidence.append(button); }
      row.append(evidence); table.append(row);
    }
    container.append(table); card.append(container);
    if (result.event_count > eventList.length) card.append(element("p", "flow-result-note", "页面展示部分事件，全部事件见下方 CSV / JSON。"));
  }
  appendArtifacts(card, result.artifacts);
  card.append(element("p", "result-limitation", result.limitations.join(" ")));
  const details = element("details", "result-details"); details.append(element("summary", "", "查看基线、质量与全部指标摘要"), element("pre", "", JSON.stringify(result, null, 2))); card.append(details);
  byId("flow-output").prepend(card);
  byId("flow-explanation").textContent = result.stopped ? "任务已停止，已完成结果见下方。" : "专业工具已完成计算，LLM 正在根据真实指标和事件生成简要解释…";
}

async function startFlow(event) {
  event.preventDefault();
  if (state.busy || !state.sessionId) return toast("请等待服务连接或当前任务结束。");
  const form = byId("flow-form"); if (!form.reportValidity()) return;
  const raw = Object.fromEntries(new FormData(form));
  const message = raw.analysis_request.trim() || "请按已确认的流态配置执行监测，简单分析气泡出现量、大气泡变化和运动状态，列出异常时段、依据和数据局限。";
  delete raw.analysis_request;
  const payload = {};
  for (const [key, value] of Object.entries(raw)) payload[key] = ["baseline_path", "input_path"].includes(key) ? value.trim() : ["normal_baseline_confirmed", "acquisition_confirmed"].includes(key) ? true : Number(value);
  try {
    setBusy(true);
    const data = await post(`/api/sessions/${state.sessionId}/flow-config`, payload);
    state.flowConfig = data.flow_config; addAssets(data.assets);
    byId("flow-config-note").textContent = `配置已确认 · 每窗口 ${state.flowConfig.frames_per_window} 帧，基线至少 ${state.flowConfig.frames_per_window * 3} 帧。`;
    const run = await post(`/api/sessions/${state.sessionId}/chat`, {message, flow_config_id: state.flowConfig.config_id});
    state.flowRun = true;
    byId("flow-output").replaceChildren();
    byId("flow-explanation").textContent = "Agent 正在检查任务并选择流态监测工具…";
    byId("flow-progress").textContent = "正在建立正常基线…";
    for (const group of ["appearance", "size", "motion"]) { const panel = byId("flow-state-" + group); panel.dataset.state = "insufficient"; panel.querySelector("strong").textContent = "待分析"; panel.querySelector("p").textContent = "正在建立正常基线"; }
    addMessage("user", message); state.pending = addMessage("assistant", "正在执行流态监测…", "pending");
    connectEvents(run.run_id);
  } catch (error) { setBusy(false); byId("flow-progress").textContent = error.message; toast(error.message); }
}

async function stopAnalysis() {
  if (!state.runId || !state.busy) return;
  byId("flow-stop").disabled = true; byId("chat-stop").disabled = true;
  try { await post(`/api/sessions/${state.sessionId}/runs/${state.runId}/stop`, {}); toast("正在停止并保存已经完成的结果。"); }
  catch (error) { toast(error.message); byId("flow-stop").disabled = false; byId("chat-stop").disabled = false; }
}

byId("chat-form").addEventListener("submit", submitTask);
byId("message-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); byId("chat-form").requestSubmit(); } });
byId("file-input").addEventListener("change", (event) => { upload(event.target.files); event.target.value = ""; });
byId("drop-zone").addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); byId("file-input").click(); } });
byId("drop-zone").addEventListener("dragover", (event) => { event.preventDefault(); byId("drop-zone").classList.add("drag-over"); });
byId("drop-zone").addEventListener("dragleave", () => byId("drop-zone").classList.remove("drag-over"));
byId("drop-zone").addEventListener("drop", (event) => { event.preventDefault(); byId("drop-zone").classList.remove("drag-over"); upload(event.dataTransfer.files); });
byId("path-form").addEventListener("submit", async (event) => { event.preventDefault(); if (state.busy) return toast("请等待当前分析结束。"); try { const asset = await post(`/api/sessions/${state.sessionId}/paths`, {path: byId("local-path").value.trim()}); addAssets([asset]); byId("local-path").value = ""; toast(asset.kind === "folder" ? "已添加本地文件夹，分析时会直接读取图片。" : "已添加本地数据源。"); } catch (error) { toast(error.message); } });
byId("browse-folder").addEventListener("click", chooseFolder);
byId("home-folder").addEventListener("click", chooseFolder);
document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", async () => { if (state.busy) return toast("请等待当前分析结束。"); try { const kind = button.dataset.example; addAssets([await post(`/api/sessions/${state.sessionId}/examples/${kind}`, {})]); byId("message-input").value = examplePrompts[kind]; byId("message-input").focus(); toast(kind === "csv" ? "已添加合成教学 CSV，不代表真实实验。" : "已添加 YOLOTracker 真实示例图片。"); } catch (error) { toast(error.message); } }));
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { byId("message-input").value = button.dataset.prompt; byId("message-input").focus(); }));
byId("settings-open").addEventListener("click", openSettings);
byId("settings-close").addEventListener("click", () => byId("settings-dialog").close());
byId("settings-form").addEventListener("submit", (event) => { event.preventDefault(); saveSettings(); });
byId("fetch-models").addEventListener("click", fetchModels);
byId("test-connection").addEventListener("click", () => saveSettings(true));
byId("image-close").addEventListener("click", () => byId("image-dialog").close());
byId("activity-clear").addEventListener("click", () => byId("activity").replaceChildren());
byId("new-session").addEventListener("click", () => { if (!state.busy) { sessionStorage.removeItem("bifb-session"); sessionStorage.removeItem("bifb-run"); window.location.reload(); } });
document.querySelectorAll("[data-nav]").forEach((button) => button.addEventListener("click", (event) => { event.preventDefault(); showView(button.dataset.nav); }));
document.querySelectorAll("[data-coming]").forEach((button) => button.addEventListener("click", () => toast(`${button.dataset.coming}功能正在推进中，敬请期待。`)));
document.querySelectorAll("[data-home-prompt]").forEach((button) => button.addEventListener("click", () => { byId("home-input").value = button.dataset.homePrompt; byId("home-input").focus(); }));
byId("home-attach").addEventListener("click", () => { showView("workbench"); byId("file-input").click(); });
byId("home-form").addEventListener("submit", (event) => { event.preventDefault(); if (state.busy) return toast("Agent 正在分析，请稍候。"); byId("message-input").value = byId("home-input").value; byId("chat-form").requestSubmit(); });
byId("home-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); byId("home-form").requestSubmit(); } });
byId("flow-form").addEventListener("submit", startFlow);
byId("flow-stop").addEventListener("click", stopAnalysis);
byId("chat-stop").addEventListener("click", stopAnalysis);
document.querySelectorAll("[data-flow-pick]").forEach((button) => button.addEventListener("click", async () => {
  if (state.busy || state.folderPicking) return;
  state.folderPicking = true; button.disabled = true;
  try { const selected = await pickFolderSelection(); if (!selected.cancelled && selected.path) { byId("flow-form").elements.namedItem(button.dataset.flowPick).value = selected.path; byId("flow-form").elements.normal_baseline_confirmed.checked = false; byId("flow-form").elements.acquisition_confirmed.checked = false; state.flowConfig = null; } }
  catch (error) { toast(error.message); } finally { state.folderPicking = false; button.disabled = state.busy; }
}));
initialize().catch((error) => { toast(error.message); byId("system-status").textContent = "服务连接失败"; });
