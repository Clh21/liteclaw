HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>LiteClaw 聊天记录</title>
<style>
body{font:16px/1.6 system-ui,sans-serif;margin:0;background:#f5f6f8;color:#20242a}
main{max-width:1000px;margin:auto;padding:28px 18px 60px}h1{margin:0}h2{font-size:1.2rem}
section{background:white;border:1px solid #e2e5ea;border-radius:12px;margin:18px 0;padding:20px}
label{display:block;margin:12px 0 4px;font-weight:600}input,select,button{font:inherit;padding:9px;border:1px solid #b8c0cb;border-radius:7px;box-sizing:border-box}
input,select{max-width:100%}input[type=text],input[type=password]{width:100%}
button{background:#164a8a;color:#fff;border:0;cursor:pointer;margin:8px 8px 8px 0}button:disabled{opacity:.5}
button.danger{background:#9d2431}.row{display:flex;gap:14px;flex-wrap:wrap}.row>div{flex:1;min-width:180px}
.muted{color:#59616c}.item{border-top:1px solid #e5e8ec;padding:9px 0}.pill{display:inline-block;background:#e8f0fa;border-radius:10px;padding:2px 8px;margin:3px}
#status{min-height:1.5em}.error{color:#a31927}.ok{color:#14613b}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f7f8fa;padding:12px}
</style></head><body><main>
<h1>聊天记录分析</h1><p class="muted">导入你自行导出的 TXT、CSV 或 JSON 记录。原文件不会保存；分析结论请对照原话核实。若配置了外部 AI 模型，分析时会向该服务发送所选记录的部分内容。</p>
<section><h2>连接</h2><label for="token">服务 API Key 或用户 Token</label><input id="token" type="password" autocomplete="off" placeholder="如服务要求鉴权，请在这里填写"><p class="muted">令牌仅保存在当前标签页。</p></section>
<section><h2>导入记录</h2><div class="row"><div><label for="file">聊天导出文件</label><input id="file" type="file" accept=".txt,.csv,.json"></div><div><label for="self">我在记录中的昵称</label><input id="self" type="text" value="我"></div></div><div class="row"><div><label for="conversation">会话名称（TXT 必填）</label><input id="conversation" type="text"></div><div><label for="zone">时区</label><input id="zone" type="text" value="Asia/Shanghai"></div></div><button id="upload">导入</button></section>
<section><h2>来源</h2><button id="refresh">刷新来源</button><label for="sources">选择记录来源</label><select id="sources"><option value="">全部来源</option></select><div id="source-list"></div></section>
<section><h2>分析与报告</h2><div class="row"><div><label for="contact">联系人昵称（可选）</label><input id="contact" type="text" placeholder="按发言人筛选"></div><div><label for="period">报告周期</label><select id="period"><option value="week">周报</option><option value="month">月报</option><option value="year">年报</option></select></div><div><label for="anchor">报告日期</label><input id="anchor" type="date"></div></div><button id="analyze">分析聊天</button><button id="report">生成报告</button><p id="status" role="status"></p><div id="result"></div></section>
</main><script>
const $=id=>document.getElementById(id);
$('token').value=sessionStorage.getItem('liteclaw-chat-token')||'';
$('token').addEventListener('input',()=>sessionStorage.setItem('liteclaw-chat-token',$('token').value));
$('anchor').value=new Date().toLocaleDateString('en-CA');
function status(message,error=false){$('status').textContent=message;$('status').className=error?'error':'ok'}
async function api(path,options={}){const token=$('token').value.trim();const headers={...(options.headers||{})};if(token)headers.Authorization='Bearer '+token;
const response=await fetch('/v1/chat-records'+path,{...options,headers});let data;try{data=await response.json()}catch{data={}};
if(!response.ok)throw new Error(data.detail?.code||data.detail||'请求失败（'+response.status+'）');return data}
function line(parent,text,className='item'){const node=document.createElement('div');node.className=className;node.textContent=text;parent.append(node);return node}
async function sources(){const data=await api('/sources');const select=$('sources');const selected=select.value;select.replaceChildren(new Option('全部来源',''));
const list=$('source-list');list.replaceChildren();for(const source of data.sources){select.add(new Option(`${source.filename} · ${source.message_count} 条`,source.id));
const row=document.createElement('div');row.className='item';row.append(document.createTextNode(`${source.filename} · ${source.conversation||'多个会话'} · ${source.message_count} 条 · ${source.first_at||''} 至 ${source.last_at||''} `));
const remove=document.createElement('button');remove.className='danger';remove.textContent='删除';remove.onclick=async()=>{if(!confirm('删除这份导入记录？'))return;try{await api('/sources/'+encodeURIComponent(source.id),{method:'DELETE'});await sources();status('已删除来源')}catch(error){status(String(error),true)}};row.append(remove);list.append(row)}
select.value=selected;if(!select.value)select.value=''}
function heading(parent,title){const h=document.createElement('h3');h.textContent=title;parent.append(h)}
async function render(data){const root=$('result');root.replaceChildren();line(root,`${data.summary||'分析结果'} 消息 ${data.message_count} 条；模式：${data.analysis_mode}`,'muted');
const byId=new Map(Object.entries(data.evidence||{}));
function evidence(parent,ids){for(const id of ids||[]){const m=byId.get(id);line(parent,m?`${m.sent_at} ${m.sender}: ${m.content}`:`证据消息 ID：${id}`,'muted')}}
heading(root,'活动');line(root,`参与者：${Object.entries(data.participants).map(([name,n])=>name+' '+n+' 条').join('、')||'无'}`);
for(const [day,n] of Object.entries(data.activity_by_day))line(root,`${day}：${n} 条`);
for(const [title,key] of [['待核实事项','open_items'],['确认完成','completed_items']]){heading(root,title);if(!data[key].length)line(root,'无');for(const item of data[key]){const box=document.createElement('div');box.className='item';line(box,`${item.is_self?'我':'其他人'}：${item.text}`,'');evidence(box,item.evidence_ids);root.append(box)}}
for(const [title,key] of [['做得好的地方','strengths'],['可改进的地方','improvements'],['对方的沟通表现','counterpart']]){heading(root,title);const items=data.communication?.[key]||[];if(!items.length)line(root,'暂无有证据支持的观察');for(const item of items){const box=document.createElement('div');box.className='item';line(box,item.text,'');evidence(box,item.evidence_ids);root.append(box)}}}
$('refresh').onclick=async()=>{try{await sources();status('来源已刷新')}catch(error){status(String(error),true)}};
$('upload').onclick=async()=>{const file=$('file').files[0];if(!file){status('请选择文件',true);return}const params=new URLSearchParams({filename:file.name,self_sender:$('self').value,timezone:$('zone').value});if($('conversation').value)params.set('conversation',$('conversation').value);
try{status('正在导入…');const result=await api('/import?'+params,{method:'POST',body:file});await sources();$('sources').value=result.id;status(`已导入 ${result.message_count} 条消息`)}catch(error){status(String(error),true)}};
$('analyze').onclick=async()=>{try{status('正在分析…');const data=await api('/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_id:$('sources').value||null,contact:$('contact').value||null,timezone:$('zone').value})});await render(data);status('分析完成')}catch(error){status(String(error),true)}};
$('report').onclick=async()=>{try{status('正在生成报告…');const data=await api('/reports',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_id:$('sources').value||null,period:$('period').value,anchor_date:$('anchor').value,timezone:$('zone').value})});await render(data);status('报告已生成')}catch(error){status(String(error),true)}};
sources().catch(error=>status(String(error),true));
</script></body></html>"""
