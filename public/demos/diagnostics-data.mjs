export const stages = [
  ['vad','VAD / 输入','#8596b0'],['asr','ASR','#56a5ae'],['endpoint','语义端点','#c99f55'],
  ['memory','记忆','#9a87b8'],['retrieval','知识检索','#8d78ac'],['llm','LLM','#6888da'],
  ['tools','工具 / Agent','#a180b1'],['tts','TTS','#61aa90'],['transport','传输','#b99367'],['playback','播放缓冲','#a1adb9'],
];
export const sessions = Array.from({length: 24}, (_, i) => ({
  id: `vs_20261004_${String(24-i).padStart(3,'0')}`, role: ['若水','Samantha','星澜'][i%3],
  model: ['DeepSeek V3','GPT Realtime','Qwen'][i%3], engine: i%3===1?'Native':'Cascaded',
  time: `${String(15-Math.floor(i/4)).padStart(2,'0')}:${String(55-(i%4)*12).padStart(2,'0')}`,
  duration: 160+(i*37)%520, turns: 5+(i*3)%18, state: i%7===0?'异常':'正常',
  response: i%7===0?1480+i*12:590+(i*43)%490, interruption: 160+(i*17)%180,
  coverage: i%7===0?85:100, errors: i%7===0?2:0,
}));
export function percentile(values, p) {
  if (!values.length) return null;
  const sorted=[...values].sort((a,b)=>a-b); return sorted[Math.max(0,Math.ceil(p*sorted.length)-1)];
}
export function filterSessions(query='', state='all', role='all') {
  const q=query.trim().toLowerCase();
  return sessions.filter(s=>(!q||s.id.toLowerCase().includes(q))&&(state==='all'||s.state===state)&&(role==='all'||s.role===role));
}
export function summary(rows) {
  const turns=rows.flatMap(getTurns);
  return {count:rows.length,normal:rows.filter(s=>s.state==='正常').length,
    responseP50:percentile(turns.map(t=>t.total),.5),responseP95:percentile(turns.map(t=>t.total),.95),
    stopP50:percentile(turns.filter(t=>t.stop!==null).map(t=>t.stop),.5),stopP95:percentile(turns.filter(t=>t.stop!==null).map(t=>t.stop),.95)};
}
export function getTurns(session) {
  if (!session) return [];
  return Array.from({length:session.turns},(_,i)=>{
    const interrupted=i===2; const slow=session.errors>0&&i===1;
    const total = slow ? 1240 + Number(session.id.slice(-3))*10 : 610 + Number(session.id.slice(-3))*12;
    const scale = total/(slow?1240:820);
    const spans = [
      ['vad',0,70],['asr',30,125],['endpoint',155,95],['memory',250,25],['retrieval',250,60],
      ['llm',310,slow?730:310],['tools',405,slow?310:65],['tts',slow?1040:620,140],
      ['transport',slow?1180:760,30],['playback',slow?1210:790,30],
    ].map(([key,start,duration])=>({key,start:Math.round(start*scale),duration:Math.round(duration*scale)}));
    return {id:`turn-${i+1}`,index:i+1,interrupted,slow,total,stop:interrupted?session.interruption:null,spans,
      user:['今天帮我整理一下安排。','能说得更简短一些吗？','等等，先告诉我最重要的一件事。','那我先处理这个。'][i%4],
      assistant:['可以，我们先从今天最重要的事项开始。','好的，我用三点说明。','先完成你刚才提到的那项任务。','需要时我可以继续帮你拆解。'][i%4]};
  });
}

for (const session of sessions) session.response=percentile(getTurns(session).map(t=>t.total),.95);
