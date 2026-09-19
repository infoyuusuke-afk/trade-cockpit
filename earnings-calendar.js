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
  </style><h2>決算カレンダー・カタリスト</h2>
  <div class="ec-note" id="ec-status">公式予定と企業開示を確認中…</div>
  <div class="ec-controls"><label>表示月 <input id="ec-month" type="month"></label><label><input id="ec-watched" type="checkbox"> 監視銘柄のみ</label><a href="https://s.kabutan.jp/warnings/news_schedule/" target="_blank" rel="noopener">株探で予定を確認 ↗</a></div>
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
  fetch('earnings_calendar.json?t='+Date.now()).then(r=>{if(!r.ok)throw Error('HTTP '+r.status);return r.json();}).then(data=>{
    const age=(Date.now()-Date.parse(data.updated_at))/3600000;
    find('ec-status').textContent=`更新 ${data.updated_at.replace('T',' ')} ／ ${data.coverage_note}`;
    if(age>26 || data.errors.length){text(find('ec-status'),'div',(age>26?'更新から26時間超・鮮度注意。 ':'')+(data.errors.length?'一部の取得に失敗。確認できた範囲のみ表示。':''),'ec-error');}
    if(data.momentum_target_date){
      const v=data.momentum_validation||{};
      text(find('ec-status'),'div',`モメンタムレーン対象日 ${data.momentum_target_date}（${v.status||'未確認'}／resolved_n=${v.resolved_n??0}${v.hit_rate_pct!=null?'／的中率'+v.hit_rate_pct+'%（参考）':''}）`,'ec-note');
    }
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
      const shown=events.filter(x=>!selected||x.date===selected);
      if(!shown.length)text(list,'p',data.calendar_status==='error'?'JPX予定を取得できませんでした。株探・会社IRで確認してください。':'取得したJPX掲載範囲に予定がありません。全市場の決算なしを意味しません。','ec-note');
      shown.slice(0,100).forEach(x=>{const item=text(list,'div','','ec-item');text(item,'strong',`${x.date}　${x.name}（${x.code}）${x.watched?' ★監視':''}`);text(item,'div',x.analysis.label);text(item,'div',x.analysis.note,'ec-note');if(x.momentum){const m=x.momentum;text(item,'div',m.available?`モメンタムレーン: ${m.momentum_direction}（直近5日${m.return_5d_pct==null?'—':(m.return_5d_pct>=0?'+':'')+m.return_5d_pct+'%'}）`:`モメンタムレーン: 取得不可（${m.reason||'—'}）`,'ec-note');}link(item,'JPX原資料',x.source_url);const details=text(item,'details','');text(details,'summary','上方修正・決算材料の確認ポイント');x.analysis.checks.forEach(c=>text(details,'div','・'+c));x.analysis.evidence_urls.forEach(u=>link(details,'関連開示',u));});
      if(shown.length>100)text(list,'p','先頭100社を表示。日付を選択すると絞り込めます。');
      const catalysts=find('ec-catalysts');catalysts.replaceChildren();
      const items=data.catalysts.filter(x=>!watched||x.watched);
      if(!items.length)text(catalysts,'p','取得範囲内に対象開示なし。取得状況・対象期間も確認してください。','ec-note');
      items.slice(0,40).forEach(x=>{const item=text(catalysts,'div','','ec-item');text(item,'strong',`${x.published_at.slice(0,16).replace('T',' ')}　${x.name}（${x.code}）`);text(item,'div',x.tags.join(' ／ '));link(item,x.title,x.source_url);text(item,'div',x.basis,'ec-note');});
      text(catalysts,'p',data.analysis_note,'ec-note');
    }
    month.onchange=()=>{selected=null;render();};find('ec-watched').onchange=render;render();
  }).catch(e=>{find('ec-status').textContent='決算データ取得待ち／取得失敗：'+e.message;find('ec-status').classList.add('ec-error');});
 };
 if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();
