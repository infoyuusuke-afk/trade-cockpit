(()=>{
  "use strict";
  const BRIDGE="http://127.0.0.1:28583";
  let voiceOn=false;
  let voiceOnline=false;
  let queue=[];
  let playing=false;
  let lastKey="";
  let lastAt=0;
  window.cockpitLiveSpeechEnabled=true;

  const sessionLabel=()=>{
    const p=Object.fromEntries(new Intl.DateTimeFormat("en-US",{
      timeZone:"Asia/Tokyo",weekday:"short",hour:"2-digit",minute:"2-digit",hourCycle:"h23"
    }).formatToParts(new Date()).filter(x=>x.type!=="literal").map(x=>[x.type,x.value]));
    if(["Sat","Sun"].includes(p.weekday)) return "時間外";
    const m=Number(p.hour)*60+Number(p.minute);
    if((m>=540&&m<=690)||(m>=750&&m<=930)) return "東証";
    if(m>=990&&m<1439) return "PTS";
    return "時間外";
  };

  function ensureStatusEl(){
    const host=document.querySelector(".unified-mode-controls");
    if(!host)return null;
    let el=document.getElementById("voice-backend-status");
    if(!el){
      el=document.createElement("span");
      el.id="voice-backend-status";
      el.className="voice-backend-status";
      host.appendChild(el);
    }
    return el;
  }

  function updateUi(){
    const session=sessionLabel();
    document.querySelectorAll("#unified-mode-market-status").forEach(el=>{
      const open=session!=="時間外";
      el.classList.toggle("open",open);
      const b=el.querySelector("b");if(b)b.textContent=session;
    });
    document.querySelectorAll("[data-voice-toggle]").forEach(button=>{
      button.textContent=voiceOn?"音声 ON":"音声 OFF";
      button.classList.toggle("voice-on",voiceOn);
      button.disabled=!voiceOnline;
      button.title=!voiceOnline
        ?"VOICE OFFLINE：Style-Bert-VITS2に接続できません"
        :(voiceOn?"全音声ON（東証・夜間PTS共通。クリックでOFF）":"全音声OFF（クリックでON）");
    });
    const s=ensureStatusEl();
    if(s){
      s.textContent=!voiceOnline?"VOICE OFFLINE":(voiceOn?"VOICE SBV2 ON":"VOICE SBV2 OFF");
      s.classList.toggle("online",voiceOnline&&voiceOn);
      s.classList.toggle("offline",!voiceOnline);
    }
  }

  async function refreshHealth(){
    try{
      const r=await fetch(BRIDGE+"/health?t="+Date.now(),{cache:"no-store"});
      const j=await r.json();
      voiceOnline=!!(r.ok&&j&&j.sbv2_ready===true);
      if(r.ok&&j&&typeof j.enabled==="boolean")voiceOn=j.enabled;
    }catch(_e){voiceOnline=false;}
    updateUi();
    return voiceOnline;
  }

  async function setBridgeEnabled(next){
    const r=await fetch(BRIDGE+"/control?enabled="+(next?"1":"0")+"&t="+Date.now(),{cache:"no-store"});
    const j=await r.json();
    if(!r.ok||!j||typeof j.enabled!=="boolean")throw new Error("voice control failed");
    voiceOn=j.enabled;
    localStorage.setItem("cockpitVoiceV1",voiceOn?"on":"off");
    updateUi();
    return voiceOn;
  }

  function enqueue(text,level="CALM",force=false){
    const clean=String(text||"").trim();
    if(!clean)return;
    const now=Date.now(),key=level+"|"+clean;
    if(key===lastKey&&now-lastAt<10000)return;
    lastKey=key;lastAt=now;
    if(queue.length>=6)queue=queue.slice(-5);
    queue.push({text:clean,level,force:!!force});
    pump();
  }

  async function pump(){
    if(playing||!queue.length)return;
    playing=true;
    try{
      while(queue.length){
        if(!voiceOn){queue=[];break;}
        const item=queue.shift();
        if(!item.force&&window.cockpitLiveSpeechEnabled===false)continue;
        if(!voiceOnline&&!(await refreshHealth())){queue=[];break;}
        try{
          const u=BRIDGE+"/announce?level="+encodeURIComponent(item.level)+"&text="+encodeURIComponent(item.text)+"&t="+Date.now();
          const r=await fetch(u,{cache:"no-store"});
          const j=await r.json();
          if(!r.ok||!j||j.ok!==true)throw new Error("voice bridge rejected request");
          if(j.skipped&&j.reason==="VOICE_OFF"){
            voiceOn=false;
            updateUi();
            queue=[];
            break;
          }
        }catch(_e){
          voiceOnline=false;
          updateUi();
          queue=[];
          break;
        }
      }
    }finally{playing=false;}
  }

  window.cockpitSpeak=(msg,level="CALM")=>{
    if(!voiceOn||!msg||window.cockpitLiveSpeechEnabled===false)return;
    enqueue(msg,level,false);
  };
  window.cockpitVoiceSetLiveEnabled=v=>{
    window.cockpitLiveSpeechEnabled=v===true;
    updateUi();
  };
  window.cockpitAnnounce=model=>{
    if(!model||!model.symbol||!window.recordOnAir)return;
    window.recordOnAir(model);
    const box=document.getElementById("cockpit-onair-cards");
    if(box&&window.renderOnAirPanel)box.innerHTML=window.renderOnAirPanel();
  };

  document.addEventListener("click",async e=>{
    const button=e.target.closest?.("[data-voice-toggle]");
    if(!button)return;
    e.preventDefault();
    if(!voiceOnline&&!(await refreshHealth()))return;
    button.disabled=true;
    try{
      const nowOn=await setBridgeEnabled(!voiceOn);
      if(nowOn)enqueue("AIコクピットの自動読み上げを開始します","CALM",true);
      else queue=[];
    }catch(_e){
      voiceOnline=false;
      updateUi();
    }finally{
      button.disabled=!voiceOnline;
    }
  });

  document.addEventListener("DOMContentLoaded",()=>{
    refreshHealth();
    setInterval(refreshHealth,15000);
    setInterval(updateUi,30000);
  });
})();