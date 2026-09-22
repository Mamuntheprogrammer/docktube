const $=id=>document.getElementById(id);
let videos=[],plTitle="",jobId=null,poll=null;
const fmtB=n=>{if(!n)return"0 B";const u=["B","KB","MB","GB"];let i=0;while(n>=1024&&i<3){n/=1024;i++}return n.toFixed(1)+" "+u[i]};
const fmtS=n=>!n?"—":fmtB(n)+"/s";
const fmtT=s=>{s=Math.round(s||0);if(!s)return"—";const m=Math.floor(s/60),h=Math.floor(m/60);return h?`${h}h ${m%60}m ${s%60}s`:m?`${m}m ${s%60}s`:`${s}s`};
const fmtD=s=>{s=Math.round(s||0);return Math.floor(s/60)+":"+String(s%60).padStart(2,"0")};

$("themeBtn").onclick=()=>{const h=document.documentElement;h.dataset.theme=h.dataset.theme==="dark"?"light":"dark";$("themeBtn").textContent=h.dataset.theme==="dark"?"🌙":"☀️"};
async function loadHist(){$("histCard").classList.remove("hidden");const [hr,cr]=await Promise.all([fetch("/api/history"),fetch("/api/cache/info")]);const h=await hr.json();const c=await cr.json().catch(()=>null);if(c)$("cacheInfo").textContent=`Cache: ${fmtB(c.parts_size)} temp (${c.parts_count} parts) · Jobs: ${fmtB(c.jobs_size)} · Downloads: ${fmtB(c.downloads_size)}`;$("hist").innerHTML=h.map(j=>`<div class="prow"><b>${j.title||j.id}</b> <span class="st ${j.status}">${j.status}</span><div class="mini">${j.overall?j.overall.done+"/"+j.overall.total_n+" done, "+j.overall.failed+" failed":""} · ${j.merged_file||""}</div><div class="mini"><button onclick="delJob('${j.id}')">Delete</button></div></div>`).join("")||"<span class='muted'>No history yet.</span>"}
$("historyBtn").onclick=loadHist;
window.delJob=async id=>{const del=document.getElementById("delMerged")?.checked;await fetch("/api/jobs/"+id+(del?"?delete_file=1":""),{method:"DELETE"});loadHist()};
$("clearCacheBtn").onclick=async()=>{await fetch("/api/cache/clear",{method:"POST"});loadHist()};
$("clearHistBtn").onclick=async()=>{if(!confirm("Clear all history?"))return;const del=document.getElementById("delMerged")?.checked;await fetch("/api/history/clear",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({delete_merged:!!del})});loadHist()};
$("folderBtn").onclick=()=>fetch("/api/open-folder",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
$("allBtn").onclick=()=>document.querySelectorAll(".v input").forEach(c=>c.checked=true);
$("noneBtn").onclick=()=>document.querySelectorAll(".v input").forEach(c=>c.checked=false);

let localMode=false,localFolder="";
async function doAnalyze(){
  const url=$("url").value.trim();if(!url)return;
  // Local folder? (server runs locally so it can read D:\Videos)
  if(/^[A-Za-z]:[\\/]/.test(url)||url.startsWith("/")||url.startsWith("\\\\")){
    $("analyzeMsg").textContent="Listing local files…";$("analyzeBtn").disabled=true;
    try{
      const r=await fetch("/api/local/list",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({folder:url})});
      const j=await r.json();if(j.error)throw new Error(j.error);
      videos=j.videos;plTitle=j.title;localMode=true;localFolder=j.folder;
      $("plTitle").textContent=`— 📁 ${j.title} (${j.count} files)`;
      $("vlist").innerHTML=videos.map((v,i)=>`<label class="v"><input type="checkbox" checked data-i="${i}"><span><span class="t">#${i+1} ${v.title}</span><br><span class="d">${v.ext||""} · ${fmtB(v.size||0)}</span><br><span class="d">${v.filepath||""}</span></span></label>`).join("");
      $("listCard").classList.remove("hidden");$("dlBtn").textContent="Merge local files (instant if same type)";
      $("analyzeMsg").textContent=`Found ${j.count} files in ${j.folder}. Tick order = merge order. Same codec/size = instant copy.`;
      localStorage.setItem("lastUrl",url);
    }catch(e){$("analyzeMsg").textContent="Folder error: "+e.message+" — try playlist URL instead.";localMode=false}
    $("analyzeBtn").disabled=false;return;
  }
  localMode=false;$("dlBtn").textContent="Download + Merge";
  $("analyzeMsg").textContent="Analyzing playlist… (auto-retries x3)";$("analyzeBtn").disabled=true;$("analyzeBtn").textContent="Working…";
  try{
    const r=await fetch("/api/analyze",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url})});
    const j=await r.json();
    if(j.error)throw new Error(j.error+" — press Analyze again to retry");
    videos=j.videos;plTitle=j.title;
    $("plTitle").textContent=`— ${j.title} (${j.count})`;
    $("vlist").innerHTML=videos.map((v,i)=>`<label class="v ${v.broken?"broken":""}"><input type="checkbox" ${v.broken?"":"checked"} data-i="${i}"><img loading="lazy" src="${v.thumbnail}"><span><span class="t">${v.title}${v.broken?" ⚠ private/deleted":""}</span><br><span class="d">${fmtD(v.duration)}</span></span></label>`).join("");
    $("listCard").classList.remove("hidden");
    $("analyzeMsg").textContent=`Found ${j.count} videos.${j.unavailable?` ${j.unavailable} unavailable skipped — press Analyze to retry.`:""} Press Verify ✓ before Download to save time.`;
    localStorage.setItem("lastUrl",url);
  }catch(e){$("analyzeMsg").textContent="Analyze failed: "+e.message}
  $("analyzeBtn").disabled=false;$("analyzeBtn").textContent="Analyze / List files";
}
$("analyzeBtn").onclick=doAnalyze;
$("verifyBtn").onclick=async()=>{
  const boxes=[...document.querySelectorAll(".v input")];const sel=boxes.filter(c=>c.checked).map(c=>videos[+c.dataset.i]);
  if(!sel.length){alert("Select at least one video.");return}
  $("analyzeMsg").textContent=`Verifying ${sel.length} videos before download…`;$("verifyBtn").disabled=true;
  try{
    const r=await fetch("/api/precheck",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({videos:sel,quality:$("quality").value})});
    const j=await r.json();const bad=new Set((j.results||[]).filter(x=>!x.ok).map(x=>x.id));
    let n=0;boxes.forEach(c=>{const v=videos[+c.dataset.i];if(bad.has(v.id)){c.checked=false;n++}});
    $("analyzeMsg").textContent=n?`⚠ ${n} will fail — unticked. Press Analyze to retry list, or Download the rest.`:`✓ All ${sel.length} look downloadable. Safe to Download.`;
  }catch(e){$("analyzeMsg").textContent="Verify error: "+e.message+" — press Verify again"}
  $("verifyBtn").disabled=false;
};
if(localStorage.getItem("lastUrl"))$("url").value=localStorage.getItem("lastUrl");

$("dlBtn").onclick=async()=>{
  const sel=[...document.querySelectorAll(".v input")].filter(c=>c.checked).map(c=>videos[+c.dataset.i]);
  if(!sel.length){alert("Select at least one video.");return}
  const endpoint=localMode?"/api/local/merge":"/api/jobs";
  const body=localMode?{folder:localFolder,videos:sel,format:$("format").value}:{playlist_url:$("url").value,playlist_title:plTitle,videos:sel,quality:$("quality").value,format:$("format").value,concurrency:+$("conc").value};
  const r=await fetch(endpoint,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  const j=await r.json();if(j.error){alert(j.error);return}
  jobId=j.id;$("progCard").classList.remove("hidden");$("doneMsg").textContent="";$("saveBtn").classList.add("hidden");
  clearInterval(poll);poll=setInterval(refresh,1000);refresh();
};

async function refresh(){
  if(!jobId)return;
  const r=await fetch("/api/jobs/"+jobId);const j=await r.json();
  const o=j.overall;
  $("oPct").textContent=o.pct+"%";
  $("oBar").style.width=o.pct+"%";
  $("oCounts").textContent=`· ${o.done} done · ${o.failed} failed / ${o.total_n}`;
  $("oSpeed").textContent=fmtS(o.speed);
  $("oSize").textContent=`${fmtB(o.downloaded)}${o.total?" / "+fmtB(o.total):""}`;
  $("oEta").textContent="ETA "+fmtT(o.eta)+(j.status==="merging"?" · merging…":" · "+j.status);
  $("plist").innerHTML=j.videos.map(v=>`<div class="prow"><div class="meta"><span><b>#${v.order+1}</b> ${v.title}</span><span class="st ${v.status}">${v.status} ${v.status==="downloading"?v.pct+"%":""}</span></div><div class="bar"><div style="width:${v.pct}%"></div></div><div class="mini">${fmtB(v.downloaded)}${v.total?" / "+fmtB(v.total):""} · ${fmtS(v.speed)} · ETA ${fmtT(v.eta)} ${v.error?"· ❌ "+v.error:""} ${v.status==="failed"?`<button onclick="retryOne('${v.id}')">Retry</button>`:""}</div></div>`).join("");
  if(["completed","completed_with_failures","failed","merge_failed","cancelled"].includes(j.status)){
    clearInterval(poll);
    $("doneMsg").textContent="Status: "+j.status+(j.merged_file?" · "+j.merged_file:"")+(j.error?" · "+j.error:"");
    if(j.merged_file){const s=$("saveBtn");s.classList.remove("hidden");s.href="/api/file/"+jobId;}
  }
}
window.retryOne=async vid=>{await fetch(`/api/jobs/${jobId}/retry`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({video_id:vid})});clearInterval(poll);poll=setInterval(refresh,1000)};
$("cancelBtn").onclick=async()=>{await fetch(`/api/jobs/${jobId}/cancel`,{method:"POST"});refresh()};
$("retryBtn").onclick=async()=>{await fetch(`/api/jobs/${jobId}/retry`,{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});clearInterval(poll);poll=setInterval(refresh,1000)};
$("mergeBtn").onclick=async()=>{await fetch(`/api/jobs/${jobId}/merge`,{method:"POST"});refresh()};
