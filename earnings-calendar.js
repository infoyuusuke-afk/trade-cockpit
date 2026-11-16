(() => {
 const boot = () => {
  if (document.getElementById('earnings-calendar-panel')) return;
  const root = document.createElement('section');
  root.id = 'earnings-calendar-panel'; root.className = 'card wide';
  root.innerHTML = `<style>
  #earnings-calendar-panel .ec-controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:16px 0}
  #earnings-calendar-panel .ec-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:5px;margin:16px 0}
  #earnings-calendar-panel .ec-day{min-height:58px;border:1px solid #53677d;border-radius:7px;padding:7px;background:transparent;color:inherit;cursor:pointer;text-align:left}
  #earnings-calendar-panel .ec-day.active{border:2px solid #58d9b4;background:#163a36}
  #earnings-calendar-panel .ec-day small{display:block;color:#58d9b4}
  #earnings-calendar-panel .ec-item{padding:12px 0;border-bottom:1px solid #53677d}
  #earnings-calendar-panel .ec-item a{color:#58d9b4;margin-right:12px}
  #earnings-calendar-panel .ec-note{font-size:13px;line-height:1.6;opacity:.85}
  #earnings-calendar-panel .ec-error{color:#ffba77}
  #earnings-calendar-panel .ec-plan{margin:14px 0 6px;padding:12px 14px;border:1px solid #303033;border-radius:10px}
  #earnings-calendar-panel .ec-plan h3{margin:0 0 4px}
  #earnings-calendar-panel .ec-plan .ec-badge{display:inline-block;margin-left:8px;padding:1px 8px;border:1px solid #6b5a1e;border-radius:9px;color:#f5c542;font-size:12px}
  #earnings-calendar-panel .ec-scroll{overflow-x:auto}
  #earnings-calendar-panel .ec-plan table{width:100%;border-collapse:collapse;margin:6px 0 10px;font-size:13px}
  #earnings-calendar-panel .ec-plan th,#earnings-calendar-panel .ec-plan td{padding:5px 8px;border-bottom:1px solid #22252a;text-align:right;white-space:nowrap}
  #earnings-calendar-panel .ec-plan th:first-child,#earnings-calendar-panel .ec-plan td:first-child,#earnings-calendar-panel .ec-plan td.ec-name{text-align:left}
  #earnings-calendar-panel .ec-plan th{color:#b5b5ba;font-weight:400}
  </style><h2>決算カレンダー・カタリスト</h2>
  <div class="ec-note" id="ec-status">公式予定と企業開示を確認中…</div>
  <div class="ec-plan" id="ec-plan"><h3>決算前2週間の候補<span class="ec-badge">検証中</span></h3><div class="ec-note">16:00の記録を読込中…</div></div>
  <div class="ec-controls"><label>表示月 <input id="ec-month" type="month"></label><label><input id="ec-watched" type="checkbox" checked> 監視銘柄のみ</label><label><input id="ec-past" type="checkbox"> 過ぎた日も出す</label><a href="https://s.kabutan.jp/warnings/news_schedule/" target="_blank" rel="noopener">株探で予定を確認 ↗</a></div>
  <div id="ec-grid" class="ec-grid"></div><h3 id="ec-date-title">決算予定</h3><div id="ec-events"></div>
  <h3>直近の発表済み材料</h3><div id="ec-catalysts"></div>
  <p class="ec-note">上方修正・増配の表題が確認できた開示を表示します。「業績予想の修正」だけでは方向を決めません。好材料でも市場予想未達・織り込み済みで下落する場合があります。</p>`;
  const main=document.querySelector('main')||document.body;
  const nav=document.querySelector('.cockpit-tabs');
  if(nav){
    const pane=document.createElement('div');pane.className='tab-pane';pane.dataset.pane='earnings';pane.append(root);
    [...main.querySelectorAll('section')].filter(s=>(s.querySelector('h2')?.textContent||'').includes('決算勝負候補')).forEach(s=>pane.append(s));
    main.append(pane);
    const button=document.createElement('button');button.className='cockpit-tab';button.dataset.tab='earnings';button.textContent='決算日程';button.type='button';nav.insertBefore(button,nav.querySelector('.cockpit-tab[data-tab="events"]')||nav.querySelector('.secondary-tabs'));
    button.onclick=()=>{document.querySelectorAll('.cockpit-tab').forEach(x=>x.classList.toggle('active',x===button));document.querySelectorAll('.tab-pane').forEach(x=>x.classList.toggle('active',x===pane));localStorage.setItem('cockpitTabV5','earnings');};
    if(new URLSearchParams(location.search).get('earnings')==='1'||localStorage.getItem('cockpitTabV5')==='earnings')button.click();
  }else main.append(root);
  const find = id => root.querySelector('#'+id);
  function text(parent, tag, value, cls) { const el=document.createElement(tag); el.textContent=value; if(cls)el.className=cls; parent.append(el);return el; }
  function link(parent, value, url) { try { const u=new URL(url);if(u.protocol!=='https:')return;const a=text(parent,'a',value);a.href=u.href;a.target='_blank';a.rel='noopener'; }catch{} }
  let selected=null;
  const month=find('ec-month');month.value=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit'}).format(new Date());
  // OWNER 2026-11-16 「決算日程タブをA＋B＋C＋Dで1つの版にして。表示と仮想の記録だけで、売買の合図・声・注文カードは付けない」:
  // A the coming earnings of the 監視100＋日経225 with the last 2 weeks and the 検証中 mark, and the virtual record of that shape;
  // B a past date says 発表済み with the reaction-day gap and the move from that open (the PC's 16:00 record, /earnings_gap.json);
  // C the momentum lane (34.8% over 3 outcomes, no better than chance) is no longer shown; D 監視銘柄のみ and today onward by default.
  const pct=v=>v===null||v===undefined||!Number.isFinite(Number(v))?'—':(Number(v)>0?'+':'')+Number(v).toFixed(2)+'%';
  const todayJ=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
  let gap=null;
  const gapLoad=fetch('/earnings_gap.json?t='+Date.now(),{cache:'no-store'}).then(r=>r.ok?r.json():null).catch(()=>null).then(j=>{
    gap=j&&j.real_submit_allowed===false&&j.trade_instruction===false?j:null;renderPlan();return gap;});
  function cell(tr,v,cls){const td=text(tr,'td',v);if(cls)td.className=cls;return td;}
  function renderPlan(){
    const box=find('ec-plan');box.replaceChildren();
    const plan=gap&&gap.plan,ok=plan&&plan.stats;
    const h=text(box,'h3','決算前2週間の候補');text(h,'span',ok&&plan.status==='合格'?'合格':'検証中','ec-badge');
    if(!gap){text(box,'div','16:00の記録を読めません（0件とは扱いません）。','ec-note');return;}
    text(box,'div','形：'+(plan&&plan.rule||'—')+'。2017〜2026年の日足で合格ラインの4条件を通った形を、今の決算で仮想に記録して確かめています。売買の合図ではありません。声と注文カードはありません。','ec-note');
    const s=ok?plan.stats:{};
    text(box,'div',s.n?('仮想の記録（5日目まで終わった分）：'+s.n+'件・平均 '+pct(s.mean_net_pct)+'・勝率 '+(s.win_pct??'—')+'%・PF '+(s.pf??'—')+'・前半 '+pct(s.first&&s.first.mean_net_pct)+'・後半 '+pct(s.second&&s.second.mean_net_pct)+'・でたらめに選んだ場合 '+pct(s.random_mean_net_pct)+'（勝った割合 '+(s.random_beat_pct??'—')+'%）'):'仮想の記録：5日目まで終わった銘柄はまだありません。','ec-note');
    const up=Array.isArray(gap.upcoming)?gap.upcoming:null;
    if(!up){text(box,'div','これからの決算を読めません。','ec-note');}
    else if(!up.length){text(box,'div','今日から14日の間に、監視100＋日経225の決算はありません。','ec-note');}
    else{const wrap=text(box,'div','','ec-scroll'),t=text(wrap,'table',''),hr=text(text(t,'thead',''),'tr','');
      ['決算日','銘柄','2週間の値動き','出来高の倍率','印'].forEach(x=>text(hr,'th',x));const tb=text(t,'tbody','');
      up.slice(0,60).forEach(r=>{const tr=text(tb,'tr','');cell(tr,String(r.date||'').slice(5).replace('-','/'));cell(tr,(r.name||'')+'('+(r.code||'')+')','ec-name');
        cell(tr,pct(r.r10_pct));cell(tr,r.v_ratio==null?'—':Number(r.v_ratio).toFixed(2)+'倍');cell(tr,r.candidate===true?'検証中の候補':'');});
      text(box,'div','2週間の値動きと出来高の倍率は、'+String(up[0]&&up[0].as_of||'').slice(5).replace('-','/')+'の引けの時点です（決算の前日の引けで決まります）。','ec-note');}
    const live=Array.isArray(plan&&plan.rows)?plan.rows:[];
    if(live.length){text(box,'div','記録中の候補（寄りから・費用0.1%引き）：'+live.map(r=>(r.name||'')+'('+(r.code||'')+') '+(r.day_n??'—')+'日目 '+pct(r.net_pct)).join('　'),'ec-note');}
  }
  fetch('earnings_calendar.json?t='+Date.now()).then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json();}).then(data=>{
    const age=(Date.now()-Date.parse(data.updated_at))/3600000;
    find('ec-status').textContent=`更新 ${data.updated_at.replace('T',' ')} ／ ${data.coverage_note}`;
    if(age>26 || data.errors.length){text(find('ec-status'),'div',(age>26?'更新から26時間超・鮮度注意。 ':'')+(data.errors.length?'一部の取得に失敗。確認できた範囲のみ表示。':''),'ec-error');}
    function render(){
      const watched=find('ec-watched').checked;
      const events=data.calendar.filter(x=>(!watched||x.watched)&&x.date.startsWith(month.value));
      const grid=find('ec-grid');grid.replaceChildren();
      ['月','火','水','木','金','土','日'].forEach(x=>text(grid,'small',x));
      const [year,mon]=month.value.split('-').map(Number);if(!year||!mon)return;
      const first=(new Date(year,mon-1,1).getDay()+6)%7;for(let i=0;i<first;i++)text(grid,'span','');
      for(let d=1;d<=new Date(year,mon,0).getDate();d++){
        const day=`${month.value}-${String(d).padStart(2,'0')}`;
        const count=events.filter(x=>x.date===day).length;
        const b=text(grid,'button',String(d),'ec-day'+(selected===day?' active':''));b.type='button';b.setAttribute('aria-label',`${day} 決算予定${count}件`);
        if(count)text(b,'small',count+'社');b.onclick=()=>{selected=selected===day?null:day;render();};
      }
      const list=find('ec-events');list.replaceChildren();find('ec-date-title').textContent=(selected||month.value)+' の決算予定';
      const showPast=find('ec-past').checked;
      const shown=events.filter(x=>selected?x.date===selected:(showPast||x.date>=todayJ));
      if(!shown.length)text(list,'p',data.calendar_status==='error'?'JPX予定を取得できませんでした。株探・会社IRで確認してください。':'取得したJPX掲載範囲に予定がありません。全市場の決算なしを意味しません。','ec-note');
      shown.slice(0,100).forEach(x=>{const item=text(list,'div','','ec-item');text(item,'strong',`${x.date}　${x.name}（${x.code}）${x.watched?' ★監視':''}`);
        if(x.date<todayJ){const p=gap&&gap.past?gap.past[x.code+'|'+x.date]:null;
          text(item,'div',p?`発表済み・翌日の寄り ${pct(p.gap_pct)}・寄りから ${pct(p.move_pct)}（${p.day_n}日目まで）`:'発表日を過ぎています（寄りと5日の記録は監視100＋日経225だけ）');}
        else{const u=gap&&Array.isArray(gap.upcoming)?gap.upcoming.find(r=>r.code===x.code&&r.date===x.date):null;
          text(item,'div',x.analysis.label==='未発表・期待判断の根拠不足'?'未発表':x.analysis.label);
          if(u)text(item,'div',`決算前2週間：値動き ${pct(u.r10_pct)}・出来高 ${u.v_ratio==null?'—':Number(u.v_ratio).toFixed(2)+'倍'}${u.candidate===true?'・検証中の候補':''}`,'ec-note');}
        link(item,'JPX原資料',x.source_url);const details=text(item,'details','');text(details,'summary','上方修正・決算材料の確認ポイント');x.analysis.checks.forEach(c=>text(details,'div','・'+c));x.analysis.evidence_urls.forEach(u=>link(details,'関連開示',u));});
      if(shown.length>100)text(list,'p','先頭100社を表示。日付を選択すると絞り込めます。');
      const catalysts=find('ec-catalysts');catalysts.replaceChildren();
      const items=data.catalysts.filter(x=>!watched||x.watched);
      if(!items.length)text(catalysts,'p','取得範囲内に対象開示なし。取得状況・対象期間も確認してください。','ec-note');
      items.slice(0,40).forEach(x=>{const item=text(catalysts,'div','','ec-item');text(item,'strong',`${x.published_at.slice(0,16).replace('T',' ')}　${x.name}（${x.code}）`);text(item,'div',x.tags.join(' ／ '));link(item,x.title,x.source_url);text(item,'div',x.basis,'ec-note');});
      text(catalysts,'p',data.analysis_note,'ec-note');
    }
    month.onchange=()=>{selected=null;render();};find('ec-watched').onchange=render;find('ec-past').onchange=render;render();gapLoad.then(()=>render());
  }).catch(e=>{find('ec-status').textContent='決算データ取得待ち／取得失敗：'+e.message;find('ec-status').classList.add('ec-error');});
 };
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
