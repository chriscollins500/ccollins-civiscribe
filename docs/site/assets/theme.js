try {
  const stored = localStorage.getItem("civiscribe-theme");
  const theme = stored === "light" || stored === "dark" ? stored : "dark";
  document.documentElement.dataset.theme = theme;
} catch {
  document.documentElement.dataset.theme = "dark";
}
