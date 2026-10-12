<script setup>
import { ref, computed } from 'vue';

const commPatient=ref('DEMO-P001'),commTemplate=ref('CHECKIN_REQUEST'),commHours=ref(24),commItems=ref([]),commNotice=ref('');
const token=ref(''),cases=ref([]),tasks=ref([]),selected=ref(null),audits=ref([]),trend=ref(null);
const comment=ref(''),choice=ref('escalate'),busy=ref(false),error=ref(''),activeTab=ref('queue');
const resolution=ref('handoff_documented'),resolutionNote=ref('');
const metrics=ref(null);
const inbox=ref([]),rosters=ref({}),timeline=ref([]),jobHealth=ref(null);
const shiftPatient=ref('DEMO-P001'), shiftStart=ref(''),shiftEnd=ref('');
const alertGroups=ref(null),evaluations=ref(null),evalPatient=ref('DEMO-P001');
const selectedHandoffTask=ref(''),handoffTarget=ref(''),handoffReason=ref('');
async function request(path,options={}) {
  if(!token.value) throw Error('請先輸入短效 clinician JWT');
  const r=await fetch(path,{...options,headers:{Authorization:'Bearer '+token.value,'Content-Type':'application/json',...(options.headers||{})}});
  if(!r.ok)throw Error(`${r.status}: ${await r.text()}`);
  return r.json();
}
async function refresh(){
  try {error.value='';const [cs,ts,ms]=await Promise.all([request('/v1/cases'),request('/v2/tasks'),request('/v2/metrics').catch(()=>null)]);
    cases.value=cs;tasks.value=ts.tasks;metrics.value=ms;
    inbox.value=(await request('/v3/handoffs/inbox').catch(()=>({handoffs:[]}))).handoffs;
    jobHealth.value=await request('/v3/ops/dispatch-jobs').catch(()=>null);
    alertGroups.value=await request('/v4/clinician/alert-groups').catch(()=>null);
  }catch(e){error.value=e.message}
}
async function open(c){
  try {error.value='';selected.value=await request('/v1/cases/'+encodeURIComponent(c.case_id));
    audits.value=(await request('/v1/audit/'+encodeURIComponent(c.case_id))).events;
    trend.value=await request('/v2/patients/'+encodeURIComponent(selected.value.patient_ref)+'/trends?days=7');
    timeline.value=(await request('/v3/patients/'+encodeURIComponent(selected.value.patient_ref)+'/timeline')).events;
    evalPatient.value=selected.value.patient_ref;
    evaluations.value=await request('/v4/clinician/evaluation/'+encodeURIComponent(evalPatient.value)).catch(()=>null);
    activeTab.value='case';
  }catch(e){error.value=e.message}
}
async function claim(t){
  busy.value=true;error.value='';try{await request('/v2/tasks/'+encodeURIComponent(t.task_id)+'/claim',{method:'POST'});await refresh();
  }catch(e){error.value=e.message}finally{busy.value=false}
}
async function resolveTask(t){
  if(resolutionNote.value.trim().length<12){error.value='必須寫下至少 12 字的處置原因';return}
  busy.value=true;error.value='';try{
    await request('/v2/tasks/'+encodeURIComponent(t.task_id)+'/resolve',{method:'POST',body:JSON.stringify({outcome:resolution.value,note:resolutionNote.value})});
    resolutionNote.value='';await refresh();
  }catch(e){error.value=e.message}finally{busy.value=false}
}
async function decide(){
  if(!selected.value)return;busy.value=true;error.value='';try{
    const r=await request('/v1/decisions',{method:'POST',body:JSON.stringify({case_id:selected.value.case_id,
      choice:choice.value,comment:comment.value,expected_version:selected.value.version})});
    comment.value='';await refresh();await open(selected.value);
    alert(`決策紀錄：${r.status}；所有病患通知均為模擬`);
  }catch(e){error.value=e.message}finally{busy.value=false}
}
async function fetchRoster(patientRef){
  try {error.value='';rosters.value[patientRef]=(await request('/v3/shifts/'+encodeURIComponent(patientRef))).shifts;
  } catch(e){error.value=e.message}
}
function utcIsoForLocal(v){return v ? new Date(v).toISOString():''}
async function registerShift(){
  busy.value=true;error.value='';try{
    await request('/v3/shifts',{method:'POST',body:JSON.stringify({patient_ref:shiftPatient.value,
      starts_at:utcIsoForLocal(shiftStart.value),ends_at:utcIsoForLocal(shiftEnd.value)})});
    await fetchRoster(shiftPatient.value);
  }catch(e){error.value=e.message}finally{busy.value=false}
}
function selectHandoffTask(){handoffTarget.value='';if(handoffTask.value)fetchRoster(handoffTask.value.patient_ref)}
async function offerHandoff(){
  if(!selectedHandoffTask.value)return;
  busy.value=true;error.value='';try{
    await request('/v3/tasks/'+encodeURIComponent(selectedHandoffTask.value)+'/handoff',{
      method:'POST',body:JSON.stringify({to_clinician_sub:handoffTarget.value,reason:handoffReason.value})});
    handoffReason.value='';await refresh();
  }catch(e){error.value=e.message}finally{busy.value=false}
}
async function decideHandoff(h,decision){
  busy.value=true;error.value='';try{
    await request('/v3/handoffs/'+encodeURIComponent(h.handoff_id)+'/'+decision,{method:'POST'});
    await refresh();
  }catch(e){error.value=e.message}finally{busy.value=false}
}
async function loadCommunications(){error.value='';try{commItems.value=(await request('/v5/clinician/communications/'+encodeURIComponent(commPatient.value))).messages}catch(e){error.value=e.message}}
async function draftCommunication(){busy.value=true;error.value='';try{const key='REQ-'+crypto.randomUUID().replaceAll('-','');await request('/v5/communications/drafts',{method:'POST',body:JSON.stringify({request_key:key,patient_ref:commPatient.value,template_code:commTemplate.value,due_hours:Number(commHours.value)})});commNotice.value='已建立草稿；需另外由醫護發佈';await loadCommunications()}catch(e){error.value=e.message}finally{busy.value=false}}
async function publishCommunication(m){busy.value=true;error.value='';try{await request('/v5/communications/'+encodeURIComponent(m.message_id)+'/publish',{method:'POST'});commNotice.value='已發佈至合成患者站內收件匣（無外部訊息）';await loadCommunications()}catch(e){error.value=e.message}finally{busy.value=false}}
const handoffTask=computed(()=>tasks.value.find(t=>t.task_id===selectedHandoffTask.value));
const handoffRoster=computed(()=>rosters.value[handoffTask.value?.patient_ref]||[]);
const reviewTask=computed(()=>tasks.value.find(t=>selected.value && t.case_id===selected.value.case_id && t.kind==='clinical_review'));
const canApprove=computed(()=>!!selected.value && selected.value.status==='AWAITING_CLINICIAN' && reviewTask.value?.status==='ACKNOWLEDGED');
const canDecide=computed(()=>!!selected.value && ['AWAITING_CLINICIAN','ESCALATION_REQUIRED','TECHNICAL_REVIEW'].includes(selected.value.status) && reviewTask.value?.status==='ACKNOWLEDGED');
const openTasks=computed(()=>tasks.value.filter(t=>t.status!=='COMPLETED'));
const statusLabel=s=>({OPEN:'待接單',ACKNOWLEDGED:'已接單',OVERDUE:'已逾期',COMPLETED:'已完成'})[s]||s;
</script>
<template>
<main>
  <header>
    <div><p class="eyebrow">CA6117 · HOSPITAL AT HOME · CARE COORDINATION RESEARCH PLATFORM</p>
      <h1>Clinical Care Coordination Workspace</h1>
      <p>連續監測 → 多代理推論 → 醫護接單 → 安全審核 → 後續追蹤</p>
    </div>
    <span class="warning">SYNTHETIC DATA ONLY · NOT FOR CLINICAL USE</span>
  </header>
  <section class="login"><label>Clinician Bearer Token（Demo JWT 或外部 OIDC Access Token，僅保存於記憶體）</label>
    <input type="password" v-model="token" placeholder="請使用短效 clinician token" autocomplete="off">
    <button @click="refresh">重新載入任務及案件</button>
  </section>
  <p v-if="error" role="alert" class="error">{{error}}</p>
  <section class="metrics" v-if="metrics">
    <div><small>待處理任務</small><strong>{{openTasks.length}}</strong></div>
    <div><small>量測筆數</small><strong>{{metrics.observation_count}}</strong></div>
    <div><small>已完成 Check-in 分流</small><strong>{{metrics.triaged_checkins}}</strong></div>
    <div><small>已完成任務</small><strong>{{metrics.task_counts.COMPLETED||0}}</strong></div>
  </section>
  <div class="tabs"><button :class="{'active-tab':activeTab==='queue'}" @click="activeTab='queue'">照護任務佇列</button><button :class="{'active-tab':activeTab==='case'}" @click="activeTab='case'">臨床案件證據</button><button :class="{'active-tab':activeTab==='handoff'}" @click="activeTab='handoff'">值班交接與追蹤</button><button :class="{'active-tab':activeTab==='alerts'}" @click="activeTab='alerts'">警報檢視與評估</button><button :class="{'active-tab':activeTab==='communications'}" @click="activeTab='communications'">站內訊息閉環</button></div>

  <div v-if="activeTab==='queue'" class="layout">
    <aside><h2>案件清單</h2><p v-if="!cases.length">尚未讀取或沒有案件</p>
      <button v-for="c of cases" :key="c.case_id" class="case" @click="open(c)">
        <strong>{{c.case_id}}</strong><small>{{c.patient_ref}}</small><span>{{c.status}}</span>
      </button>
    </aside>
    <article>
      <h2>待接單、逾時與後續追蹤</h2>
      <p>此佇列只是模擬醫護工作分派，沒有真正的醫院呼叫或傳呼系統。</p>
      <p v-if="!tasks.length">尚未有照護任務。請先處理案件或建立 synthetic Check-in。</p>
      <div v-for="t in tasks" :key="t.task_id" class="task">
        <div class="title-row"><strong>{{t.kind}}</strong><span class="priority">{{t.priority}} · {{statusLabel(t.status)}}</span></div>
        <small>Task ID: {{t.task_id}} · {{t.patient_ref}} · {{t.reason_code}}</small>
        <p>負責人：{{t.assigned_to||'尚未指派'}} · 截止時間：{{new Date(t.due_at*1000).toLocaleString()}}</p>
        <div class="task-actions">
          <button v-if="t.status==='OPEN'||t.status==='OVERDUE'" :disabled="busy" @click="claim(t)">接單 / 確認接手</button>
          <button v-if="t.case_id" class="secondary" @click="open({case_id:t.case_id})">查看案件</button>
        </div>
        <div v-if="t.kind!=='clinical_review'&&t.status==='ACKNOWLEDGED'" class="task-resolution">
          <label>模擬處置結果</label><select v-model="resolution">
            <option value="handoff_documented">交接已記錄（模擬）</option>
            <option value="demo_documented">已人工處理（模擬）</option>
            <option value="unable_to_reach">無法聯繫（不得關閉任務）</option>
          </select>
          <textarea v-model="resolutionNote" placeholder="記錄處理依據（不可輸入真實患者資料）"></textarea>
          <button :disabled="busy||resolutionNote.trim().length<12" @click="resolveTask(t)">紀錄任務處置</button>
        </div>
      </div>
    </article>
  </div>

  <div v-else-if="activeTab==='communications'" class="layout">
    <aside><h2>合成患者站內訊息</h2><p>僅預先核准的操作性訊息模板；不能輸入自由格式藥物或治療建議。</p>
      <label>Patient reference</label><input v-model="commPatient" placeholder="DEMO-P001" />
      <label>Template</label><select v-model="commTemplate"><option value="CHECKIN_REQUEST">Check-in request</option><option value="DEVICE_HELP">Device help</option><option value="FOLLOWUP_ACK">Follow-up status</option></select>
      <label>確認逾期（小時）</label><input type="number" min="1" max="168" v-model.number="commHours" />
      <button :disabled="busy" @click="draftCommunication">建立草稿</button>
      <button class="secondary" @click="loadCommunications">重新載入</button><p>{{commNotice}}</p>
    </aside>
    <article><h2>雙步驟人工審核與患者回執</h2><p>草稿 → 醫護發佈 → 患者確認 → 逾時任務。沒有 SMS、Email 或真實醫療傳呼。</p>
      <div v-for="m in commItems" :key="m.message_id" class="task">
        <strong>{{m.template_code}}</strong><p>{{m.content}}</p><small>{{m.message_id}} · {{m.state}}</small>
        <button v-if="m.state==='DRAFT'" :disabled="busy" @click="publishCommunication(m)">核對後發佈站內訊息</button>
      </div><p v-if="!commItems.length">沒有訊息。可先建立固定模板草稿。</p>
    </article>
  </div>

  <div v-else-if="activeTab==='alerts'" class="layout">
    <aside><h2>警報分組（唯讀）</h2><p>不會隱藏或降低任何原始照護任務的優先級。</p>
      <button @click="refresh">重新整理</button>
      <p v-if="alertGroups">原始 {{alertGroups.raw_active_task_count}} 筆 / 顯示 {{alertGroups.display_group_count}} 組 / 隱藏 0 筆</p>
      <h3>合成評估</h3><label>病人代碼</label><input v-model="evalPatient" placeholder="DEMO-P001"/>
      <button @click="request('/v4/clinician/evaluation/'+encodeURIComponent(evalPatient)).then(v=>evaluations=v).catch(e=>error=e.message)">載入評估</button>
      <pre v-if="evaluations">{{JSON.stringify(evaluations.metrics,null,2)}}</pre>
      <p>僅工作流程指標，不是 AI 敏感度、特異度或臨床有效性的證據。</p>
    </aside>
    <article><h2>工作優先排序與安全分組</h2><p>Urgent、Clinical Review、Escalation Follow-up 不做合併。每個 task_id 仍然獨立存在。</p>
      <div v-for="g in (alertGroups?.groups||[])" :key="g.task_ids.join('-')" class="task">
        <div class="title-row"><strong>{{g.kind}}</strong><span class="priority">{{g.priority}} · {{g.overdue?'已逾時':'待處理'}}</span></div>
        <p>{{g.patient_ref}} · {{g.reason_code}} · {{g.task_ids.length}} 筆原始任務</p>
        <small>{{g.task_ids.join('、')}}</small>
      </div>
      <p v-if="!alertGroups?.groups.length">暫無可顯示的警報。</p>
    </article>
  </div>
  <div v-else-if="activeTab==='handoff'" class="layout">
    <aside>
      <h2>排班與後續照護</h2>
      <p>合成資料、僅模擬值班。真實臨床值班需整合醫院排班系統。</p>
      <label>病人代碼</label><input v-model="shiftPatient" placeholder="DEMO-P001" />
      <label>開始時間</label><input type="datetime-local" v-model="shiftStart" />
      <label>結束時間</label><input type="datetime-local" v-model="shiftEnd" />
      <button :disabled="busy||!shiftStart||!shiftEnd" @click="registerShift">登記自己的模擬值班</button>
      <button class="secondary" @click="fetchRoster(shiftPatient)">查詢值班名單</button>
      <div v-for="s in (rosters[shiftPatient]||[])" :key="s.shift_id" class="log">
        <strong>{{s.clinician_sub}}</strong><small> {{new Date(s.starts_at*1000).toLocaleString()}} — {{new Date(s.ends_at*1000).toLocaleString()}}</small>
      </div>
      <h3>發送失敗監測</h3>
      <p v-if="jobHealth">等待 {{jobHealth.counts.PENDING||0}} / 失敗 {{jobHealth.counts.DEAD||0}}</p>
      <small>只代表 n8n Webhook 接受與否，不代表已完成醫療處理。</small>
    </aside>
    <article>
      <h2>我收到的交接邀請</h2>
      <p v-if="!inbox.length">目前沒有待接受的交接邀請。</p>
      <div v-for="h in inbox" :key="h.handoff_id" class="task">
        <strong>{{h.handoff_id}}</strong><p>{{h.patient_ref}} · {{h.task_id}} · 由 {{h.from_sub}} 提出</p>
        <p>截止：{{new Date(h.expires_at*1000).toLocaleString()}}；接手前原負責人保留責任。</p>
        <div class="task-actions"><button :disabled="busy" @click="decideHandoff(h,'accept')">接受交接</button><button :disabled="busy" class="secondary" @click="decideHandoff(h,'reject')">拒絕</button></div>
      </div>
      <h2>向下一班提出交接</h2>
      <label>已接手、待處理的任務</label>
      <select v-model="selectedHandoffTask" @change="selectHandoffTask">
        <option value="">選擇任務</option>
        <option v-for="t in tasks.filter(t=>t.assigned_to&&['ACKNOWLEDGED','OVERDUE'].includes(t.status))" :value="t.task_id" :key="t.task_id">{{t.task_id}} · {{t.patient_ref}} · {{t.assigned_to}}</option>
      </select>
      <div v-if="handoffTask" class="task-resolution">
        <p>目前負責人：{{handoffTask.assigned_to}}。只能由本人提交交接。</p>
        <label>接班人（須有有效值班）</label>
        <select v-model="handoffTarget"><option value="">選擇有效值班者</option>
          <option v-for="s in handoffRoster.filter(s=>s.starts_at<=Date.now()/1000 && s.ends_at>Date.now()/1000)" :key="s.shift_id" :value="s.clinician_sub">{{s.clinician_sub}}</option>
        </select>
        <textarea v-model="handoffReason" placeholder="交接理由（至少 12 字，勿包含真實病人資訊）" />
        <button :disabled="busy||!handoffTarget||handoffReason.length<12" @click="offerHandoff">發出交接邀請</button>
      </div>
      <p>交接請求不會自動解除原負責人的任務；接受前不得視為已完成。</p>
    </article>
  </div>

  <div v-else class="layout">
    <aside><h2>案件</h2><button v-for="c in cases" :key="c.case_id" class="case" @click="open(c)"><strong>{{c.case_id}}</strong><small>{{c.status}}</small></button></aside>
    <article v-if="selected">
      <div class="title-row"><div><h2>{{selected.case_id}}</h2><p>{{selected.patient_ref}} · {{selected.status}} · Version {{selected.version}}</p></div><span class="priority">{{selected.state.priority}}</span></div>
      <h3>七日連續監測趨勢（實際觀測值，不補缺失資料）</h3>
      <div class="trends" v-if="trend">
        <div v-for="(m,code) in trend.measurements" :key="code" class="trend">
          <strong>{{code}}</strong><span>Latest: {{m.latest}} | Δ: {{m.delta===null?'無足夠數據':m.delta}} | N: {{m.count}}</span>
          <small>Median: {{m.median}}</small>
        </div>
        <p v-if="!Object.keys(trend.measurements).length">尚未上傳獨立 Observation 資料。</p>
      </div>
      <h3>原始合成病人資料</h3><pre>{{JSON.stringify({vitals:selected.payload.vitals,symptoms:selected.payload.symptoms,meal_text:selected.payload.meal_text},null,2)}}</pre>
      <h3>Safety Flags</h3><div class="chips"><span v-for="f in selected.state.flags" :key="f">{{f}}</span><span v-if="!selected.state.flags.length">沒有規則旗標 ≠ 臨床安全</span></div>
      <h3>Agent Outputs</h3><div v-for="(a,name) in selected.state.agents" :key="name" class="agent"><strong>{{name}}</strong><p>{{a.summary}}</p><small>Confidence: {{a.confidence}} | uncertainty: {{(a.uncertainties||[]).join('; ')}}</small></div>
      <h3>可稽核的示範 RAG 來源</h3><div v-for="s of selected.state.sources" :key="s.source_id" class="source"><strong>{{s.source_id}}</strong> — {{s.title}} ({{s.version}}) <small>sha256: {{s.sha256.slice(0,12)}}</small><details><summary>來源摘錄</summary>{{s.snippet}}</details></div>
      <h3>AI Draft（未寄送）</h3><pre>{{JSON.stringify(selected.state.synthesis,null,2)}}</pre>
      <h3>Human Checkpoint</h3>
      <p>負責任務：{{reviewTask?.task_id||'尚未建立'}} · {{reviewTask?.status||'等待 Agent 完成'}}</p>
      <button v-if="reviewTask && (reviewTask.status==='OPEN'||reviewTask.status==='OVERDUE')" :disabled="busy" @click="claim(reviewTask)">先確認接手此案件</button>
      <p v-if="canDecide">請先檢查原始資料、Agent 不確定性及來源，再記錄審核。</p>
      <select v-model="choice"><option value="approve" :disabled="!canApprove">Approve（僅模擬訊息佇列）</option><option value="reject">Reject</option><option value="escalate">Escalate（另建追蹤任務）</option></select>
      <textarea v-model="comment" placeholder="寫下審核原因（至少 8 字）"></textarea>
      <button :disabled="busy||!canDecide||comment.length<8||choice==='approve'&&!canApprove" @click="decide">送出醫護決策</button>
      <h3>照護交接時間軸（2.3 開始）</h3>
      <div v-for="e in timeline" :key="e.event_id" class="log"><code>{{e.event_code}}</code> · {{e.actor}} · {{new Date(e.occurred_at*1000).toLocaleString()}}</div>
      <p v-if="!timeline.length">尚無 2.3 版交接或後續事件。</p>
      <h3>Audit Trail</h3><div v-for="a of audits" :key="a.seq" class="log"><code>{{a.seq}} · {{a.event}}</code> · {{a.actor}}</div>
    </article>
    <article v-else class="empty">請選擇案件，查看 AI 證據、長期趨勢與醫護決策。</article>
  </div>
</main>
</template>
