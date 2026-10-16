
  window.__h3ApplyTheme = function (mode) {
    var sys = false;
    try { sys = window.matchMedia('(prefers-color-scheme: dark)').matches; } catch (e) {}
    var dark = (mode === 'dark') || (mode !== 'light' && sys);
    document.body.classList.toggle('dark', dark);
    var app = document.querySelector('gradio-app');
    if (app) { app.classList.toggle('dark', dark); }
    window.__h3ThemeMode = mode;
    try { localStorage.setItem('h3-theme', mode); } catch (e) {}
    return dark;
  };
