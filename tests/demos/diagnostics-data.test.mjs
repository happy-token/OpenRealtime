import {test} from 'node:test';
import assert from 'node:assert/strict';
import {sessions,filterSessions,getTurns,percentile,summary} from '../../public/demos/diagnostics-data.mjs';
test('filters by session ID, role and anomaly without losing the original rows',()=>{
 assert.equal(filterSessions('024').length,1);
 assert.ok(filterSessions('', '异常').every(s=>s.errors>0));
 assert.ok(filterSessions('', 'all','Samantha').every(s=>s.role==='Samantha'));
 assert.equal(filterSessions('absent').length,0);assert.equal(sessions.length,24);
});
test('missing metrics remain null and totals derive from the filtered turns',()=>{
 assert.equal(percentile([], .95),null);assert.equal(summary([]).responseP95,null);
 const rows=filterSessions('024');assert.equal(summary(rows).responseP95,percentile(getTurns(rows[0]).map(t=>t.total),.95));
});
test('every session has independently selectable turns and overlapping spans',()=>{
 for(const s of sessions){const turns=getTurns(s);assert.equal(turns.length,s.turns);assert.equal(new Set(turns.map(t=>t.id)).size,s.turns);
 for(const t of turns){assert.equal(t.spans.length,10);assert.ok(t.spans.every(p=>p.start>=0&&p.duration>0&&p.start+p.duration<=t.total+1));assert.equal(t.spans.find(p=>p.key==='memory').start,t.spans.find(p=>p.key==='retrieval').start)}
 assert.ok(turns.some(t=>t.interrupted&&t.stop>0));}
});
