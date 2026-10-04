import { stages, sessions, filterSessions, summary, percentile, getTurns } from './diagnostics-data.mjs';
const $=id=>document.getElementById(id);
let current=null, selected=null, activeTab='chain';
const ms=v=>v===null?'—':`${Math.round(v)} <em>ms</em>`;
const duration=v=>`${Math.floor(v/60)}m ${v%60}s`;
const status=s=>`<span class="status ${s==='异常'?'error':''}">${s}</span>`;
function renderOverview(){
  const rows=filterSessions($('search').value,$('statefilter').value,$('rolefilter').value), stats=summary(rows);
  $('sessioncount').textContent=stats.count; $('normalcount').textContent=`正常 ${stats.normal} · 异常 ${stats.count-stats.normal}`;
  $('responsep95').innerHTML=ms(stats.responseP95); $('responsep50').textContent=`P95 · P50 ${stats.responseP50??'—'} ms`;
  $('stopp95').innerHTML=ms(stats.stopP95); $('stopp50').textContent=`P95 · P50 ${stats.stopP50??'—'} ms`;
  $('errorrate').textContent=stats.count?`${((stats.count-stats.normal)/stats.count*100).toFixed(1)}%`:'—';
  $('rowcount').textContent=`共 ${rows.length} 个会话`;
  $('sessionrows').innerHTML=rows.length?rows.map(s=>`<tr><td>${s.time}<br><span class="caption">10 月 4 日</span></td><td><a class="sessionlink mono" href="#session/${s.id}">${s.id}</a></td><td>${s.role}<br><span class="caption">${s.engine} · ${s.model}</span></td><td>${duration(s.duration)}<br><span class="caption">${s.turns} 轮</span></td><td class="${s.response>1200?'warn':''}">${s.response} ms</td><td>${s.interruption} ms</td><td>${status(s.state)}</td><td>${s.coverage}%<br><span class="caption">${s.errors?'缺少部分客户端回执':'客户端回执完整'}</span></td></tr>`).join(''):'<tr><td colspan="8" class="empty">没有匹配会话，请调整 Session ID 或筛选条件。</td></tr>';
  renderTrend(rows); renderModules(rows);
}
function renderModules(rows){
 const turns=rows.flatMap(getTurns);
 $('modulemetrics').innerHTML=stages.map(([key,label,color])=>{
  const values=turns.flatMap(t=>t.spans.filter(s=>s.key===key).map(s=>s.duration));const p=percentile(values,.95);
  return `<div class="stageitem"><div class="stagecap"><span>${label}</span><span>${p===null?'—':Math.round(p)+' ms'}</span></div><div class="barbg"><div class="barfill" style="background:${color};width:${p===null?0:Math.min(100,p/8)}%"></div></div><span class="caption">n=${values.length} · ${values.length?'已采集':'无样本'}</span></div>`;
 }).join('');
}
function renderTrend(rows){
 const hours=[10,11,12,13,14,15];
 const groups=hours.map(h=>rows.filter(s=>Number(s.time.split(':')[0])===h));
 const points=groups.map(g=>summary(g)); const x=i=>47+i*88,y=v=>170-v/2000*140;
 const segments=key=>{let parts=[],part=[];points.forEach((p,i)=>{if(p[key]===null){if(part.length)parts.push(part);part=[]}else part.push([x(i),y(p[key])])});if(part.length)parts.push(part);return parts.map(p=>p.map(([a,b],i)=>`${i?'L':'M'}${a} ${b}`).join(' '))};
 let svg='<svg viewBox="0 0 540 205" role="img" aria-label="响应与打断延迟趋势">';
 [0,500,1000,1500,2000].forEach(v=>svg+=`<line x1="40" y1="${y(v)}" x2="510" y2="${y(v)}" stroke="#edf0f4"/><text x="0" y="${y(v)+3}">${v}</text>`);
 for(const [key,color] of [['responseP95','#6888da'],['stopP95','#61aa90']]){
  segments(key).forEach(d=>svg+=`<path d="${d}" fill="none" stroke="${color}" stroke-width="2"/>`);
  points.forEach((p,i)=>{if(p[key]!==null)svg+=`<circle cx="${x(i)}" cy="${y(p[key])}" r="3" fill="${color}"><title>${hours[i]}:00 · ${p[key]} ms</title></circle>`});
 }
 hours.forEach((h,i)=>svg+=`<text x="${x(i)-13}" y="195">${h}:00</text>`);$('trend').innerHTML=svg+'</svg>';
}
function route(){
 const id=location.hash.startsWith('#session/')?location.hash.slice(9):null;
 current=sessions.find(s=>s.id===id)||null;
 $('overview').classList.toggle('hide',Boolean(current));$('detail').classList.toggle('hide',!current);
 $('crumbdetail').textContent=current?'　/　会话详情':'';$('notice').textContent=id&&!current?'找不到这个示例 Session ID。':'';
 if(current){selected=getTurns(current)[0];activeTab='chain';renderDetail()}else renderOverview();
}
function renderDetail(){
 $('detailid').textContent=current.id;$('turncount').textContent=`${current.turns} 轮对话`;
 $('sessionmeta').innerHTML=`<span>角色<strong>${current.role}</strong></span><span>引擎<strong>${current.engine}</strong></span><span>模型<strong>${current.model}</strong></span><span>时长<strong>${duration(current.duration)}</strong></span><span>状态 ${status(current.state)}</span><span>采集覆盖<strong>${current.coverage}%</strong></span>`;
 $('wave').innerHTML=Array.from({length:55},(_,i)=>`<i style="height:${5+(i*13)%23}px"></i>`).join('');
 $('agentcommand').textContent=`get_session_diagnostics("${current.id}")`;
 $('pin').textContent=sessionStorage.getItem(`pin:${current.id}`)==='yes'?'★ 已标记长期保留':'☆ 长期保留录音';
 renderTurns();renderTurn();
}
function renderTurns(){
 $('turns').innerHTML=getTurns(current).map(t=>`<button class="turn ${selected.id===t.id?'selected':''}" data-turn="${t.id}" aria-pressed="${selected.id===t.id}"><div class="turntop"><span>第 ${String(t.index).padStart(2,'0')} 轮</span><span>${t.interrupted?'有效打断 · '+t.stop+' ms':t.slow?'慢响应 · '+t.total+' ms':t.total+' ms'}</span></div><div class="speech"><span class="speaker">用户</span><span>${t.user}</span></div><div class="speech"><span class="speaker agent">助手</span><span>${t.assistant}</span></div></button>`).join('');
 $('turns').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{selected=getTurns(current).find(t=>t.id===button.dataset.turn);renderTurns();renderTurn()}));
}
function renderTurn(){
 $('turntitle').textContent=`第 ${String(selected.index).padStart(2,'0')} 轮 · 诊断详情`;
 $('turnstatus').textContent=selected.interrupted?'有效打断':selected.slow?'慢响应':'正常回复';$('turnstatus').classList.toggle('error',selected.slow);
 const max=selected.total*1.13;
 $('chain').innerHTML=`<div class="waterfall"><div class="watercap"><span class="sub">用户语音结束为 0 ms</span><span class="mono">${selected.id}</span></div><div class="axis"><span>0</span><span>${Math.round(max/4)}</span><span>${Math.round(max/2)}</span><span>${Math.round(max*3/4)}</span><span>${Math.round(max)} ms</span></div>${selected.spans.map(s=>{const [,label,color]=stages.find(a=>a[0]===s.key);return `<div class="spanrow"><span>${label}</span><div class="track"><button class="spanbar" data-stage="${s.key}" aria-label="查看 ${label} 耗时" style="left:${s.start/max*100}%;width:${s.duration/max*100}%;background:${color}" title="${s.start}–${s.start+s.duration} ms"></button><span class="spanlabel" style="left:${(s.start+s.duration)/max*100+1}%">${s.duration}</span></div></div>`}).join('')}<div class="milestones"><div>语音结束<strong>0 ms</strong></div><div>首段文本<strong>${selected.spans.find(s=>s.key==='tts').start} ms</strong></div><div>客户端首播<strong>${selected.total} ms</strong></div></div><div class="selection" id="stageselection">点击阶段色条查看时间范围与关联事件。</div><div class="focusnote">并行阶段真实重叠；这里的 TTS 为首音等待，LLM 为首文本等待。</div></div>`;
 $('chain').querySelectorAll('[data-stage]').forEach(button=>button.addEventListener('click',()=>{const span=selected.spans.find(s=>s.key===button.dataset.stage);$('stageselection').textContent=`${stages.find(s=>s[0]===span.key)[1]} · ${span.start} → ${span.start+span.duration} ms · 耗时 ${span.duration} ms · 关联 ${selected.id}`;}));
 const stop=selected.stop, detection=Math.round(stop*.25),decision=Math.round(stop*.375),dispatch=Math.round(stop*.125),client=stop-detection-decision-dispatch;
 $('stop').innerHTML=stop===null?'<div class="empty">该轮没有有效打断；不会将普通进度或自然播放结束计为打断。</div>':`<div class="stopsteps">${[['检测',detection],['语义确认',decision],['取消发送',dispatch],['客户端停播',client]].map(([n,v])=>`<div>${n}<strong>${v} <span class="caption">ms</span></strong></div>`).join('')}</div><div class="waterfall"><h3>总打断延迟 ${stop} ms</h3><p class="sub">用户有效打断开口 → 客户端旧输出停止</p><div class="selection">标签：stop · 来源：规则<br>interruption_id: interrupt-${current.id}-${selected.id}<br>旧输出 speech_id: speech-${selected.index-1}<br>明确收到 stopped 回执，普通 progress 不结束计时。</div></div>`;
 $('logs').innerHTML=`<div class="loglist">${selected.spans.map(s=>`<div class="logrow"><time>${s.start} ms</time><code>${s.key}</code><span>阶段开始 · ${selected.id}<br><span class="caption">duration_ms=${s.duration} · outcome=ok</span></span></div>`).join('')}<div class="logrow"><time>${selected.total} ms</time><code>playback</code><span>client_playback_started · ${selected.id}</span></div></div>`;
 setTab(activeTab);
}
function setTab(name){activeTab=name;for(const id of ['chain','stop','logs'])$(id).classList.toggle('hide',id!==name);document.querySelectorAll('[data-tab]').forEach(b=>{b.classList.toggle('active',b.dataset.tab===name);b.setAttribute('aria-selected',String(b.dataset.tab===name))})}
for(const id of ['search','statefilter','rolefilter'])$(id).addEventListener(id==='search'?'input':'change',renderOverview);
$('back').addEventListener('click',()=>{location.hash='data'});
document.querySelectorAll('[data-tab]').forEach(b=>b.addEventListener('click',()=>setTab(b.dataset.tab)));
$('pin').addEventListener('click',()=>{const key=`pin:${current.id}`;sessionStorage.setItem(key,sessionStorage.getItem(key)==='yes'?'no':'yes');renderDetail();$('notice').textContent='仅更新本次浏览器 Demo 标记，不修改真实录音保留策略。'});
$('export').addEventListener('click',()=>{const blob=new Blob([JSON.stringify({schema_version:1,demo:true,session:current,turns:getTurns(current),completeness:{audio:'not_attached',metrics:'simulated',coverage:current.coverage}},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=`${current.id}-demo.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);$('notice').textContent='已导出本地示例诊断 JSON。'});
window.addEventListener('hashchange',route);route();
