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
      button.onclick=async()=>{
        if(!voiceOnline&&!(await refreshHealth())){updateUi();return;}
        const next=!voiceOn;
        try{
          const r=await fetch(BRIDGE+"/control?enabled="+(next?"1":"0")+"&t="+Date.now(),{cache:"no-store"});
          const j=await r.json();
          if(!r.ok||!j||typeof j.enabled!=="boolean")throw new Error("control failed");
          voiceOn=j.enabled;
          localStorage.setItem("cockpitVoiceV1",voiceOn?"on":"off");
          updateUi();
          if(voiceOn)enqueue("AIコクピットの自動読み上げを開始します","CALM",true);
          else queue=[];
        }catch(_e){
          voiceOnline=false;updateUi();
        }
      };
    });
    refreshHealth();
    setInterval(refreshHealth,15000);
    setInterval(updateUi,30000);
  });
})();