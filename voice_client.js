(()=>{
  "use strict";
  const BRIDGE="http://127.0.0.1:28583";
  let voiceOn=localStorage.getItem("cockpitVoiceV1")==="on";
  let voiceOnline=false;
  let queue=[];
  let playing=false;
  let lastKey="";
  let lastAt=0;
  window.cockpitLiveSpeechEnabled=true;

  const jstClock=()=>{
    const p=Object.fromEntries(new Intl.DateTimeFormat("en-US",{
      timeZone:"Asia/Tokyo",weekday:"short",hour:"2-digit",minute:"2-digit",hourCycle:"h23"
    }).formatToParts(new Date()).filter(x=>x.type!=="literal").map(x=>[x.type,x.value]));
    return {weekday:p.weekday,minutes:Number(p.hour)*60+Number(p.minute)};
  };
  const isTseVoiceWindow=()=>{
    const t=jstClock(),weekday=!["Sat","Sun"].includes(t.weekday);
    return weekday&&((t.minutes>=540&&t.minutes<=690)||(t.minutes>=750&&t.minutes<=930));
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
    const open=isTseVoiceWindow();
    document.querySelectorAll("#unified-mode-market-status").forEach(el=>{
      el.classList.toggle("open",open);
      const b=el.querySelector("b");if(b)b.textContent=open?"取引時間中":"取引時間外";
    });
    document.querySelectorAll("[data-voice-toggle]").forEach(button=>{
      button.textContent=!open?"🔇":(!voiceOnline?"⚠":(voiceOn?"🔊":"🔇"));
      button.title=!open
        ?"東証9:00～11:30・12:30～15:30のみ"
        :(!voiceOnline?"VOICE OFFLINE：Style-Bert-VITS2に接続できません"
        :(voiceOn?"SBV2音声ON（クリックでOFF）":"SBV2音声OFF（クリックでON）"));
    });
    const s=ensureStatusEl();
    if(s){
      s.textContent=voiceOnline?"VOICE SBV2":"VOICE OFFLINE";
      s.classList.toggle("online",voiceOnline);
      s.classList.toggle("offline",!voiceOnline);
    }
  }

  async function refreshHealth(){
    try{
      const r=await fetch(BRIDGE+"/health?t="+Date.now(),{cache:"no-store"});
      const j=await r.json();
      voiceOnline=!!(r.ok&&j&&j.sbv2_ready===true);
    }catch(_e){voiceOnline=false;}
    updateUi();
    return voiceOnline;
  }

  function enqueue(text,level){
    const clean=String(text||"").trim();
    if(!clean)return;
    const now=Date.now(),key=level+"|"+clean;
    if(key===lastKey&&now-lastAt<10000)return;
    lastKey=key;lastAt=now;
    if(queue.length>=6)queue=queue.slice(-5);
    queue.push({text:clean,level:level||"CALM"});
    pump();
  }

  async function pump(){
    if(playing||!queue.length)return;
    playing=true;
    try{
      while(queue.length){
        if(!voiceOn||!isTseVoiceWindow()||window.cockpitLiveSpeechEnabled===false) {queue=[];break;}
        if(!voiceOnline&&!(await refreshHealth())){queue=[];break;}
        const item=queue.shift();
        try{
          const u=BRIDGE+"/speak?level="+encodeURIComponent(item.level)+"&text="+encodeURIComponent(item.text)+"&t="+Date.now();
          const r=await fetch(u,{cache:"no-store"});
          if(!r.ok)throw new Error("voice bridge "+r.status);
          const blob=await r.blob();
          const url=URL.createObjectURL(blob);
          try{
            const audio=new Audio(url);
            await new Promise((resolve,reject)=>{
              audio.onended=resolve;audio.onerror=reject;
              const p=audio.play();if(p&&p.catch)p.catch(reject);
            });
          }finally{URL.revokeObjectURL(url);}
        }catch(_e){
          voiceOnline=false;updateUi();queue=[];break;
        }
      }
    }finally{playing=false;}
  }

  window.cockpitSpeak=(msg,level="CALM")=>{
    if(!voiceOn||!msg||!isTseVoiceWindow()||window.cockpitLiveSpeechEnabled===false)return;
    enqueue(msg,level);
  };
  window.cockpitVoiceSetLiveEnabled=v=>{window.cockpitLiveSpeechEnabled=v===true;updateUi();};
  window.cockpitAnnounce=model=>{
    if(!model||!model.symbol||!window.recordOnAir)return;
    window.recordOnAir(model);
    const box=document.getElementById("cockpit-onair-cards");
    if(box&&window.renderOnAirPanel)box.innerHTML=window.renderOnAirPanel();
  };

  document.addEventListener("DOMContentLoaded",()=>{
    document.querySelectorAll("[data-voice-toggle]").forEach(button=>{
      button.onclick=async()=>{
        if(!isTseVoiceWindow()){
          voiceOn=false;localStorage.setItem("cockpitVoiceV1","off");updateUi();return;
        }
        if(!voiceOn){
          const ok=await refreshHealth();
          if(!ok){voiceOn=false;localStorage.setItem("cockpitVoiceV1","off");updateUi();return;}
        }
        voiceOn=!voiceOn;
        localStorage.setItem("cockpitVoiceV1",voiceOn?"on":"off");
        updateUi();
        if(voiceOn)enqueue("AIコクピットの自動読み上げを開始します","CALM");
        else queue=[];
      };
    });
    refreshHealth();
    setInterval(refreshHealth,15000);
    setInterval(updateUi,30000);
  });
})();