<script setup>
import {ref, computed} from 'vue'
const communications=ref([])
const token=ref(''),data=ref(null),error=ref(''),success=ref(''),loading=ref(false),days=ref(7)
const weight=ref(''),glucose=ref(''),note=ref(''),deviceProblem=ref(false)
const symptoms=ref({swelling:false,chest_pain:false,severe_breathlessness:false,fainting:false,confusion:false})
const code=ref('weight_kg'),value=ref('')
const unit=computed(()=>({weight_kg:'kg',glucose_mg_dl:'mg/dL',heart_rate_bpm:'beats/min',spo2_pct:'%'})[code.value])
const privacyReminder='合成教學資料限定。沒有連接醫院，也不會向醫護發出真實通知。遇到緊急症狀不可依賴本頁面求救。'
async function request(path,options={}){
  if(!token.value)throw Error('請先輸入有效的 Demo patient JWT')
  const result=await fetch(path,{...options,headers:{Authorization:'Bearer '+token.value,'Content-Type':'application/json',...(options.headers||{})}})
  if(!result.ok)throw Error(`${result.status}: ${await result.text()}`)
  return result.json()
}
async function refresh(){loading.value=true;error.value='';try{data.value=await request('/v4/patient/dashboard?days='+days.value); communications.value=(await request('/v5/patient/communications')).messages}catch(e){error.value=e.message}finally{loading.value=false}}
function eid(prefix){return prefix+'-'+crypto.randomUUID().replaceAll('-','').slice(0,18)}
async function submitObservation(){loading.value=true;error.value='';success.value='';try{
  if(!data.value)throw Error('請先載入患者頁面')
  await request('/v2/observations',{method:'POST',body:JSON.stringify({event_id:eid('OBS'),patient_ref:data.value.patient_ref,is_synthetic:true,code:code.value,value:Number(value.value),unit:unit.value,taken_at:new Date().toISOString()})})
  success.value='合成量測已記錄（不代表臨床監測）';value.value='';await refresh()
}catch(e){error.value=e.message}finally{loading.value=false}}
async function submitCheckin(){loading.value=true;error.value='';success.value='';try{
  if(!data.value)throw Error('請先載入患者頁面')
  await request('/v2/checkins',{method:'POST',body:JSON.stringify({event_id:eid('CHK'),patient_ref:data.value.patient_ref,is_synthetic:true,symptoms:{...symptoms.value,notes:''},device_problem:deviceProblem.value,patient_note:note.value})})
  success.value='合成 Check-in 已記錄；不會觸發真實救援';note.value='';deviceProblem.value=false
  symptoms.value={swelling:false,chest_pain:false,severe_breathlessness:false,fainting:false,confusion:false};await refresh()
}catch(e){error.value=e.message}finally{loading.value=false}}
async function savePreference(){loading.value=true;error.value='';try{
  const p=data.value.reminder_preferences
  await request('/v4/patient/preferences',{method:'PUT',body:JSON.stringify({reminder_opt_in:p.reminder_opt_in,reminder_hour_utc:Number(p.reminder_hour_utc),minimum_gap_hours:Number(p.minimum_gap_hours)})})
  await refresh();success.value='偏好已儲存：提醒只會顯示於本頁，沒有實際發送'
}catch(e){error.value=e.message}finally{loading.value=false}}
async function markSeen(p){loading.value=true;error.value='';try{await request('/v4/patient/prompts/'+encodeURIComponent(p.prompt_id)+'/seen',{method:'POST'});await refresh()}catch(e){error.value=e.message}finally{loading.value=false}}
async function acknowledgeMessage(msg){loading.value=true;error.value='';try{await request('/v5/patient/communications/'+encodeURIComponent(msg.message_id)+'/acknowledge',{method:'POST'});await refresh()}catch(e){error.value=e.message}finally{loading.value=false}}
function fmt(v){return new Date(v*1000).toLocaleString()}
</script>
<template>
<main>
  <header><div><p class="eyebrow">H@H AUTOMATION · PATIENT EXPERIENCE PORTFOLIO</p><h1>Patient Portal — Synthetic Demo</h1>
    <p>自主追蹤觀測、回覆 Check-in、控制提醒偏好。</p></div>
    <span class="warning">SYNTHETIC ONLY · NOT FOR CLINICAL USE</span></header>
  <p class="error">{{privacyReminder}}</p>
  <section class="login"><label>Patient Bearer Token（只保存在此分頁記憶體）</label>
    <input type="password" v-model="token" placeholder="Demo patient JWT" autocomplete="off"/>
    <label>歷史天數</label><select v-model.number="days"><option :value="7">7 日</option><option :value="14">14 日</option><option :value="30">30 日</option></select>
    <button :disabled="loading" @click="refresh">讀取我的合成資料</button></section>
  <p v-if="error" role="alert" class="error">{{error}}</p><p v-if="success" class="success">{{success}}</p>
  <div v-if="data" class="patient-columns">
    <section class="panel"><h2>我的監測摘要 · {{data.patient_ref}}</h2>
      <p>監測計畫：{{data.monitoring_plan?.observation_code || '尚未設定'}} ／ {{data.monitoring_plan?.review_gap_hours || '—'}} 小時</p>
      <div v-for="(m,code) in data.observations" :key="code" class="trend"><strong>{{code}}</strong><span>最新 {{m.latest}} · Δ {{m.delta??'資料不足'}} · {{m.count}} 筆</span></div>
      <p v-if="!Object.keys(data.observations).length">目前沒有量測紀錄。</p>
      <h3>新增合成量測</h3>
      <select v-model="code"><option value="weight_kg">體重</option><option value="glucose_mg_dl">血糖</option><option value="heart_rate_bpm">心率</option><option value="spo2_pct">SpO₂</option></select>
      <input type="number" step="any" v-model="value" :placeholder="unit" />
      <button :disabled="loading||value===''" @click="submitObservation">新增量測</button>
    </section>
    <section class="panel"><h2>症狀 Check-in</h2>
      <div v-for="(enabled,s) in symptoms" :key="s" class="tick"><label><input type="checkbox" v-model="symptoms[s]"/> {{s}}</label></div>
      <label><input type="checkbox" v-model="deviceProblem"/> 裝置有問題</label>
      <textarea v-model="note" maxlength="500" placeholder="合成情境說明（不要輸入真實病人資料）"/>
      <button :disabled="loading" @click="submitCheckin">提交合成 Check-in</button>
      <h3>最近 Check-in</h3><p v-for="c in data.checkins" :key="c.event_id" class="log">{{c.event_id}} · {{c.status}} · {{fmt(c.created_at)}}</p>
      <p v-if="!data.checkins.length">目前沒有記錄。</p>
    </section>
    <section class="panel"><h2>照護訊息追蹤（站內模擬）</h2>
      <p>只顯示具權限醫護人員核准的固定模板；已查看不代表醫療處置完成。</p>
      <div v-for="m in communications" :key="m.message_id" class="task">
        <strong>{{m.template_code}} · {{m.state}}</strong><p>{{m.content}}</p>
        <small>發佈：{{m.published_at?fmt(m.published_at):'尚未發佈'}}</small>
        <button v-if="m.state==='PUBLISHED_IN_APP'" :disabled="loading" @click="acknowledgeMessage(m)">確認已閱讀</button>
      </div><p v-if="!communications.length">目前沒有已發佈的示範訊息。</p>
    </section>
    <section class="panel"><h2>每日提醒偏好</h2><p>預設關閉。只有同意參與且監測計畫啟用時，才會在系統內建立示範提醒，沒有 SMS 或推播。</p>
      <label><input type="checkbox" v-model="data.reminder_preferences.reminder_opt_in" /> 同意站內模擬提醒</label>
      <label>UTC 時間（0–23）<input type="number" min="0" max="23" v-model.number="data.reminder_preferences.reminder_hour_utc" /></label>
      <label>至少間隔小時（24–168）<input type="number" min="24" max="168" v-model.number="data.reminder_preferences.minimum_gap_hours" /></label>
      <button :disabled="loading" @click="savePreference">儲存偏好</button>
      <h3>站內模擬提醒</h3>
      <div v-for="p in data.in_app_prompts" :key="p.prompt_id" class="task"><strong>{{p.kind}} · {{p.state}}</strong>
        <p>{{fmt(p.created_at)}}</p><button v-if="p.state==='PENDING_SIMULATED'" :disabled="loading" @click="markSeen(p)">標記已查看</button></div>
      <p v-if="!data.in_app_prompts.length">目前無站內提醒。</p>
    </section>
  </div>
</main>
</template>
