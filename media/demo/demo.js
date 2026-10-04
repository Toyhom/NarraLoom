const languages = {
  en: {title: 'Weave a world. Let its stories unfold.', description: 'A 51-second tour of world creation, story play and the Python API.', guide: 'Get started', download: 'Download MP4', repository: 'Source code', video: 'NarraLoom demonstration', error: 'Video loading failed. Try the MP4 download below.', guidePath: 'guides/quickstart.md'},
  'zh-CN': {title: '织就一个世界，让故事在其中生长。', description: '51 秒了解世界创建、故事互动与 Python API。', guide: '开始使用', download: '下载 MP4', repository: '源代码', video: 'NarraLoom 演示视频', error: '视频加载失败，可以使用下方的 MP4 下载链接。', guidePath: 'guides/zh-CN/quickstart.md'},
  ja: {title: '世界を織り、物語を紡ぐ。', description: '世界の作成、物語のプレイ、Python API を 51 秒で紹介します。', guide: 'はじめる', download: 'MP4 をダウンロード', repository: 'ソースコード', video: 'NarraLoom デモ動画', error: '動画を読み込めませんでした。下のリンクから MP4 をダウンロードできます。', guidePath: 'guides/ja/quickstart.md'},
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
document.getElementById('download').href = 'https://github.com/Toyhom/NarraLoom/releases/download/v0.14.0/narraloom-' + locale + '.mp4';
const video = document.querySelector('video');
video.setAttribute('aria-label', text.video);
video.poster = 'poster-' + locale + '.jpg';
video.addEventListener('error', () => { document.getElementById('status').textContent = text.error; });
for (const source of video.querySelectorAll('source')) {
  source.src = 'narraloom-' + locale + (source.type.startsWith('video/mp4') ? '.mp4' : '.webm');
}
video.load();
