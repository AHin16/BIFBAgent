const byId = (id) => document.getElementById(id);
const state = {sessionId: null, assets: [], busy: false, results: 0, source: null, pending: null, view: "home", folderPicking: false, flowConfig: null, flowRun: false, optimizationRun: false, optimizationAsset: null, predictionHeights: ["H1"], runId: null, knowledgeRun: false, citations: new Map()};
const toolNames = {detect_bubbles: "YOLO · 单图气泡检测", batch_detect_bubbles: "YOLO · 实验批次分析", inspect_csv: "CSV · 数据结构检查", analyze_csv: "CSV · 科研数据分析", calculate_bubble_statistics: "气泡尺寸 · 统计分析", compare_experiments: "实验结果 · 交叉比较", calculate_bubble_velocity: "气泡运动 · 速度计算", list_files: "实验目录 · 文件检查", analyze_flow_warning: "流态监测 · 基线与持续异常分析", inspect_flow_event: "流态监测 · 事件依据查询"};
const flowStateLabels = {normal: "正常", attention: "关注", warning: "预警", insufficient: "数据不足"};
const flowEndLabels = {recovered: "指标已恢复", data_gap: "数据中断", stopped: "用户停止", end_of_sequence: "序列结束"};
const examplePrompts = {image: "检测这张气泡图片，统计气泡数量、平均直径和尺寸分布。", folder: "分析这个文件夹里的全部气泡图片，统计尺寸分布并导出 CSV。", csv: "分析这个合成示例 CSV，看看气速和气泡直径的关系，并比较不同工况。"};
Object.assign(toolNames, {search_knowledge: "知识库 · 检索原文", read_knowledge_excerpt: "知识库 · 核对原文", get_experiment_context: "实验 · 获取已确认背景"});
Object.assign(toolNames, {estimate_gas_holdup: "气含率 · 等效球体积估算", track_bubbles: "气泡追踪 · 轨迹与运动测量"});
toolNames.predict_ug_bubble_diameter = "气速变化 · 气泡尺寸预测";
toolNames.predict_h3_demo_bubble_diameter = "H3 · 0.5 wt% 气泡尺寸专项预测";
toolNames.lookup_condition_measurements = "当前工况 · 多图统计";

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

function optimizationAcceptsDrop() {
  return state.view === "optimization" && !byId("optimization-general").hidden;
}

function syncOptimizationDrop() {
  window.bifbDesktopReady?.then((desktop) => desktop.setOptimizationActive(optimizationAcceptsDrop())).catch(() => {});
}

function showView(view) {
  const home = view === "home";
  const flow = view === "flow";
  const knowledge = view === "knowledge";
  const optimization = view === "optimization";
  state.view = home ? "home" : flow ? "flow" : knowledge ? "knowledge" : optimization ? "optimization" : "workbench";
  syncOptimizationDrop();
  byId("home-view").hidden = !home;
  byId("workbench-view").hidden = home || flow || knowledge || optimization;
  byId("flow-view").hidden = !flow;
  byId("knowledge-view").hidden = !knowledge;
  byId("optimization-view").hidden = !optimization;
  byId("view-title").textContent = home ? "首页" : flow ? "流态监测预警" : knowledge ? "专业知识问答" : optimization ? "运行参数优化" : "实验分析";
  document.querySelectorAll(".nav-item[data-nav]").forEach((button) => {
    const active = button.dataset.nav === (home ? "home" : flow ? "flow" : knowledge ? "knowledge" : optimization ? "optimization" : "workbench");
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  if (!home && !flow && !knowledge && !optimization) byId("message-input").focus({preventScroll: true});
  if (knowledge) window.KnowledgeUI?.refresh();
  if (optimization) refreshPredictionHeights().catch((error) => { byId("optimization-supported").textContent = error.message; });
  window.scrollTo({top: 0, behavior: "instant"});
}

function showOptimizationMode(useH3) {
  const frame = byId("optimization-h3-frame");
  byId("optimization-general").hidden = useH3;
  byId("optimization-h3").hidden = !useH3;
  byId("optimization-general-mode").setAttribute("aria-pressed", String(!useH3));
  byId("optimization-h3-mode").setAttribute("aria-pressed", String(useH3));
  if (useH3 && !frame.hasAttribute("src")) frame.src = frame.dataset.src;
  syncOptimizationDrop();
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
  byId("optimization-fields").disabled = busy;
  byId("optimization-start").disabled = busy || !!state.optimizationUploading;
  byId("optimization-file").disabled = busy || !!state.optimizationUploading;
  byId("optimization-stop").hidden = !busy || !state.optimizationRun;
  byId("optimization-stop").disabled = false;
  byId("flow-stop").hidden = !busy;
  byId("chat-stop").hidden = !busy;
  byId("flow-stop").disabled = false;
  byId("chat-stop").disabled = false;
  byId("browse-folder").disabled = busy || state.folderPicking;
  byId("activity-dot").classList.toggle("busy", busy);
  byId("activity-state").textContent = busy ? "Agent 正在行动" : "行动过程可追溯";
  byId("composer-context").textContent = busy ? "正在分析，请稍候…" : "支持多轮实验分析";
  window.KnowledgeUI?.setBusy(busy);
}

function inlineText(target, text) {
  for (const token of text.split(/(\*\*[^*]+\*\*|`[^`]+`|\[K[A-Za-z0-9]+\])/g)) {
    if (/^\[K[A-Za-z0-9]+\]$/.test(token)) {
      const id = token.slice(1, -1); const citation = state.citations.get(id);
      if (citation) { const button = element("button", "citation-inline", citation.page_label); button.type = "button"; button.title = citation.title; button.addEventListener("click", () => window.KnowledgeUI?.openSource(citation)); target.append(button); }
      else target.append(document.createTextNode(token));
    }
    else if (token.startsWith("**") && token.endsWith("**")) target.append(element("strong", "", token.slice(2, -2)));
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
  const prediction = ["ug_bubble_prediction", "h3_demo_bubble_prediction"].includes(result.kind);
  header.append(element("div", "result-badge", prediction ? "探索性预测" : result.status === "partial" ? "部分完成" : "已计算"), element("h3", "", toolNames[tool] || tool), element("span", "", "#" + (result.result_id || "")));
  card.append(header);
  let metrics = [];
  if (result.kind === "ug_bubble_prediction") {
    const fromPhotos = result.change_from_measurement;
    metrics = [[fromPhotos?.current_d50_px ?? result.current_predicted_d50_px, fromPhotos ? "当前照片 d50 / px" : "当前预测 d50 / px"], [result.predicted_d50_px, "目标预测 d50 / px"], [fromPhotos?.change_px ?? result.change_px, fromPhotos ? "相对当前照片预计变化 / px" : "预测变化 / px"]];
    card.append(element("div", "result-limitation", `条件：盐度 ${result.conditions.salinity_wt_pct} wt%，PL ${result.conditions.PL_fraction}，${result.conditions.height_id}（${result.conditions.height_m} m）。当前 Q=${formatNumber(result.current_Q_m3_h, 3)} m³/h，Ug=${formatNumber(result.current_Ug_m_s, 6)} m/s；目标 Q=${formatNumber(result.target_Q_m3_h, 3)} m³/h，Ug=${formatNumber(result.target_Ug_m_s, 6)} m/s。适用 Q：1.5–2.3 m³/h。`));
    card.append(element("div", "result-limitation", `预计变化 ${formatNumber(fromPhotos ? fromPhotos.change_percent : result.change_percent)}%；${result.validation_summary}`));
  }
  else if (result.kind === "h3_demo_bubble_prediction") {
    metrics = [[result.current_d50_px, result.current_is_measured ? "当前照片 d50 / px" : "当前估计 d50 / px"], [result.estimated_d50_px, "目标预测 d50 / px"], [result.estimated_change_px, "预计变化 / px"]];
    if (result.observed_d50_px != null) metrics.push([result.observed_d50_px, "目标实际气泡大小 / px"]);
    if (result.transport) {
      metrics.push([result.transport.rise_change_mm_s, "预计上升速度变化 / mm/s"],
                   [result.transport.relative_oxygen_efficiency_percent, "相对传氧效率 / %"]);
      const comparison = result.transport.target_rise_comparison;
      if (comparison) {
        const method = comparison.method === "linear_extrapolation" ? "边界外推" : "相邻插值";
        card.append(element("div", "result-limitation", `目标上升速度整档留出预测 ${formatNumber(comparison.prediction_mm_s)} mm/s（${method}），照片追踪统计 ${formatNumber(comparison.observed_mm_s)} mm/s，绝对误差 ${formatNumber(comparison.absolute_error_mm_s)} mm/s。`));
      }
      card.append(element("div", "result-limitation", result.transport.limitations[1]));
    }
    card.append(element("div", "result-limitation", `H3（${result.height_m} m） · 盐度 ${result.salinity_wt_pct} wt% · PL ${result.PL_fraction * 100}% · Q ${result.current_q} → ${result.target_q} m³/h。`));
  }
  else if (result.kind === "flow_warning") metrics = [[result.processed_frames, "待测帧数"], [result.window_count, "时间窗口数"], [result.event_count, "预警事件数"]];
  else if (result.kind === "gas_holdup") metrics = [[result.gas_holdup_percent?.mean, "平均体积气含率 / %"], [result.bubble_area_ratio_percent?.mean, "平均二维面积占比 / %"], [result.valid_frames, "有效帧数"]];
  else if (result.kind === "bubble_tracking") metrics = [[result.track_id_count, "追踪 ID 数"], [result.motion_samples, "有效运动样本"], [result.mean_speed, `平均速度 / ${result.speed_unit}`]];
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
  if (state.knowledgeRun) sessionStorage.setItem("bifb-knowledge-run", runId);
  if (state.optimizationRun) sessionStorage.setItem("bifb-optimization-run", runId);
  state.source?.close();
  state.source = new EventSource(`/api/runs/${runId}/events`);
  const seen = new Set();
  state.source.onmessage = (received) => {
    const event = JSON.parse(received.data);
    if (seen.has(event.id)) return;
    seen.add(event.id);
    for (const citation of event.citations || []) state.citations.set(citation.citation_id, citation);
    window.KnowledgeUI?.onEvent(event);
    if (event.type === "flow_window") renderFlowWindow(event.window);
    if (state.flowRun && ["status", "thinking", "progress"].includes(event.type)) byId("flow-progress").textContent = event.message;
    if (state.optimizationRun) optimizationEvent(event);
    if (event.type !== "final" && event.type !== "done") activity(event);
    if (event.type === "tool_result") addResult(event.result, event.tool);
    if (event.type === "final") { state.pending?.remove(); state.pending = null; const message = addMessage("assistant", event.message); appendArtifacts(message, event.artifacts); if (state.flowRun) { byId("flow-explanation").replaceChildren(); renderMarkdown(byId("flow-explanation"), event.message); appendArtifacts(byId("flow-explanation"), event.artifacts); } }
    if (event.type === "error") { state.pending?.remove(); state.pending = null; addMessage("assistant", event.message, "error"); if (state.flowRun) { byId("flow-explanation").textContent = event.message + " 已生成的工具结果可在下方查看。"; byId("flow-progress").textContent = "本轮分析未全部完成"; } }
    if (event.type === "done") { state.source.close(); state.source = null; sessionStorage.removeItem("bifb-run"); sessionStorage.removeItem("bifb-flow-run"); sessionStorage.removeItem("bifb-knowledge-run"); sessionStorage.removeItem("bifb-optimization-run"); state.pending?.remove(); setBusy(false); if (state.flowRun && event.success) byId("flow-progress").textContent = "本轮监测与状态解释已完成"; state.runId = null; state.knowledgeRun = false; state.optimizationRun = false; }
  };
  state.source.onerror = () => {
    toast("连接暂时中断，正在尝试恢复行动记录。");
  };
}

function setOptimizationAsset(asset) {
  state.optimizationAsset=asset || null;
  if (asset) {
    sessionStorage.setItem('bifb-optimization-asset',asset.id);
    byId('optimization-image').src=`/api/sessions/${state.sessionId}/assets/${asset.id}/preview`;
    byId('optimization-filename').textContent=asset.name;byId('optimization-preview').hidden=false;
  } else {
    sessionStorage.removeItem('bifb-optimization-asset');byId('optimization-image').removeAttribute('src');
    byId('optimization-filename').textContent='';byId('optimization-preview').hidden=true;
  }
}

function applyOptimizationMetadata(metadata) {
  const form=byId('optimization-form');
  for (const name of ['current_q','height_m','salinity_wt_pct','pl_percent']) form.elements[name].value='';
  const values=metadata?.values || {};
  for (const name of ['current_q','height_m','salinity_wt_pct']) if (values[name] != null) form.elements[name].value=values[name];
  if (values.PL_fraction != null) form.elements.pl_percent.value=Number((values.PL_fraction * 100).toFixed(6));
  const match=(state.historicalConditions || []).findIndex(r=>r.current_q===values.current_q && r.height_m===values.height_m && r.salinity_wt_pct===values.salinity_wt_pct && r.PL_fraction===values.PL_fraction);
  byId('optimization-condition').value=match>=0 ? String(match) : '';
  byId('optimization-metadata-status').textContent=metadata?.message || '上传文件未提供原始路径，无法自动识别工况，请手动填写或使用本地路径选择。';
}

async function addOptimizationPath(path) {
  if (state.busy || state.optimizationUploading || !state.sessionId) return toast('请等待当前任务完成并连接本地服务。');
  if (!path) return;
  state.optimizationUploading=true; byId('optimization-start').disabled=true; byId('optimization-file').disabled=true;
  byId('optimization-progress').textContent='正在读取图片和工况…';
  try {
    const asset=await post(`/api/sessions/${state.sessionId}/optimization-image`,{path});
    setOptimizationAsset(asset); addAssets([asset]); applyOptimizationMetadata(asset.optimization_metadata);
    byId('optimization-progress').textContent='图片已添加，请核对工况并选择目标流量。';
  } catch(error) { byId('optimization-progress').textContent='读取失败，请检查图片路径。'; toast(error.message); }
  finally { state.optimizationUploading=false; byId('optimization-start').disabled=state.busy; byId('optimization-file').disabled=state.busy; }
}

async function uploadOptimizationImage(files) {
  if (state.busy || state.optimizationUploading || !state.sessionId) return toast('请等待当前任务完成并连接本地服务。');
  const file=files?.[0];
  if (!file || files.length!==1 || !/\.(jpe?g|png|tiff?|bmp|webp)$/i.test(file.name)) return toast('请选择一张图片。');
  if (file.size>50*1024*1024) return toast('单张图片不能超过 50 MB。');
  const body=new FormData();body.append('files',file);
  state.optimizationUploading=true;byId('optimization-start').disabled=true;byId('optimization-file').disabled=true;
  try {
    const data=await api(`/api/sessions/${state.sessionId}/uploads`,{method:'POST',body});
    const asset=data.assets[0];if (!asset || asset.kind!=='image') throw new Error('请选择有效的图片。');
    setOptimizationAsset(asset);addAssets([asset]);applyOptimizationMetadata(null);
    byId('optimization-progress').textContent='图片已添加，请确认工况。';
  } catch(error){toast(error.message);}
  finally {state.optimizationUploading=false;byId('optimization-start').disabled=state.busy;byId('optimization-file').disabled=state.busy;}
}

function optimizationEvent(event) {
  const log = byId("optimization-activity");
  if (["status", "thinking", "tool_start", "tool_result", "tool_error", "error"].includes(event.type)) {
    log.querySelector(".activity-empty")?.remove();
    const label = event.type === "tool_start" ? `调用 ${toolNames[event.tool] || event.tool}` : event.type === "tool_result" ? `${toolNames[event.tool] || event.tool} · ${event.result?.status === "error" ? event.result.message : "已完成"}` : event.message;
    if (label) {
      const row = element("div", `activity-row${event.type === "error" || event.type === "tool_error" || event.result?.status === "error" ? " error" : ""}`);
      row.append(element("span", "activity-time", event.time || ""), element("span", "activity-symbol", "●"), element("span", "activity-content", label));
      log.append(row); log.scrollTop = log.scrollHeight;
    }
  }
  if (["status", "thinking", "progress"].includes(event.type)) byId("optimization-progress").textContent = event.message;
  if (event.type === "tool_result" && event.result?.status === "success") {
    const r = event.result;
    if (!['detect_bubbles','lookup_condition_measurements','predict_ug_bubble_diameter'].includes(event.tool)) return;
    if (event.tool === 'lookup_condition_measurements') {
      const card=element('article','result-card');const head=element('div','result-card-header');
      head.append(element('div','result-badge','当前工况 · 多张实验图片'),element('h3','','当前工况气泡大小'));card.append(head);
      const grid=element('div','result-metrics');
      const rows=[[r.image_count,'图片数量'],[r.valid_images,'有效图片'],[r.mean_image_d50_px,'每图中位径平均 / px']];
      if (r.mean_image_d50_mm != null) rows.push([r.mean_image_d50_mm,'每图中位径平均 / mm']);
      for (const [value,label] of rows) { const metric=element('div','metric');metric.append(element('strong','',formatNumber(value)),element('span','',label));grid.append(metric); }
      const rangeMM=r.image_d50_p10_mm != null ? `（${formatNumber(r.image_d50_p10_mm)}–${formatNumber(r.image_d50_p90_mm)} mm）` : '';
      card.append(grid,element('p','flow-result-note',`图片中位径 P10–P90：${formatNumber(r.image_d50_p10_px)}–${formatNumber(r.image_d50_p90_px)} px ${rangeMM}；有效气泡少于 5 个的图片 ${r.low_quality_images} 张。来源：${r.source}。这是已识别的历史同工况实验照片统计，不是实时测量；连续帧不是独立重复实验。`));
      if (r.preview_unavailable) card.append(element('p','flow-result-note','部分原始图片暂时无法访问；以上统计来自本地已有结果。'));
      appendArtifacts(card,r.artifacts);byId('optimization-output').append(card);return;
    }
    const card = element("article", "result-card");
    const head = element("div", "result-card-header");
    const paired = event.tool === 'predict_ug_bubble_diameter' && r.comparison?.observed_change_px != null;
    const fromPhotos = event.tool === 'predict_ug_bubble_diameter' ? r.change_from_measurement : null;
    head.append(element("div", "result-badge", paired ? "实验照片 · YOLO" : event.tool === "detect_bubbles" ? "当前图片 · YOLO" : "目标工况 · 模型预测"), element("h3", "", paired ? "两组实验照片的气泡尺寸对比" : event.tool === "detect_bubbles" ? "当前气泡大小" : r.height_changed ? "目标气速与高度的预测" : "改变气速后的预测"));
    card.append(head);
    if (paired) {
      const measured = r.comparison.measured;
      const actualGrid = element('div', 'result-metrics');
      const measuredValues = [
        [r.current.mean_image_d50_px, `当前 Q ${formatNumber(r.current_Q_m3_h)} · d50 / px`],
        [measured.mean_image_d50_px, `目标 Q ${formatNumber(r.target_Q_m3_h)} · d50 / px`],
        [r.comparison.observed_change_px, '照片统计变化 / px']
      ];
      for (const [value, label] of measuredValues) {
        const metric = element('div', 'metric');
        metric.append(element('strong', '', formatNumber(value)), element('span', '', label));
        actualGrid.append(metric);
      }
      const scale = r.prediction_mm_per_pixel;
      const changeMM = scale ? `，按标定换算约 ${formatNumber(r.comparison.observed_change_px * scale)} mm` : '';
      card.append(actualGrid, element('p', 'flow-result-note',
        `照片统计变化 ${formatNumber(r.comparison.observed_change_percent)}%${changeMM}。当前和目标分别有 ${r.current.image_count} 和 ${measured.image_count} 张有效照片，均为训练所用的实验数据。`));
    }
    if (fromPhotos) {
      const forecast = element('div', 'result-comparison');
      forecast.append(element('h4', '', '从当前照片出发的预测'));
      let text = `当前照片 d50 为 ${formatNumber(fromPhotos.current_d50_px)} px，目标预测 d50 为 ${formatNumber(r.predicted_d50_px)} px。预计变化 ${formatNumber(fromPhotos.change_px)} px（${formatNumber(fromPhotos.change_percent)}%）`;
      if (fromPhotos.change_mm != null) text += `，约 ${formatNumber(fromPhotos.change_mm)} mm`;
      forecast.append(element('p', '', `${text}。当前值来自数据库中的 ${fromPhotos.image_count} 张有效实验照片。`));
      if (paired) forecast.append(element('p', '', `与两组照片的实际变化相差 ${formatNumber(r.comparison.change_from_measurement_error_px)} px。`));
      card.append(forecast);
    }
    const prediction = paired || fromPhotos ? element('details', 'result-comparison') : card;
    if (paired || fromPhotos) {
      prediction.append(element('summary', '', '展开模型两端估计与偏差'));
      card.append(prediction);
    }
    const values = event.tool === "detect_bubbles" ? [[r.bubble_count, "检测气泡数"], [r.statistics_px?.mean, "平均直径 / px"], [r.statistics_px?.median, "中位直径 / px"]] : [[r.current_predicted_d50_px, "当前工况模型 d50 / px"], [r.predicted_d50_px, "目标工况模型 d50 / px"], [r.change_px, "模型预测变化 / px"]];
    if (event.tool === 'detect_bubbles' && r.unit === 'mm') values.push([r.statistics?.mean,'当前图片平均直径 / mm'],[r.statistics?.median,'当前图片中位直径 / mm']);
    if (event.tool === 'predict_ug_bubble_diameter' && r.predicted_d50_mm != null) values.push([r.current_predicted_d50_mm,'当前工况模型 d50 / mm'],[r.predicted_d50_mm,'目标工况模型 d50 / mm'],[r.change_mm,'模型预测变化 / mm']);
    const grid = element("div", "result-metrics");
    for (const [value, label] of values) { const metric = element("div", "metric"); metric.append(element("strong", "", formatNumber(value)), element("span", "", label)); grid.append(metric); }
    prediction.append(grid);
    prediction.append(element("p", "flow-result-note", event.tool === "detect_bubbles" ? "单张图片检测的二维等效直径，包含边缘目标；统计可能受遮挡与分割误差影响。" : `当前高度 H = ${formatNumber(r.current_height_m ?? r.conditions?.height_m)} m，目标高度 H = ${formatNumber(r.target_height_m ?? r.conditions?.height_m)} m；盐度 ${formatNumber(r.conditions?.salinity_wt_pct)} wt%，PL ${formatNumber(r.conditions?.PL_fraction * 100)}%。${r.height_changed ? '高度与气体流量可能同时变化，预测差值包含两者影响。' : '高度保持不变。'}模型预测变化 ${formatNumber(r.change_percent)}%。预测是目标工况的平均图片中位径，不由单张图片推算。`));
    if (paired) {
      prediction.append(element('p', 'flow-result-note',
        `目标泡径的预测与照片统计相差 ${formatNumber(r.comparison.absolute_error_px)} px。仅用两端模型预测计算的变化量，与两组照片的实际变化相差 ${formatNumber(r.comparison.change_absolute_error_px)} px。`));
    } else if (event.tool==='predict_ug_bubble_diameter' && r.comparison?.measured) {
      const measured=r.comparison.measured; const block=element('div','result-comparison');
      block.append(element('h4','','实际气泡大小（实验照片 YOLO 统计）'));
      let text=`${formatNumber(measured.mean_image_d50_px)} px；预测与实际的绝对差 ${formatNumber(r.comparison.absolute_error_px)} px，相对差 ${formatNumber(r.comparison.relative_error_percent)}%；有效图片 ${measured.image_count} 张。`;
      if (r.prediction_mm_per_pixel) text+=` 按标定换算：实际 ${formatNumber(measured.mean_image_d50_px*r.prediction_mm_per_pixel)} mm，绝对差 ${formatNumber(r.comparison.absolute_error_px*r.prediction_mm_per_pixel)} mm。`;
      if (r.current?.mean_image_d50_px != null) {
        const current=r.current.mean_image_d50_px, delta=measured.mean_image_d50_px-current;
        text+=` 当前工况实际 ${formatNumber(current)} px，目标与当前实际变化 ${formatNumber(delta)} px（${formatNumber(current ? delta/current*100 : null)}%）。`;
        if (r.prediction_mm_per_pixel) text+=` 实际变化 ${formatNumber(delta*r.prediction_mm_per_pixel)} mm。`;
      }
      block.append(element('p','',text),element('p','','统计来自训练所用的实验照片，适合查看已有工况差异。'));grid.before(block);
    }
    if (event.tool === 'predict_ug_bubble_diameter') card.append(element('p','flow-result-note',r.predicted_d50_mm != null ? `毫米值按你确认的 ${formatNumber(r.prediction_mm_per_pixel, 8)} mm/px 换算；模型本身仍是像素模型。` : '未确认统一空间标定，暂不显示毫米尺寸。'));
    if (event.tool === "predict_ug_bubble_diameter") card.append(element("p", "flow-result-note", r.validation_summary));
    if (event.tool === 'predict_ug_bubble_diameter' && r.target_q_support) {
      const support = r.target_q_support;
      const levels = support.measured_q_levels.map(q => formatNumber(q)).join('、');
      const prefix = `同高度、同盐度及同 PL 下的实验 Q 为 ${levels} m³/h。`;
      const message = {
        measured: `${prefix}目标 Q 有照片统计，可直接参考上方对比。`,
        bracketed: `${prefix}目标 Q 在实验档位之间，变化幅度和方向仍需实验证实。`,
        outside_group_q: `${prefix}目标 Q 超出该组合的实验档位范围，变化方向可信度较低。`,
        no_matching_group: '目标高度、盐度和 PL 的组合没有实验照片，变化方向可信度较低。'
      }[support.kind];
      if (message) card.append(element('p', 'optimization-warning', message));
    }
    if (event.tool === "predict_ug_bubble_diameter" && typeof r.target_within_joint_coverage === 'boolean') card.append(element("p", "optimization-warning", `当前工况：${r.current_within_joint_coverage ? '在已有数据联合覆盖内' : '联合覆盖外（组合外推，尚未验证）'}；目标工况：${r.target_within_joint_coverage ? '在已有数据联合覆盖内' : '联合覆盖外（组合外推，尚未验证）'}。覆盖内也不代表预测已被实验证实。`));
    appendArtifacts(prediction, r.artifacts);
    byId("optimization-output").append(card);
  }
  if (event.type === "final") { byId("optimization-explanation").replaceChildren(); renderMarkdown(byId("optimization-explanation"), event.message); appendArtifacts(byId("optimization-explanation"), event.artifacts); }
  if (event.type === "error") { byId("optimization-explanation").textContent = event.message; byId("optimization-progress").textContent = "分析未完成，请检查输入或运行设置。"; }
  if (event.type === "done") byId("optimization-progress").textContent = event.success ? "当前工况统计与目标工况预测已完成。" : "本轮未完成，请查看行动记录。";
}

async function startOptimization(event) {
  event.preventDefault();
  if (state.busy || !state.sessionId) return;
  const form = byId("optimization-form");
  if (!form.reportValidity()) return;
  const input = {use_history:true, asset_id: state.optimizationAsset?.id || '', current_q: Number(form.elements.current_q.value),
    target_q: Number(form.elements.target_q.value), salinity_wt_pct: Number(form.elements.salinity_wt_pct.value),
    height_m: Number(form.elements.height_m.value), PL_fraction: Number(form.elements.pl_percent.value) / 100};
  if (form.elements.use_target_height.checked) input.target_height_m=Number(form.elements.target_height_m.value);
  const scale=form.elements.prediction_mm_per_pixel.value.trim();
  const confirmed=form.elements.calibration_confirmed.checked;
  if (!!scale !== confirmed) return toast('显示毫米需要填写比例尺，并确认它适用于当前照片和模型训练照片。');
  if (scale) { input.prediction_mm_per_pixel=Number(scale); input.calibration_confirmed=true; }
  state.flowRun = false; state.knowledgeRun = false; state.optimizationRun = true; setBusy(true);
  byId("optimization-output").replaceChildren(); byId("optimization-activity").replaceChildren();
  byId("optimization-explanation").textContent = "Agent 正在查询当前工况实验统计并预测目标工况…";
  try {
    const result = await post(`/api/sessions/${state.sessionId}/chat`, {message: "请查询当前工况的实验图片统计，并预测目标工况的气泡尺寸；若目标工况有实验数据，展示实际气泡大小及比较，说明依据和局限。", optimization: input});
    connectEvents(result.run_id);
  } catch (error) { state.optimizationRun = false; setBusy(false); byId("optimization-explanation").textContent = error.message; toast(error.message); }
}

async function submitTask(event) {
  event.preventDefault();
  const message = byId("message-input").value.trim();
  if (!message || state.busy) return;
  if (!state.sessionId) return toast("正在连接本地服务，请稍候。");
  showView("workbench");
  state.flowRun = false;
  state.knowledgeRun = false;
  state.optimizationRun = false;
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
    remove.addEventListener("click", async () => { if (state.busy) return toast("请等待当前分析结束。"); try { await api(`/api/sessions/${state.sessionId}/assets/${asset.id}`, {method: "DELETE"}); state.assets = state.assets.filter((item) => item.id !== asset.id); if (state.optimizationAsset?.id === asset.id) { setOptimizationAsset(null); byId("optimization-progress").textContent = "图片已移除，请重新选择当前工况图片。"; } renderAssets(); } catch (error) { toast(error.message); } });
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
  if ([...files].some((file) => /\.(mp4|avi|mov|mkv)$/i.test(file.name))) return toast("请通过「输入本地文件或文件夹路径」添加视频。");
  if ([...files].some((file) => /\.(pdf|docx?|txt|md)$/i.test(file.name))) return toast("文献知识库功能正在推进中。");
  const supported = [...files].filter((file) => /\.(jpe?g|png|tiff?|bmp|webp|csv)$/i.test(file.name));
  if (!supported.length) return toast("请选择图片或 CSV 文件。");
  if (supported.some((file) => file.size > 50 * 1024 * 1024)) return toast("单个文件不能超过 50 MB，大文件请用本地路径。");
  const body = new FormData();
  for (const file of supported) body.append("files", file, folder ? file.webkitRelativePath || file.name : file.name);
  try { toast("正在上传实验数据…"); const data = await api(`/api/sessions/${state.sessionId}/uploads?folder=${folder}`, {method: "POST", body}); addAssets(data.assets); toast(`已添加 ${supported.length} 个文件，可以开始提问。`); } catch (error) { toast(error.message); }
}

async function refreshPredictionHeights() {
  const health = await api("/api/health"); state.predictionHeights = health.prediction_heights || ["H1"];
  byId("optimization-supported").textContent = state.settings?.prediction_calibration_confirmed ? '探索性连续高度模型：H 0.2–1.8 m；已使用确认的统一标定，视野和裁剪差异仍需核对。' : '探索性连续高度模型：H 0.2–1.8 m；允许范围内组合预测，并标明数据覆盖情况。视野和比例尺未确认一致，跨高度结果需谨慎。';
}

async function refreshHistoricalConditions() {
  if (state.historicalConditions) return;
  const data=await api('/api/optimization/conditions');
  state.historicalConditions=data.conditions.sort((a,b)=>a.height_m-b.height_m || a.salinity_wt_pct-b.salinity_wt_pct || a.PL_fraction-b.PL_fraction || a.current_q-b.current_q);
  const select=byId('optimization-condition');select.replaceChildren(new Option('选择已有工况（可选）',''));
  state.historicalConditions.forEach((r,i)=>select.add(new Option(`H ${r.height_m} m · 盐 ${r.salinity_wt_pct}% · PL ${formatNumber(r.PL_fraction*100)}% · Q ${r.current_q} · ${r.valid_images} 张`,String(i))));
}

async function refreshSettings() {
  const settings = await api("/api/settings"); state.settings = settings;
  await refreshPredictionHeights();
  const badge = byId("system-status"); badge.replaceChildren(element("i"), document.createTextNode(settings.llm_ready ? "本地服务已就绪" : "待配置 LLM")); badge.classList.toggle("ready", settings.llm_ready);
  byId("calibration-label").textContent = settings.mm_per_pixel ? `空间标定 · ${settings.mm_per_pixel} mm / px` : "未标定 · 图像尺寸以 px 显示";
  const predictionForm=byId('optimization-form');
  if (state.predictionCalibrationAuto || (!predictionForm.elements.prediction_mm_per_pixel.value && !predictionForm.elements.calibration_confirmed.checked)) {
    predictionForm.elements.prediction_mm_per_pixel.value=settings.prediction_calibration_confirmed ? settings.mm_per_pixel ?? '' : '';
    predictionForm.elements.calibration_confirmed.checked=!!(settings.mm_per_pixel && settings.prediction_calibration_confirmed);
    state.predictionCalibrationAuto=predictionForm.elements.calibration_confirmed.checked;
  }
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
    byId("settings-feedback").textContent = settings.model_exists ? "YOLO 推理已内置，已找到模型权重。" : "YOLO 推理已内置，请选择有效的气泡模型权重。";
    byId("settings-dialog").showModal();
  } catch (error) { toast(error.message); }
}

async function chooseModel() {
  const button = byId("browse-model");
  button.disabled = true;
  try {
    let selected;
    if (window.bifbDesktopReady) {
      const desktop = await window.bifbDesktopReady;
      selected = JSON.parse(await new Promise((resolve) => desktop.chooseModel(resolve)));
    } else {
      selected = await api("/api/dialog/model");
    }
    if (selected.cancelled || !selected.path) return;
    byId("settings-form").elements.yolo_model_path.value = selected.path;
    byId("settings-feedback").textContent = "已选择模型权重，保存设置后生效。";
  } catch (error) {
    byId("settings-feedback").textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

byId("browse-model").addEventListener("click", chooseModel);

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
  try { await refreshHistoricalConditions(); } catch { byId('optimization-condition').replaceChildren(new Option('工况数据库不可用','')); }
  const previous = sessionStorage.getItem("bifb-session");
  let session = null;
  if (previous) { try { session = await api(`/api/sessions/${previous}`); } catch { sessionStorage.removeItem("bifb-run"); } }
  if (!session) session = await post("/api/sessions", {});
  state.sessionId = session.session_id; sessionStorage.setItem("bifb-session", state.sessionId);
  state.assets = session.assets || []; renderAssets();
  setOptimizationAsset(state.assets.find((asset) => asset.id === sessionStorage.getItem("bifb-optimization-asset") && asset.kind === "image") || null);
  for (const citation of session.knowledge_citations || []) state.citations.set(citation.citation_id, citation);
  if (session.flow_config) {
    state.flowConfig = session.flow_config;
    for (const [key, value] of Object.entries(session.flow_config)) {
      const input = byId("flow-form").elements.namedItem(key);
      if (input) { if (input.type === "checkbox") input.checked = Boolean(value); else input.value = value; }
    }
  }
  for (const message of session.history || []) addMessage(message.role, message.content);
  const activeRun = sessionStorage.getItem("bifb-run");
  if (activeRun) { state.flowRun = sessionStorage.getItem("bifb-flow-run") === activeRun; state.knowledgeRun = sessionStorage.getItem("bifb-knowledge-run") === activeRun; state.optimizationRun = sessionStorage.getItem("bifb-optimization-run") === activeRun; if (state.flowRun) showView("flow"); if (state.knowledgeRun) showView("knowledge"); if (state.optimizationRun) showView("optimization"); setBusy(true); connectEvents(activeRun); }
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
    state.knowledgeRun = false;
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
  byId("flow-stop").disabled = true; byId("chat-stop").disabled = true; byId("optimization-stop").disabled = true;
  try { await post(`/api/sessions/${state.sessionId}/runs/${state.runId}/stop`, {}); toast("正在停止并保存已经完成的结果。"); }
  catch (error) { toast(error.message); byId("flow-stop").disabled = false; byId("chat-stop").disabled = false; byId("optimization-stop").disabled = false; }
}

byId("chat-form").addEventListener("submit", submitTask);
byId("optimization-general-mode").addEventListener("click", () => showOptimizationMode(false));
byId("optimization-h3-mode").addEventListener("click", () => showOptimizationMode(true));
let h3FrameObserver;
byId("optimization-h3-frame").addEventListener("load", (event) => {
  const frame = event.currentTarget;
  h3FrameObserver?.disconnect();
  const content = frame.contentDocument?.querySelector("main") || frame.contentDocument?.body;
  if (!content) return;
  h3FrameObserver = new ResizeObserver(() => {
    const height = Math.ceil(content.getBoundingClientRect().bottom);
    if (height > 0) frame.style.height = `${height + 2}px`;
  });
  h3FrameObserver.observe(content);
});
byId("optimization-form").addEventListener("submit", startOptimization);
byId('optimization-condition').addEventListener('change',(event)=>{
  if (event.target.value==='') return;
  const r=state.historicalConditions[Number(event.target.value)];if (!r) return;
  const form=byId('optimization-form');form.elements.current_q.value=r.current_q;form.elements.height_m.value=r.height_m;
  form.elements.salinity_wt_pct.value=r.salinity_wt_pct;form.elements.pl_percent.value=Number((r.PL_fraction*100).toFixed(6));
  byId('optimization-metadata-status').textContent=`已选择数据库工况，来源：${r.source}；可手动修改，当前工况必须与数据库严格匹配。`;
});
for (const name of ['current_q','height_m','salinity_wt_pct','pl_percent']) byId('optimization-form').elements[name].addEventListener('input',()=>{byId('optimization-condition').value='';});
byId('optimization-form').elements.use_target_height.addEventListener('change', (event) => {
  const target=byId('optimization-form').elements.target_height_m;
  byId('optimization-target-height-fields').hidden=!event.target.checked;
  target.required=event.target.checked;
  if (!event.target.checked) target.value='';
});
byId('optimization-form').elements.prediction_mm_per_pixel.addEventListener('input', () => { state.predictionCalibrationAuto=false; });
byId('optimization-form').elements.calibration_confirmed.addEventListener('change', () => { state.predictionCalibrationAuto=false; });
async function chooseOptimizationImage() {
  if (state.busy || state.optimizationUploading) return;
  if (!window.bifbDesktopReady) { byId('optimization-file').click(); return; }
  try {
    const desktop=await window.bifbDesktopReady;
    const result=JSON.parse(await new Promise((resolve) => desktop.chooseOptimizationImage(resolve)));
    if (!result.cancelled) await addOptimizationPath(result.path);
  } catch (error) { toast(error.message || '无法打开图片选择器。'); }
}
if (window.bifbDesktopReady) window.bifbDesktopReady.then((desktop) => {
  desktop.localImageDropped.connect((path) => { if (optimizationAcceptsDrop()) addOptimizationPath(path); });
  desktop.setOptimizationActive(optimizationAcceptsDrop());
}).catch(() => {});
byId('optimization-path-add').addEventListener('click', () => addOptimizationPath(byId('optimization-path').value.trim()));
byId('optimization-drop').addEventListener('click', (event) => {
  if (window.bifbDesktopReady && event.target !== byId('optimization-file')) { event.preventDefault(); chooseOptimizationImage(); }
});
byId("optimization-file").addEventListener("change", (event) => { uploadOptimizationImage(event.target.files); event.target.value = ""; });
byId("optimization-drop").addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); chooseOptimizationImage(); } });
byId("optimization-drop").addEventListener("dragover", (event) => { event.preventDefault(); byId("optimization-drop").classList.add("drag-over"); });
byId("optimization-drop").addEventListener("dragleave", () => byId("optimization-drop").classList.remove("drag-over"));
byId("optimization-drop").addEventListener("drop", (event) => { event.preventDefault(); byId("optimization-drop").classList.remove("drag-over"); uploadOptimizationImage(event.dataTransfer.files); });
byId("optimization-stop").addEventListener("click", stopAnalysis);
byId("message-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); byId("chat-form").requestSubmit(); } });
byId("file-input").addEventListener("change", (event) => { upload(event.target.files); event.target.value = ""; });
byId("drop-zone").addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); byId("file-input").click(); } });
byId("drop-zone").addEventListener("dragover", (event) => { event.preventDefault(); byId("drop-zone").classList.add("drag-over"); });
byId("drop-zone").addEventListener("dragleave", () => byId("drop-zone").classList.remove("drag-over"));
byId("drop-zone").addEventListener("drop", (event) => { event.preventDefault(); byId("drop-zone").classList.remove("drag-over"); upload(event.dataTransfer.files); });
byId("path-form").addEventListener("submit", async (event) => { event.preventDefault(); if (state.busy) return toast("请等待当前分析结束。"); try { const asset = await post(`/api/sessions/${state.sessionId}/paths`, {path: byId("local-path").value.trim()}); addAssets([asset]); byId("local-path").value = ""; toast(asset.kind === "folder" ? "已添加本地文件夹，分析时会直接读取图片。" : "已添加本地数据源。"); } catch (error) { toast(error.message); } });
byId("browse-folder").addEventListener("click", chooseFolder);
byId("home-folder").addEventListener("click", chooseFolder);
document.querySelectorAll("[data-example]").forEach((button) => button.addEventListener("click", async () => { if (state.busy) return toast("请等待当前分析结束。"); try { const kind = button.dataset.example; addAssets([await post(`/api/sessions/${state.sessionId}/examples/${kind}`, {})]); byId("message-input").value = examplePrompts[kind]; byId("message-input").focus(); toast(kind === "csv" ? "已添加合成教学 CSV，不代表真实实验。" : "已添加内置真实气泡示例图片。"); } catch (error) { toast(error.message); } }));
document.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => { byId("message-input").value = button.dataset.prompt; byId("message-input").focus(); }));
byId("settings-open").addEventListener("click", openSettings);
byId("settings-close").addEventListener("click", () => byId("settings-dialog").close());
byId("settings-form").addEventListener("submit", (event) => { event.preventDefault(); saveSettings(); });
byId("fetch-models").addEventListener("click", fetchModels);
byId("test-connection").addEventListener("click", () => saveSettings(true));
byId("image-close").addEventListener("click", () => byId("image-dialog").close());
byId("activity-clear").addEventListener("click", () => byId("activity").replaceChildren());
byId("new-session").addEventListener("click", () => { if (!state.busy) { sessionStorage.removeItem("bifb-session"); sessionStorage.removeItem("bifb-run"); sessionStorage.removeItem("bifb-optimization-asset"); window.location.reload(); } });
document.querySelectorAll("[data-nav]").forEach((button) => button.addEventListener("click", (event) => { event.preventDefault(); showView(button.dataset.nav); }));
document.querySelectorAll("[data-coming]").forEach((button) => button.addEventListener("click", () => toast(`${button.dataset.coming}功能正在推进中，敬请期待。`)));
document.querySelectorAll("[data-sequence]").forEach((button) => button.addEventListener("click", () => {
  showView("workbench");
  if (state.busy) return;
  const input = byId("message-input");
  if (!input.value.trim()) {
    input.value = button.dataset.sequence === "holdup"
      ? "请估算已添加图片的等效球体积气含率，并报告二维面积占比。实际视野深度（mm）为 "
      : "请追踪已添加的连续图像序列或视频，导出轨迹、速度和标注视频。";
  }
  input.focus();
  input.setSelectionRange(input.value.length, input.value.length);
}));
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
