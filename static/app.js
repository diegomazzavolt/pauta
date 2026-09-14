'use strict';
const $ = (id) => document.getElementById(id);
let video = null;
let selected = null;
let searchVersion = 0;
let selectionVersion = 0;
let downloadVersion = 0;
let ready = false;
const languageNames = new Intl.DisplayNames(['pt-BR'], { type: 'language' });
function languageName(track) { try { return languageNames.of(track.code.replace(/-orig$/, '')) || track.language; } catch { return track.language; } }

function notify(message = '') { $('notice').textContent = message; $('notice').hidden = !message; }
function messageOf(data) { return data?.detail?.message || 'Não foi possível concluir a consulta. Tente novamente.'; }
async function request(path, options = {}) {
  const response = await fetch(path, { ...options, signal: AbortSignal.timeout(110000) });
  if (!response.ok) { let data; try { data = await response.json(); } catch {} throw new Error(messageOf(data)); }
  return response;
}
function time(ms) { const s = Math.floor(ms / 1000); return (s >= 3600 ? `${Math.floor(s / 3600).toString().padStart(2,'0')}:` : '') + `${Math.floor(s / 60) % 60}`.padStart(2,'0') + ':' + `${s % 60}`.padStart(2,'0'); }
function updateInput() { $('clear-url').hidden = !$('video-url').value; }
$('video-url').addEventListener('input', updateInput);
$('clear-url').addEventListener('click', () => { $('video-url').value = ''; updateInput(); $('video-url').focus(); });
$('video-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const url = $('video-url').value.trim();
  if (!url) return;
  const version = ++searchVersion; ++selectionVersion; ++downloadVersion;
  video = null; selected = null; ready = false;
  notify(); $('results').hidden = true; $('empty').hidden = true; $('loading').hidden = false;
  $('find-button').disabled = true; $('find-label').textContent = 'Buscando…'; $('download-status').textContent = '';
  try {
    const response = await request('/api/videos', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({url})});
    const data = await response.json();
    if (version !== searchVersion) return;
    video = data;
    $('video-title').textContent = video.title; $('video-author').textContent = video.author;
    $('thumbnail').src = `https://i.ytimg.com/vi/${encodeURIComponent(video.videoId)}/mqdefault.jpg`;
    $('watch-link').href = `https://www.youtube.com/watch?v=${encodeURIComponent(video.videoId)}`;
    $('track-count').textContent = video.tracks.length;
    $('track-list').replaceChildren();
    for (const track of video.tracks) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'track'; button.dataset.trackId = track.id; button.setAttribute('aria-pressed','false');
      const label = document.createElement('span'), name = document.createElement('strong'), badge = document.createElement('small'), radio = document.createElement('span');
      const language = languageName(track);
      name.textContent = language.charAt(0).toUpperCase() + language.slice(1); badge.textContent = track.kind === 'automatic' ? 'Gerada automaticamente' : 'Enviada pelo autor';
      label.append(name,badge); radio.className = 'radio'; radio.setAttribute('aria-hidden','true'); button.append(label,radio);
      button.addEventListener('click', () => selectTrack(track)); $('track-list').append(button);
    }
    $('results').hidden = false;
    selectTrack(video.tracks[0]);
  } catch (error) {
    if (version !== searchVersion) return;
    notify(error.name === 'TimeoutError' ? 'A consulta demorou mais que o esperado. Tente novamente.' : error.message);
    $('empty').hidden = false;
  } finally {
    if (version === searchVersion) { $('loading').hidden = true; $('find-button').disabled = false; $('find-label').textContent = 'Buscar legendas'; }
  }
});
async function selectTrack(track) {
  const version = ++selectionVersion; ++downloadVersion; selected = track; ready = false;
  $('download-button').disabled = true; $('download-status').textContent = ''; $('cue-count').textContent = '';
  $('cues').replaceChildren(); $('transcript-status').textContent = 'Carregando a legenda…';
  document.querySelectorAll('.track').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.trackId === track.id)));
  try {
    const response = await request(`/api/videos/${video.token}/tracks/${track.id}`);
    const data = await response.json();
    if (version !== selectionVersion) return;
    $('transcript-status').textContent = ''; $('cue-count').textContent = `${data.cues.length} trechos`;
    const fragment = document.createDocumentFragment();
    // Keep long videos responsive. The downloaded file always contains every cue.
    for (const cue of data.cues.slice(0, 300)) {
      const row = document.createElement('div'), stamp = document.createElement('time'), text = document.createElement('p');
      row.className = 'cue'; stamp.textContent = time(cue.start); text.textContent = cue.text; row.append(stamp,text); fragment.append(row);
    }
    $('cues').append(fragment); $('cues').scrollTop = 0;
    if (data.cues.length > 300) $('transcript-status').textContent = 'Prévia dos primeiros 300 trechos. O download inclui a legenda completa.';
    ready = true; $('download-button').disabled = false;
  } catch (error) {
    if (version !== selectionVersion) return;
    $('transcript-status').textContent = error.message + ' Clique no idioma para tentar novamente.';
  }
}
$('download-button').addEventListener('click', async () => {
  if (!video || !selected || !ready) return;
  const version = ++downloadVersion;
  const currentVideo = video, track = selected, format = $('format').value;
  $('download-button').disabled = true; $('download-status').textContent = 'Preparando o arquivo…';
  try {
    const response = await request(`/api/videos/${currentVideo.token}/tracks/${track.id}/download?format=${format}`);
    const blob = await response.blob();
    if (version !== downloadVersion) return;
    const href = URL.createObjectURL(blob), anchor = document.createElement('a');
    anchor.href = href; anchor.download = `${currentVideo.title.replace(/[<>:"/\\|?*\x00-\x1f]/g,'').slice(0,120)}.${track.code}.${format}`;
    document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(href), 60000);
    $('download-status').textContent = `Arquivo ${format.toUpperCase()} enviado para os downloads do navegador.`;
  } catch (error) {
    if (version === downloadVersion) $('download-status').textContent = error.message;
  } finally { if (version === downloadVersion) $('download-button').disabled = !ready; }
});
