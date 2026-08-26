const groups = {
  "首页":"总览 Dashboard",
  "AI投资助手":"智能问答|综合投资分析",
  "知识中心":"知识上传|知识管理|知识检索|标签管理|知识来源管理",
  "策略中心":"策略库|四大战术|仓位管理|买点策略|卖点策略|选股策略|风险控制|外部策略",
  "行情中心【待开发】":"市场总览|A股行情|港股行情|美股行情|ETF|基金 / QDII|期货|行业 / 板块|市场情绪",
  "智能选股【待开发】":"全市场扫描|战术选股|问财选股|候选股票池",
  "实时盯盘【待开发】":"自选股|实时监控|盘中信号|买卖点提示|异动提醒",
  "持仓中心【待开发】":"总资产|股票持仓|ETF持仓|基金 / QDII|期货持仓|海外资产|现金",
  "资产配置【待开发】":"资产分布|风险暴露|行业暴露|相关性分析|调仓建议",
  "交易分析【待开发】":"历史交易|战术识别|买点分析|卖点分析|历史行情重放|Agent vs 老师",
  "复盘中心【待开发】":"每日复盘|周复盘|策略效果统计|盈亏分析|Agent自我评估",
  "新闻与研究【待开发】":"实时新闻|宏观|行业|个股资讯|研报",
  "系统设置":"基础服务配置|DeepSeek|Embedding|PostgreSQL|MinIO|Qdrant|行情数据源",
};
const routes={"总览 Dashboard":"dashboard","智能问答":"qa","知识上传":"upload","知识管理":"documents",
  "知识检索":"search","标签管理":"tags","策略库":"strategies","四大战术":"tactics","基础服务配置":"settings"};
const content=document.querySelector("#content"), heading=document.querySelector("#page-title");
const esc=v=>String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#039;"})[c]);
const badge=v=>{const key=String(v||"");const labels={UPLOADED:"已上传",PROCESSING:"处理中",INDEXED:"已入库",FAILED:"失败",
  pending:"待处理",embedding:"向量化中",embedded:"已向量化",pending_retry:"待重试",failed:"失败",
  draft:"AI解析/未审核",reviewed:"已审核",active:"参与检索",disabled:"禁用检索"};
  return `<span class="status ${esc(key.toLowerCase())}">${labels[key]||esc(key)}</span>`;};
function menu(){document.querySelector("#navigation").innerHTML=Object.entries(groups).map(([g,s])=>`<section class="nav-group">
  <h3>${g}</h3>${s.split("|").map(x=>`<button data-page="${x}"><span>${x}</span>${routes[x]?"":"<small>待开发</small>"}</button>`).join("")}</section>`).join("");
  document.querySelectorAll("[data-page]").forEach(n=>n.onclick=()=>openPage(n.dataset.page));}
async function openPage(name){heading.textContent=name;document.querySelectorAll("[data-page]").forEach(n=>n.classList.toggle("active",n.dataset.page===name));
  if(!routes[name]){content.innerHTML=`<div class="empty"><div><h2>${esc(name)}</h2><p>功能待开发</p></div></div>`;return;}
  content.innerHTML='<div class="loading">正在加载…</div>';try{await pages[routes[name]]();}catch(e){content.innerHTML=`<div class="empty error-panel"><p>${esc(e.message)}</p></div>`;}}
function bindDocs(){document.querySelectorAll("[data-doc]").forEach(n=>n.onclick=()=>detail(n.dataset.doc));}
const pages={};
pages.dashboard=async()=>{const d=await Api.request("/api/dashboard/stats"),c=d.counts;
  content.innerHTML=`<div class="metric-grid">${[["知识文档",c.document_count],["知识 Chunk",c.chunk_count],["正式策略",c.strategy_count],["知识标签",c.tag_count],["待审核",c.draft_count],["已审核",c.reviewed_count]]
  .map(x=>`<article class="metric"><span>${x[0]}</span><strong>${x[1]}</strong></article>`).join("")}</div>
  <div class="service-grid">${Object.entries(d.services).map(x=>`<article><i class="${x[1]?"online":"offline"}"></i><span>${x[0]}</span><strong>${x[1]?"正常":"异常"}</strong></article>`).join("")}</div>
  <div class="two-column"><section class="panel"><h2>最近上传知识</h2>${d.recent.map(x=>`<button class="list-row" data-doc="${x.id}"><span>${esc(x.name)}</span>${badge(x.status)}</button>`).join("")||"暂无数据"}</section>
  <section class="panel"><h2>最近失败文档</h2>${d.failed.map(x=>`<button class="list-row" data-doc="${x.id}"><span>${esc(x.name)}</span><small>${esc((x.metadata||{}).error_stage||"FAILED")}</small></button>`).join("")||"暂无失败"}</section></div>`;bindDocs();};
pages.upload=async()=>{const strategies=await Api.request("/api/strategies");content.innerHTML=`<section class="panel form-panel"><h2>上传投资资料</h2>
  <p>DOCX 可用；PDF / TXT / 图片 / 音频 / 视频待开发。</p><form id="upload" class="form-grid">
  <label class="file-drop full">DOCX 文件<input name="file" type="file" accept=".docx" required></label>
  <label>来源类型<select name="source_type"><option value="self">个人整理</option><option value="paid_teacher">付费老师</option><option value="research_report">研报</option></select></label>
  <label>来源名称<input name="source_name"></label><label>知识分类<select name="category"><option value="other">自动识别 / 其他</option><option value="core_strategy">核心策略</option>
  <option value="risk_management">风险管理</option><option value="asset_allocation">资产配置</option><option value="fund">基金 / QDII</option><option value="macro">宏观</option></select></label>
  <label>关联策略<select name="strategy_id"><option value="">DeepSeek 自动识别</option>${strategies.filter(x=>x.status==="active").map(x=>`<option value="${x.id}">${esc(x.name)}</option>`).join("")}</select></label>
  <button class="full">上传并智能入库</button></form><div id="progress"></div></section>`;
  document.querySelector("#upload").onsubmit=async e=>{e.preventDefault();const b=e.currentTarget.querySelector("button"),p=document.querySelector("#progress");b.disabled=true;
  try{const doc=await Api.request("/api/knowledge/documents",{method:"POST",body:new FormData(e.currentTarget)});
  for(;;){const s=await Api.request(`/api/knowledge/documents/${doc.id}/status`),m=s.metadata||{};p.innerHTML=`<div class="progress-card ${s.status==="FAILED"?"failed":""}">
  <div><strong>${esc(m.stage_label||s.status)}</strong><span>${m.progress||0}%</span></div><div class="progress"><i style="width:${m.progress||0}%"></i></div>
  ${s.status==="FAILED"?`<p>失败阶段：${esc(m.error_stage)}<br>${esc(m.error_message)}</p>`:""}</div>`;if(["INDEXED","FAILED"].includes(s.status))break;await new Promise(r=>setTimeout(r,1500));}}
  catch(x){p.innerHTML=`<div class="progress-card failed">${esc(x.message)}</div>`;}finally{b.disabled=false;}};};
pages.documents=async()=>{const d=await Api.request("/api/knowledge/documents");content.innerHTML=`<section class="panel"><div class="panel-title"><h2>知识管理</h2><button id="new">上传知识</button></div>
  <div class="table-wrap"><table><thead><tr><th>文件名称</th><th>来源</th><th>分类</th><th>策略</th><th>Chunk</th><th>已审核</th><th>状态</th></tr></thead><tbody>
  ${d.map(x=>`<tr data-doc="${x.id}"><td>${esc(x.name)}</td><td>${esc(x.source_name||x.source_type||"-")}</td><td>${esc(x.category||"-")}</td>
  <td>${esc(x.strategy_name||"未关联")}</td><td>${x.chunk_count}</td><td>${x.reviewed_count}/${x.chunk_count}</td><td>${badge(x.status)}</td></tr>`).join("")}</tbody></table></div></section>`;
  document.querySelector("#new").onclick=()=>openPage("知识上传");bindDocs();};
function rich(t,images){const m=Object.fromEntries((images||[]).map(x=>[x.image_id,x.url]));return String(t||"").split(/(\[\[IMAGE:[^\]]+\]\])/g).map(x=>{const a=x.match(/^\[\[IMAGE:([^\]]+)\]\]$/);
  return a?(m[a[1]]?`<figure><img src="${esc(m[a[1]])}"></figure>`:`<div class="missing-image">${esc(x)}</div>`):`<div class="text-block">${esc(x)}</div>`;}).join("");}
const chunkTypes=["principle","market_environment","stock_selection","entry_rule","exit_rule","position_management","risk_management","intraday","case","review","asset_allocation","fund","futures","macro","industry","other"];
async function detail(id){const [d,strategies]=await Promise.all([Api.request(`/api/knowledge/documents/${id}`),Api.request("/api/strategies")]);heading.textContent="知识详情";
  const strategyOptions=x=>`<option value="">未关联</option>${strategies.map(s=>`<option value="${s.id}" ${String(s.id)===String(x.strategy_id)?"selected":""}>${esc(s.name)}</option>`).join("")}`;
  content.innerHTML=`<section class="panel"><div class="panel-title"><div><h2>${esc(d.name)}</h2><p>${esc(d.original_filename)}</p></div><div class="actions"><button class="secondary" id="raw">查看原始文件</button><button id="parsed">查看解析内容</button></div></div>
  <div class="detail-grid"><div><span>来源</span><strong>${esc(d.source_name||d.source_type||"-")}</strong></div><div><span>分类</span><strong>${esc(d.category||"-")}</strong></div><div><span>策略</span><strong>${esc(d.strategy_name||"未关联")}</strong></div>
  <div><span>Chunk / 已审核</span><strong>${d.chunk_count} / ${d.reviewed_count}</strong></div><div><span>状态</span><strong>${badge(d.status)}</strong></div><div><span>处理阶段</span><strong>${esc((d.metadata||{}).processing_stage||"-")}</strong></div>
  <div class="full"><span>MinIO</span><strong>${esc(d.minio_bucket)} / ${esc(d.minio_object_key)}</strong></div><div class="full"><span>摘要</span><p>${esc(d.summary||"暂无摘要")}</p></div></div></section>
  <section class="chunk-list"><h2>知识 Chunk</h2>${d.chunks.map(x=>`<details class="chunk" data-chunk="${x.id}"><summary><div><small>Chunk ${x.chunk_index}</small><strong>${esc(x.title||`知识片段 ${x.chunk_index+1}`)}</strong></div><div>${badge(x.analysis_status)} ${badge(x.retrieval_status)} ${badge(x.status)}</div></summary>
  <div class="chunk-meta">类型：${esc(x.chunk_type)}　策略：${esc(x.strategy_name||"未关联")}　标签：${esc((x.tags||[]).join("、")||"无")}</div>
  <div class="context-box"><strong>AI 生成背景</strong><p>${esc(x.context||"暂无 Context")}</p></div><div class="summary"><strong>AI 摘要</strong><p>${esc(x.summary||"暂无摘要")}</p></div>
  <div class="chunk-content"><strong>原始知识</strong>${rich(x.content,x.images)}</div>
  <div class="chunk-editor"><form class="content-context-form"><label>Context（最多100字符）<textarea name="context" maxlength="100">${esc(x.context||"")}</textarea></label><label>原始正文<textarea name="content">${esc(x.content)}</textarea></label><button>保存正文与 Context 并重新向量化</button></form>
  <form class="summary-form"><label>Summary<textarea name="summary">${esc(x.summary||"")}</textarea></label><button class="secondary">仅保存 Summary</button></form>
  <form class="metadata-form form-grid"><label>Title<input name="title" value="${esc(x.title||"")}"></label><label>Chunk Type<select name="chunk_type">${chunkTypes.map(t=>`<option ${t===x.chunk_type?"selected":""}>${t}</option>`).join("")}</select></label><label>Strategy<select name="strategy_id">${strategyOptions(x)}</select></label><label>Tags（逗号分隔）<input name="tags" value="${esc((x.tags||[]).join(","))}"></label><button class="full secondary">保存 Metadata</button></form>
  <div class="chunk-actions"><button data-action="regenerate">重新生成 Context</button><button data-action="review" ${x.analysis_status==="reviewed"?"disabled":""}>标记已审核</button><button data-action="retrieval">${x.retrieval_status==="active"?"禁用检索":"恢复检索"}</button><button data-action="reindex">重新向量化</button></div><p class="operation-message"></p></div></details>`).join("")}</section>`;
  document.querySelector("#raw").onclick=async()=>{const x=await Api.request(`/api/knowledge/documents/${id}/raw-url`);window.open(x.url,"_blank","noopener");};
  document.querySelector("#parsed").onclick=()=>document.querySelectorAll("details.chunk").forEach(x=>x.open=true);bindChunkEditors(id);}
function bindChunkEditors(documentId){document.querySelectorAll("[data-chunk]").forEach(card=>{const chunkId=card.dataset.chunk,msg=card.querySelector(".operation-message"),run=async(path,options)=>{msg.textContent="处理中…";try{await Api.request(path,options);await detail(documentId);}catch(e){msg.textContent=e.message;}};
  card.querySelector(".content-context-form").onsubmit=e=>{e.preventDefault();const f=new FormData(e.currentTarget);run(`/api/knowledge/chunks/${chunkId}/content-context`,{method:"PATCH",body:JSON.stringify({content:f.get("content"),context:f.get("context")})});};
  card.querySelector(".summary-form").onsubmit=e=>{e.preventDefault();const f=new FormData(e.currentTarget);run(`/api/knowledge/chunks/${chunkId}/summary`,{method:"PATCH",body:JSON.stringify({summary:f.get("summary")})});};
  card.querySelector(".metadata-form").onsubmit=e=>{e.preventDefault();const f=new FormData(e.currentTarget),payload={title:f.get("title"),chunk_type:f.get("chunk_type"),strategy_id:f.get("strategy_id")||null,tags:String(f.get("tags")||"").split(/[,，]/).map(x=>x.trim()).filter(Boolean)};run(`/api/knowledge/chunks/${chunkId}/metadata`,{method:"PATCH",body:JSON.stringify(payload)});};
  card.querySelector('[data-action="regenerate"]').onclick=()=>run(`/api/knowledge/chunks/${chunkId}/regenerate-context`,{method:"POST"});card.querySelector('[data-action="review"]').onclick=()=>run(`/api/knowledge/chunks/${chunkId}/review`,{method:"POST"});
  card.querySelector('[data-action="retrieval"]').onclick=()=>{const current=card.querySelector('[data-action="retrieval"]').textContent.includes("禁用")?"disabled":"active";run(`/api/knowledge/chunks/${chunkId}/retrieval-status`,{method:"PATCH",body:JSON.stringify({retrieval_status:current})});};card.querySelector('[data-action="reindex"]').onclick=()=>run(`/api/knowledge/chunks/${chunkId}/reindex`,{method:"POST"});});}
pages.search=async()=>{content.innerHTML=`<section class="panel"><h2>知识语义检索</h2><p>Qdrant 只召回 chunk_id，完整内容从 PostgreSQL 批量读取。</p>
  <form id="search" class="inline-form"><input name="query" required><input name="top_k" type="number" value="8"><button>检索</button></form><div id="results"></div></section>`;
  document.querySelector("#search").onsubmit=async e=>{e.preventDefault();const f=new FormData(e.currentTarget),d=await Api.request("/api/knowledge/search",{method:"POST",body:JSON.stringify({query:f.get("query"),top_k:Number(f.get("top_k"))})});
  document.querySelector("#results").innerHTML=d.items.map(x=>`<article class="search-result"><div><strong>${esc(x.title)}</strong> <span>${Number(x.score).toFixed(4)}</span> ${badge(x.analysis_status)}</div><p><b>Context：</b>${esc(x.context||"-")}</p><p><b>Summary：</b>${esc(x.summary||"-")}</p><div class="search-content">${esc(x.content)}</div><small>策略：${esc(x.strategy_name||"-")} · 标签：${esc((x.tags||[]).join("、")||"-")} · 来源：${esc(x.source_name||x.document_name)}</small><button class="link-button" data-doc="${x.document_id}">查看文档 / Chunk ${x.chunk_index}</button></article>`).join("")||"没有结果";bindDocs();};};
pages.qa=async()=>{content.innerHTML=`<section class="chat-shell"><div id="messages" class="messages"><article class="assistant-message"><strong>AlphaHub</strong><p>我只依据已入库知识回答。</p></article></div>
  <form id="ask" class="chat-form"><textarea name="question" required></textarea><button>发送</button></form></section>`;document.querySelector("#ask").onsubmit=async e=>{e.preventDefault();const q=e.currentTarget.question.value.trim(),box=document.querySelector("#messages");
  box.innerHTML+=`<article class="user-message"><p>${esc(q)}</p></article>`;e.currentTarget.question.value="";const p=document.createElement("article");p.className="assistant-message";p.textContent="正在回答…";box.appendChild(p);
  try{const d=await Api.request("/api/knowledge/ask",{method:"POST",body:JSON.stringify({question:q,top_k:8,neighbor_window:1})});p.innerHTML=`<strong>AlphaHub</strong><p>${esc(d.answer)}</p><div class="sources"><h4>知识来源</h4>
  ${d.sources.map(x=>`<button class="source-link" data-doc="${x.document_id}">${esc(x.document_name)} · Chunk ${x.chunk_index} · ${esc(x.chunk_title)} · ${esc(x.strategy||"未关联")} · ${esc(x.chunk_type)} · ${esc(x.analysis_status)} · ${Number(x.score).toFixed(4)}</button>`).join("")}</div>`;bindDocs();}catch(x){p.textContent=x.message;}};};
async function strategyPage(core){const d=await Api.request("/api/strategies"),s=core?d.filter(x=>x.category==="core_strategy"):d;content.innerHTML=`<div class="strategy-grid">${s.map(x=>`<article class="strategy-card"><span>${esc(x.category)}</span><h2>${esc(x.name)}</h2>
  <code>${esc(x.code)}</code><p>${esc(x.description||"暂无说明")}</p><footer>v${esc(x.version)} <strong>${x.chunk_count} Chunks</strong></footer></article>`).join("")}</div>`;}
pages.strategies=()=>strategyPage(false);pages.tactics=()=>strategyPage(true);
pages.tags=async()=>{const d=await Api.request("/api/tags");content.innerHTML=`<section class="panel"><h2>标签管理</h2><div class="tag-cloud">${d.map(x=>`<span><strong>${esc(x.name)}</strong><small>${x.chunk_count}</small></span>`).join("")||"暂无标签"}</div></section>`;};
pages.settings=async()=>{const d=await Api.request("/api/system/config"),sets=[["DeepSeek",d.deepseek],["Embedding",d.embedding],["MinIO",d.minio],["Qdrant",d.qdrant]];
  content.innerHTML=`<div class="settings-grid">${sets.map(([n,v])=>`<section class="panel"><div class="panel-title"><h2>${n}</h2><button class="secondary tester" data-test="${n.toLowerCase()}">测试</button></div>
  <dl>${Object.entries(v).map(x=>`<div><dt>${esc(x[0])}</dt><dd>${esc(x[1])}</dd></div>`).join("")}</dl><p class="test-result"></p></section>`).join("")}
  <section class="panel"><h2>PostgreSQL / Redis</h2><button class="secondary tester" data-test="postgresql">测试 PostgreSQL</button> <button class="secondary tester" data-test="redis">测试 Redis</button><p class="test-result"></p></section></div>`;
  document.querySelectorAll(".tester").forEach(b=>b.onclick=async()=>{const o=b.closest(".panel").querySelector(".test-result");o.textContent="测试中…";try{const x=await Api.request(`/api/system/test/${b.dataset.test}`,{method:"POST"});o.textContent=x.success?`连接正常${x.dense_dimension?"，Dense "+x.dense_dimension+"维，Sparse "+x.sparse_terms+"项":""}`:"连接异常";}catch(x){o.textContent=x.message;}});};
document.querySelector("#logout").onclick=async()=>{try{await Api.request("/api/auth/logout",{method:"POST"});}finally{Api.clearLogin();location.href="/login.html";}};
(async()=>{try{await Api.request("/api/auth/check");document.querySelector("#username").textContent=localStorage.getItem(Api.usernameKey)||"用户";menu();await openPage("总览 Dashboard");}
catch(_){Api.clearLogin();location.href="/login.html";}})();
