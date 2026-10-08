DASHBOARD_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>LiteClaw Eval</title>
  <style>
    :root{color-scheme:dark;--bg:#101218;--panel:#191d27;--line:#2b3242;--text:#eef2ff;--muted:#9ba7bd;--accent:#7dd3fc;--ok:#86efac;--bad:#fca5a5}
    *{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#0b1020,#15111e);color:var(--text);font:15px/1.5 system-ui,sans-serif;min-height:100vh}
    main{max-width:1100px;margin:auto;padding:40px 24px}header{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:28px}h1{font-size:34px;margin:0}p{color:var(--muted);margin:6px 0}.key{display:flex;gap:8px}input,button{border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:#0f1320;color:var(--text)}button{cursor:pointer;background:#203044;border-color:#36506c}button:hover{border-color:var(--accent)}section{background:rgba(25,29,39,.92);border:1px solid var(--line);border-radius:14px;padding:20px;margin:16px 0}section>div:first-child{display:flex;align-items:center;justify-content:space-between}h2{font-size:18px;margin:0 0 14px}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-size:12px;text-transform:uppercase}.passed{color:var(--ok)}.failed,.error{color:var(--bad)}.empty{padding:24px;text-align:center;color:var(--muted)}#status{min-height:24px;color:var(--accent)}@media(max-width:700px){header{display:block}.key{margin-top:16px;flex-wrap:wrap}.scroll{overflow:auto}}
  </style>
</head>
<body><main>
  <header><div><h1>LiteClaw Eval</h1><p>保存回归案例，运行真实 Agent loop，追踪通过率。</p></div><div class="key"><input id="key" type="password" placeholder="服务 API Key"><button onclick="saveKey()">保存并刷新</button></div></header>
  <div id="status"></div>
  <section><div><h2>评测案例</h2><button onclick="runEvals()">运行已启用案例</button></div><div class="scroll"><table><thead><tr><th>名称</th><th>Prompt</th><th>期望包含</th><th>状态</th></tr></thead><tbody id="cases"></tbody></table></div></section>
  <section><div><h2>最近运行</h2><button onclick="refresh()">刷新</button></div><div class="scroll"><table><thead><tr><th>时间</th><th>通过率</th><th>通过</th><th>失败</th><th>错误</th></tr></thead><tbody id="runs"></tbody></table></div></section>
</main><script>
const keyInput=document.querySelector('#key'),statusBox=document.querySelector('#status');
keyInput.value=sessionStorage.getItem('liteclawApiKey')||'';
function saveKey(){sessionStorage.setItem('liteclawApiKey',keyInput.value);refresh()}
async function api(path,options={}){const key=sessionStorage.getItem('liteclawApiKey')||'';options.headers={...(options.headers||{}),...(key?{'Authorization':`Bearer ${key}`}:{})};const response=await fetch(path,options);if(!response.ok)throw new Error(`${response.status} ${await response.text()}`);return response.status===204?null:response.json()}
function cell(value,cls=''){const td=document.createElement('td');td.textContent=value??'—';td.className=cls;return td}
async function refresh(){statusBox.textContent='正在读取…';try{const [cases,runs]=await Promise.all([api('/v1/evals/cases'),api('/v1/evals/runs')]);const cb=document.querySelector('#cases');cb.replaceChildren();for(const item of cases){const tr=document.createElement('tr');tr.append(cell(item.name),cell(item.prompt),cell(item.expected_contains),cell(item.enabled?'启用':'停用'));cb.append(tr)}if(!cases.length)cb.innerHTML='<tr><td colspan="4" class="empty">尚无案例，可通过 API 或从 Agent run 回流。</td></tr>';const rb=document.querySelector('#runs');rb.replaceChildren();for(const item of runs){const tr=document.createElement('tr'),rate=item.total?`${Math.round(item.passed/item.total*100)}%`:'—';tr.append(cell(new Date(item.started_at).toLocaleString()),cell(rate,'passed'),cell(item.passed),cell(item.failed,'failed'),cell(item.errors,'error'));rb.append(tr)}if(!runs.length)rb.innerHTML='<tr><td colspan="5" class="empty">尚无运行记录。</td></tr>';statusBox.textContent=''}catch(error){statusBox.textContent=`读取失败：${error.message}`}}
async function runEvals(){statusBox.textContent='评测运行中…';try{const run=await api('/v1/evals/run',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});statusBox.textContent=`完成：${run.passed}/${run.total} 通过`;await refresh()}catch(error){statusBox.textContent=`运行失败：${error.message}`}}
refresh();
  </script></body></html>"""
