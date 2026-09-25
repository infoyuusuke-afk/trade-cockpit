(()=>{
  "use strict";
  const clean=s=>String(s||"").replace(/\s+/g," ").trim();
  const looksRank=s=>/^#?\d+$/.test(clean(s))||/^(順位|rank)$/i.test(clean(s));
  function headerCells(table){
    const hs=[...table.querySelectorAll("thead th")];
    if(hs.length)return hs.map(x=>clean(x.textContent));
    const first=table.rows&&table.rows[0];
    if(first&&[...first.cells].every(c=>c.tagName==="TH"))return [...first.cells].map(x=>clean(x.textContent));
    return [];
  }
  function dataRows(table){
    if(table.tBodies&&table.tBodies.length)return [...table.tBodies].flatMap(b=>[...b.rows]);
    const rows=[...(table.rows||[])];
    if(rows.length&&[...rows[0].cells].every(c=>c.tagName==="TH"))rows.shift();
    return rows;
  }
  function cloneHtml(cell){
    return cell?cell.innerHTML:"";
  }
  function makeCard(row,headers,index){
    const cells=[...row.cells];
    if(!cells.length)return null;
    const values=cells.map(c=>clean(c.textContent));
    const card=document.createElement("article");
    card.className="cc-data-card";

    let titleIndex=0,rank="";
    if(cells.length>1&&(looksRank(values[0])||/順位|rank/i.test(headers[0]||""))){
      rank=values[0];titleIndex=1;
    }
    const head=document.createElement("div");head.className="cc-data-card-head";
    if(rank){
      const r=document.createElement("span");r.className="cc-data-rank";r.textContent=rank;head.appendChild(r);
    }
    const title=document.createElement("div");title.className="cc-data-title";
    title.innerHTML=cloneHtml(cells[titleIndex])||("項目 "+(index+1));
    head.appendChild(title);card.appendChild(head);

    const entries=[];
    cells.forEach((cell,i)=>{
      if(i===titleIndex||(rank&&i===0))return;
      const label=clean(headers[i]||("項目 "+(i+1)));
      const value=clean(cell.textContent);
      if(!value&&!cell.querySelector("a,button,img"))return;
      entries.push({label,html:cloneHtml(cell)});
    });

    const primary=entries.slice(0,6),extra=entries.slice(6);
    const metrics=document.createElement("div");metrics.className="cc-data-metrics";
    primary.forEach(x=>{
      const item=document.createElement("div");item.className="cc-data-metric";
      const l=document.createElement("span");l.textContent=x.label;
      const v=document.createElement("b");v.innerHTML=x.html||"—";
      item.append(l,v);metrics.appendChild(item);
    });
    card.appendChild(metrics);

    if(extra.length){
      const details=document.createElement("details");details.className="cc-data-details";
      const summary=document.createElement("summary");summary.textContent="詳細 "+extra.length+"項目";
      const more=document.createElement("div");more.className="cc-data-metrics";
      extra.forEach(x=>{
        const item=document.createElement("div");item.className="cc-data-metric";
        const l=document.createElement("span");l.textContent=x.label;
        const v=document.createElement("b");v.innerHTML=x.html||"—";
        item.append(l,v);more.appendChild(item);
      });
      details.append(summary,more);card.appendChild(details);
    }
    return card;
  }

  function convertTable(table){
    if(table.dataset.cardConverted==="1"||table.matches("[data-keep-table]"))return;
    const headers=headerCells(table),rows=dataRows(table).filter(r=>[...r.cells].some(c=>clean(c.textContent)||c.children.length));
    if(!rows.length)return;
    const grid=document.createElement("div");
    grid.className="cc-table-grid";
    grid.dataset.sourceTable="1";
    rows.forEach((row,i)=>{const c=makeCard(row,headers,i);if(c)grid.appendChild(c);});
    if(!grid.children.length)return;
    table.dataset.cardConverted="1";
    table.hidden=true;
    table.insertAdjacentElement("beforebegin",grid);
  }

  function convertAll(){
    document.querySelectorAll("main table, .tab-pane table, section table").forEach(convertTable);
    document.documentElement.classList.add("cc-all-cards-ready");
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>setTimeout(convertAll,0));
  else setTimeout(convertAll,0);
  window.cockpitConvertTablesToCards=convertAll;
})();