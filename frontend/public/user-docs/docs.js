function setLang(lang) {
  var isCs = lang === 'cs'
  document.documentElement.lang = lang
  document.getElementById('panel-cs').classList.toggle('active', isCs)
  document.getElementById('panel-en').classList.toggle('active', !isCs)
  document.getElementById('nav-cs').classList.toggle('active', isCs)
  document.getElementById('nav-en').classList.toggle('active', !isCs)
  document.getElementById('btn-cs').classList.toggle('active', isCs)
  document.getElementById('btn-en').classList.toggle('active', !isCs)
  try { localStorage.setItem('webrag_docs_lang', lang) } catch (e) {}
}

try {
  var saved = localStorage.getItem('webrag_docs_lang')
  if (saved === 'en') setLang('en')
} catch (e) {}
