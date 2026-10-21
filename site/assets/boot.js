(function () {
  var root = document.documentElement;
  var theme = null;
  var lang = null;
  try {
    theme = localStorage.getItem("patchy-theme");
    lang = localStorage.getItem("patchy-lang");
  } catch (error) {
    theme = null;
    lang = null;
  }
  var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  var mode = theme === "light" || theme === "dark" ? theme : dark ? "dark" : "light";
  root.setAttribute("data-theme", mode);
  if (lang !== "tr" && lang !== "en") {
    var preferred = (navigator.languages && navigator.languages[0]) || navigator.language || "tr";
    lang = /^tr(\b|-)/i.test(preferred) ? "tr" : "en";
  }
  root.setAttribute("lang", lang);
  var meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", mode === "dark" ? "#04151c" : "#e6f6f4");
})();
