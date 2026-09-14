'use strict';
const byId = id => document.getElementById(id);
const el = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; };
let dashboard = null, page = 'edition', archiveOffset = 0, archiveVersion = 0, editionVersion = 0, refreshBusy = false;
let sourcesFingerprint = '', editionFingerprint = '';
const dates = new Intl.DateTimeFormat('pt-BR', {dateStyle:'long', timeZone:'America/Sao_Paulo'});
const shortDates = new Intl.DateTimeFormat('pt-BR', {dateStyle:'short', timeStyle:'short', timeZone:'America/Sao_Paulo'});
const statusNames = {queued:'Aguardando primeira consulta', watching:'Acompanhando', catchup_pending:'Recuperação pendente', error:'Nova tentativa programada', duplicate:'Canal repetido', pending:'Aguardando legenda', collecting:'Acessando legenda', waiting:'Legenda pendente', ready:'Legenda salva'};
const priorities = {5:'Muito importante',4:'Importante',3:'Normal',2:'Secundária',1:'Baixa'};
function notice(text='') { byId('global-notice').hidden = !text; byId('global-notice').textContent = text; }
async function api(path, body) {
  const response = await fetch('/api/journal' + path, {method:body === undefined ? 'GET':'POST', headers:body === undefined ? {} : {'Content-Type':'application/json'}, body:body === undefined ? undefined : JSON.stringify(body), signal:AbortSignal.timeout(20000)});
  let data; try { data = await response.json(); } catch { throw new Error('O servidor retornou uma resposta inesperada.'); }
  if (!response.ok) throw new Error(data?.detail?.message || 'Não foi possível concluir. Confira os dados e tente novamente.');
  return data;
}
function showPage(name) {
  page = name;
  document.querySelectorAll('.page').forEach(n=>n.hidden=n.id !== 'page-'+name);
  document.querySelectorAll('.nav-tab').forEach(n=>n.classList.toggle('selected',n.dataset.page===name));
  if(name==='archive') loadArchive();
  if(name==='edition') loadEdition();
}
document.querySelectorAll('[data-page]').forEach(n=>n.addEventListener('click',()=>showPage(n.dataset.page)));
document.querySelectorAll('[data-close]').forEach(n=>n.addEventListener('click',()=>byId(n.dataset.close).close()));
function openImport() { byId('import-feedback').textContent=''; byId('import-dialog').showModal(); }
['start-import','import-open'].forEach(id=>byId(id).addEventListener('click',openImport));
byId('pending-sources').addEventListener('click',()=>showPage('sources'));
byId('editorial-open').addEventListener('click',()=>{byId('api-model').value=dashboard?.model || ''; byId('editorial-dialog').showModal();});

byId('channel-file').addEventListener('change',async event=>{
  const file=event.target.files[0]; if(!file)return;
  if(file.size>128000){byId('import-feedback').textContent='O arquivo deve ter até 128 KB.'; event.target.value=''; return;}
  try {
    const bytes = await file.arrayBuffer();
    const view = new Uint8Array(bytes);
    const encoding = view[0]===255 && view[1]===254 ? 'utf-16le' : view[0]===254 && view[1]===255 ? 'utf-16be' : 'utf-8';
    byId('channel-links').value=new TextDecoder(encoding,{fatal:true}).decode(bytes);
    if(!byId('topic-name').value) byId('topic-name').value=file.name.replace(/\.txt$/i,'').slice(0,80);
    byId('import-feedback').textContent='Arquivo carregado. Confira o assunto e salve para começar.';
  }catch{byId('import-feedback').textContent='Não foi possível ler o TXT. Salve o arquivo em UTF-8.';}
});
byId('import-form').addEventListener('submit',async event=>{
  event.preventDefault(); byId('import-submit').disabled=true;
  try {
    const result=await api('/import',{topic:byId('topic-name').value,text:byId('channel-links').value,priority:Number(byId('topic-priority').value),include_recent:byId('include-recent').checked});
    byId('import-feedback').textContent=`${result.added} canal(is) cadastrado(s). ${result.duplicates} repetido(s) ignorado(s).` + (result.errors.length ? '\n'+result.errors.map(x=>`Linha ${x.line}: ${x.message} (${x.value})`).join('\n') : '\nO assunto está salvo. O último vídeo de cada canal entrará automaticamente na coleta e análise. Você pode enviar outro bloco ou fechar esta janela.');
    if(result.added || result.duplicates){await refresh(); showPage('sources');}
  }catch(error){byId('import-feedback').textContent=error.message;}
  finally{byId('import-submit').disabled=false;}
});
byId('editorial-form').addEventListener('submit',async event=>{
  event.preventDefault();const button=event.submitter;button.disabled=true;
  try{await api('/editorial',{key:byId('api-key').value,model:byId('api-model').value});byId('api-key').value='';byId('editorial-feedback').textContent='Configuração salva. Os textos pendentes entrarão na redação automaticamente.';await refresh();}
  catch(error){byId('editorial-feedback').textContent=error.message;}finally{button.disabled=false;}
});
byId('check-now').addEventListener('click',async()=>{byId('check-now').disabled=true;try{await api('/check',{});byId('monitor-detail').textContent='Verificação solicitada. As consultas respeitam o intervalo de segurança.';}catch(error){notice(error.message);}finally{byId('check-now').disabled=false;}});

function sourceLink(id,title){const a=el('a',title);a.href=`https://www.youtube.com/watch?v=${encodeURIComponent(id)}`;a.target='_blank';a.rel='noopener noreferrer';return a;}
function renderTopics(){
  const fingerprint=JSON.stringify([dashboard.topics,dashboard.channels]);
  if(fingerprint===sourcesFingerprint)return;sourcesFingerprint=fingerprint;
  byId('topics-list').replaceChildren();byId('topic-suggestions').replaceChildren();
  const previous=byId('archive-topic').value;byId('archive-topic').replaceChildren(new Option('Todos os assuntos',''));
  for(const topic of dashboard.topics){
    byId('topic-suggestions').append(new Option(topic.name));byId('archive-topic').append(new Option(topic.name,topic.id));
    const card=el('article',undefined,'topic-card'),header=el('div',undefined,'topic-header'),left=el('div');
    const channels=dashboard.channels.filter(c=>c.topic_id===topic.id);
    left.append(el('h2',topic.name),el('p',`${channels.filter(c=>c.active).length} canais ativos · prioridade ${priorities[topic.priority].toLowerCase()}`));
    const label=el('label','Prioridade'),select=el('select');
    for(const [value,text] of Object.entries(priorities).reverse())select.append(new Option(text,value));
    select.value=topic.priority;select.addEventListener('change',async()=>{select.disabled=true;try{await api(`/topics/${topic.id}/priority`,{priority:Number(select.value)});await refresh();}catch(error){notice(error.message);}finally{select.disabled=false;}});
    label.append(select);header.append(left,label);card.append(header);
    for(const channel of channels){
      const row=el('div',undefined,'channel-row'),info=el('div'),link=el('a',channel.title||channel.url);link.href=channel.url;link.target='_blank';link.rel='noopener noreferrer';
      info.append(link,el('p',`${channel.active ? statusNames[channel.status]||channel.status : 'Pausado'}${channel.checked ? ' · Última consulta '+shortDates.format(new Date(channel.checked*1000)) : ''}`));
      if(channel.error)info.append(el('p',channel.error,'channel-error'));
      const button=el('button',channel.active?'Pausar':'Retomar','button small');
      button.disabled=channel.status==='duplicate';
      button.addEventListener('click',async()=>{button.disabled=true;try{await api(`/channels/${channel.id}/active`,{active:!channel.active});await refresh();}catch(error){notice(error.message);button.disabled=false;}});
      row.append(info,button);card.append(row);
    }
    byId('topics-list').append(card);
  }
  byId('archive-topic').value=previous;byId('no-topics').hidden=dashboard.topics.length>0;
}
async function refresh(){
  if(refreshBusy)return;refreshBusy=true;
  try{
    dashboard=await api('/dashboard');notice();
    if(!byId('edition-date').value)byId('edition-date').value=dashboard.today;
    byId('edition-date').max=dashboard.today;
    byId('top-date').textContent=dates.format(new Date(dashboard.today+'T12:00:00-03:00')).toUpperCase();
    byId('nav-count').textContent=dashboard.topics.length;
    byId('stat-topics').textContent=dashboard.topics.length;
    byId('stat-channels').textContent=dashboard.channels.filter(c=>c.active).length;
    byId('stat-ready').textContent=dashboard.counts.ready||0;
    byId('stat-pending').textContent=Object.entries(dashboard.counts).reduce((sum,[status,n])=>sum+(status==='ready'?0:n),0);
    byId('ai-dot').classList.toggle('on',dashboard.ai_configured);
    const recent=dashboard.worker.heartbeat>(Date.now()/1000-300);
    byId('monitor-status').textContent=recent?dashboard.worker.message:'Monitor sem atividade recente';
    byId('monitor-detail').textContent=dashboard.worker.error || `Consulta a cada ${Math.round(dashboard.interval/60)} minutos. ${dashboard.pending_analysis} textos aguardam redação${dashboard.ai_configured ? '.' : ' · configure a redação para gerar as matérias.'}`;
    if(dashboard.worker.caption_blocks>0 && dashboard.worker.caption_next>Date.now()/1000) byId('monitor-detail').textContent = `O YouTube limitou o acesso às legendas. Nova consulta após ${shortDates.format(new Date(dashboard.worker.caption_next*1000))}. ${dashboard.counts.ready||0} legendas já estão salvas. Os canais continuam sendo acompanhados.`;
    if(!['SELECT','INPUT'].includes(document.activeElement.tagName))renderTopics();
    if(page==='edition')await loadEdition();
    if(page==='archive'&&!byId('video-dialog').open)await loadArchive();
  }catch(error){notice('Não foi possível atualizar o jornal. Verifique se o servidor está ligado.');}
  finally{refreshBusy=false;}
}

function citedText(node,text,sources){
  const valid=new Set(sources.map(s=>s.id));const pieces=text.split(/(\[[\w-]{11}\])/g);
  for(const piece of pieces){const id=piece.slice(1,-1);if(piece.startsWith('[')&&valid.has(id)){const index=sources.findIndex(s=>s.id===id)+1;node.append(sourceLink(id,`[${index}]`));}else node.append(document.createTextNode(piece));}
}
function renderStory(story,cover){
  const article=el('article',undefined,cover?'cover':'topic-story'),main=el('div',undefined,'cover-story');
  main.append(el('span',story.topic.toUpperCase(),'article-topic'),el('h2',story.headline));
  const summary=el('div',undefined,'story-copy');citedText(summary,story.summary,story.sources);main.append(summary);
  const aside=el('aside',undefined,'story-side');aside.append(el('h3','O que está em pauta'));
  const points=el('ul',undefined,'point-list');for(const point of story.points){const li=el('li');citedText(li,point,story.sources);points.append(li);}aside.append(points);
  const sources=el('div',undefined,'source-list');sources.append(el('h4',`${story.sources.length} FONTES DESTA COBERTURA`));
  story.sources.forEach((s,i)=>sources.append(sourceLink(s.id,`${i+1}. ${s.title} ↗`)));aside.append(sources);
  if(cover){aside.append(el('p','Na capa: prioridade do assunto + relevância editorial + diversidade de canais.','cover-reason'));article.append(main,aside);}else{main.append(points,sources);article.append(main);}
  return article;
}
async function loadEdition(){
  if(!dashboard)return;const version=++editionVersion;
  try{
    const day=byId('edition-date').value||dashboard.today;const {edition}=await api('/editions/'+day);
    if(version!==editionVersion)return;
    byId('edition-heading').textContent=day===dashboard.today?'O dia, por assunto.':dates.format(new Date(day+'T12:00:00-03:00'));
    const fingerprint=JSON.stringify(edition);
    if(fingerprint!==editionFingerprint){editionFingerprint=fingerprint;byId('edition-content').replaceChildren();if(edition){byId('edition-content').append(renderStory(edition.sections[0],true));const rest=el('div',undefined,'section-stories');edition.sections.slice(1).forEach(s=>rest.append(renderStory(s,false)));byId('edition-content').append(rest);}}
    byId('edition-empty').hidden=!!edition || dashboard.topics.length>0;
    byId('edition-pending').hidden=!!edition || dashboard.topics.length===0;
    byId('pending-copy').textContent=day!==dashboard.today?'Nenhuma edição foi produzida nesta data. Selecione outra data para consultar o histórico.':!dashboard.ai_configured?'Seus canais podem ser acompanhados e as legendas ficam guardadas no acervo. Ative a Redação com uma chave e um modelo da API OpenAI para transformar esse material em matérias por assunto.':dashboard.pending_analysis?'O conteúdo já chegou ao acervo e está aguardando análise. A edição será montada automaticamente com as matérias e suas fontes.':'O jornal aguarda conteúdo dos canais cadastrados. A edição é atualizada ao longo do dia, conforme as legendas ficam disponíveis.';
    byId('edition-status').textContent=edition?`Edição de ${dates.format(new Date(day+'T12:00:00-03:00'))} · atualizada ${shortDates.format(new Date(edition.updated*1000))}`:'Sem matérias nesta edição. Nenhum conteúdo foi inventado para preencher a capa.';
  }catch(error){notice(error.message);}
}
byId('edition-date').addEventListener('change',loadEdition);
async function loadArchive(){
  const version=++archiveVersion;
  try{
    const topic=byId('archive-topic').value;
    const data=await api(`/videos?offset=${archiveOffset}${topic?'&topic_id='+encodeURIComponent(topic):''}`);
    if(version!==archiveVersion)return;
    byId('videos-list').replaceChildren();
    if(!data.items.length)byId('videos-list').append(el('p','Os vídeos encontrados nos canais aparecerão aqui, junto com o estado da legenda e da análise.','quiet-empty'));
    for(const video of data.items){
      const row=el('article',undefined,'video-row'),info=el('div'),actions=el('div',undefined,'video-actions');
      info.append(el('h2',video.title),el('span',statusNames[video.status]||video.status,'badge '+(video.status==='ready'?'':'waiting')));
      info.append(el('p',`${video.published_known ? 'Publicado em '+shortDates.format(new Date(video.published*1000)) : 'Encontrado em '+shortDates.format(new Date(video.discovered*1000))+' · publicação não informada pelo YouTube'}${video.status==='ready' ? ' · '+(video.analysis_status==='ready'?'Analisado':video.analysis_status==='error'?'Falha na redação':'Aguardando redação') : ''}`));
      if(video.error||video.analysis_error)info.append(el('p',video.error||video.analysis_error));
      const read=el('button','Abrir conteúdo','button small');read.addEventListener('click',()=>openVideo(video.id));actions.append(read);
      if(video.status!=='ready'||video.analysis_status==='error'){const retry=el('button','Tentar novamente','button small');retry.addEventListener('click',async()=>{retry.disabled=true;try{await api(`/videos/${video.id}/retry`,{});await loadArchive();}catch(error){notice(error.message);}});actions.append(retry);}
      row.append(info,actions);byId('videos-list').append(row);
    }
    byId('page-info').textContent=data.total?`${archiveOffset+1}–${Math.min(archiveOffset+50,data.total)} de ${data.total} vídeos`:'0 vídeos';byId('previous-page').disabled=archiveOffset===0;byId('next-page').disabled=archiveOffset+50>=data.total;
  }catch(error){notice(error.message);}
}
byId('archive-topic').addEventListener('change',()=>{archiveOffset=0;loadArchive();});
byId('previous-page').addEventListener('click',()=>{archiveOffset=Math.max(0,archiveOffset-50);loadArchive();});
byId('next-page').addEventListener('click',()=>{archiveOffset+=50;loadArchive();});
async function openVideo(id){
  try{const video=await api('/videos/'+id);byId('read-title').textContent=video.title;byId('read-meta').replaceChildren(sourceLink(id,'Abrir vídeo original no YouTube ↗'));byId('read-text').textContent=video.cleaned_text||video.error||'A legenda automática ainda está pendente.';byId('read-analysis').replaceChildren();if(video.analysis){byId('read-analysis').append(el('h3','Resumo da redação'),el('p',video.analysis.summary));}byId('video-dialog').showModal();}catch(error){notice(error.message);}
}
refresh();setInterval(()=>{if(!document.hidden)refresh();},10000);
