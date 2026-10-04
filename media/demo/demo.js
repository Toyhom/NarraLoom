const languages = {
  en: {title: 'Weave a world. Let its stories unfold.', description: 'Follow real workflows from a first world to multiplayer, replaceable engines, the SDK and research tools.', guide: 'Get started', download: 'Download MP4', repository: 'Source code', video: 'NarraLoom demonstration', error: 'Video loading failed. Try the MP4 download below.', guidePath: 'guides/quickstart.md'},
  'zh-CN': {title: '织就一个世界，让故事在其中生长。', description: '跟随完整操作，体验世界创作、多人互动、可替换引擎、SDK 与研究工具。', guide: '开始使用', download: '下载 MP4', repository: '源代码', video: 'NarraLoom 演示视频', error: '视频加载失败，可以使用下方的 MP4 下载链接。', guidePath: 'guides/zh-CN/quickstart.md'},
  ja: {title: '世界を織り、物語を紡ぐ。', description: '世界づくりからマルチプレイ、交換可能なエンジン、SDK、研究ツールまでを実際の操作で紹介。', guide: 'はじめる', download: 'MP4 をダウンロード', repository: 'ソースコード', video: 'NarraLoom デモ動画', error: '動画を読み込めませんでした。下のリンクから MP4 をダウンロードできます。', guidePath: 'guides/ja/quickstart.md'},
};
const requested = new URLSearchParams(location.search).get('lang');
const preferred = navigator.language.startsWith('zh') ? 'zh-CN' : navigator.language.startsWith('ja') ? 'ja' : 'en';
const locale = Object.hasOwn(languages, requested) ? requested : preferred;
const text = languages[locale];
document.documentElement.lang = locale;
document.title = 'NarraLoom · ' + text.video;
for (const id of ['title', 'description', 'guide', 'download', 'repository']) document.getElementById(id).textContent = text[id];
document.querySelector(`nav a[lang="${locale}"]`).setAttribute('aria-current', 'page');
document.getElementById('guide').href = 'https://github.com/Toyhom/NarraLoom/blob/main/' + text.guidePath;
document.getElementById('download').href = 'https://github.com/Toyhom/NarraLoom/releases/download/v0.21.0/narraloom-' + locale + '.mp4';
const video = document.querySelector('video');
video.setAttribute('aria-label', text.video);
video.poster = 'poster-' + locale + '.jpg';
video.addEventListener('error', () => { document.getElementById('status').textContent = text.error; });
for (const source of video.querySelectorAll('source')) {
  source.src = 'narraloom-' + locale + (source.type.startsWith('video/mp4') ? '.mp4' : '.webm');
}
video.load();

const labels = {
  en: {chapters: 'Chapters', transcript: 'Transcript', waiting: 'Generation waits are shortened. Captions explain each workflow.', duration: 'Duration'},
  'zh-CN': {chapters: '章节导航', transcript: '字幕全文', waiting: '生成等待已压缩，操作过程配有文字讲解。', duration: '时长'},
  ja: {chapters: 'チャプター', transcript: '字幕全文', waiting: '生成の待ち時間を短縮し、操作を字幕で解説しています。', duration: '長さ'},
}[locale];
const stamp = seconds => Math.floor(seconds / 60) + ':' + String(Math.floor(seconds % 60)).padStart(2, '0');
document.getElementById('chapters-title').textContent = labels.chapters;
document.getElementById('transcript-title').textContent = labels.transcript;
fetch('tour.json').then(response => { if (!response.ok) throw new Error('Tour metadata'); return response.json(); }).then(tours => {
  const tour = tours[locale];
  video.dataset.duration = tour.duration;
  document.getElementById('description').textContent += ' ' + labels.duration + ' ' + stamp(tour.duration) + ' · ' + labels.waiting;
  const track = document.createElement('track');
  track.kind = 'subtitles'; track.label = locale; track.srclang = locale; track.src = 'captions-' + locale + '.vtt';
  video.append(track);
  const jump = time => { video.currentTime = time; video.focus(); video.scrollIntoView({behavior: 'smooth', block: 'center'}); };
  for (const chapter of tour.chapters) {
    const li = document.createElement('li'); const button = document.createElement('button');
    button.type = 'button'; button.dataset.time = chapter.start;
    button.textContent = stamp(chapter.start) + '  ' + chapter.title;
    button.addEventListener('click', () => jump(chapter.start)); li.append(button);
    document.getElementById('chapters').append(li);
  }
  for (const cue of tour.cues) {
    const row = document.createElement('p'); const button = document.createElement('button');
    button.type = 'button'; button.textContent = stamp(cue.start); button.addEventListener('click', () => jump(cue.start));
    row.append(button, document.createTextNode('  ' + cue.text)); document.getElementById('transcript').append(row);
  }
  video.addEventListener('timeupdate', () => {
    const current = tour.chapters.findLast(chapter => chapter.start <= video.currentTime + 0.1);
    for (const button of document.querySelectorAll('#chapters button')) {
      if (Number(button.dataset.time) === current?.start) button.setAttribute('aria-current', 'true');
      else button.removeAttribute('aria-current');
    }
  });
}).catch(() => { document.getElementById('status').textContent = text.error; });
