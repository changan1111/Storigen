const $ = id => document.getElementById(id);
const q = new URLSearchParams(location.search);
function showErr(t) { const e = $("err"); e.textContent = t; e.style.display = t ? "block" : "none"; }
(async () => {
  $("addr").value = q.get("server") || (window.storigen ? await window.storigen.getServer() : "");
  showErr(q.get("error") || "");
  $("addr").focus(); $("addr").select();
})();
$("f").addEventListener("submit", async ev => {
  ev.preventDefault(); showErr("");
  if (!window.storigen) return showErr("This page must be opened inside the Storigen app.");
  const r = await window.storigen.setServer($("addr").value);
  if (!r.ok) showErr(r.error || "Could not save the address.");
});
