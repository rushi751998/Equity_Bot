async function uploadDataFiles() {
  const inp = document.getElementById("du_files");
  const st = document.getElementById("du_status");
  const log = document.getElementById("du_log");
  if (!inp?.files?.length) { st.textContent = "Choose at least one file."; return; }
  const fd = new FormData();
  for (const f of inp.files) fd.append("files", f);
  fd.append("symbol", document.getElementById("du_symbol").value);
  fd.append("timeframe", document.getElementById("du_tf").value);
  fd.append("is_index", document.getElementById("du_isIndex").checked ? "1" : "0");
  st.textContent = "Uploading...";
  const res = await (await fetch("/api/data/upload", { method: "POST", body: fd })).json();
  st.textContent = res.ok ? `Stored ${res.total_rows} rows.` : `Error: ${res.error}`;
  log.style.display = "block";
  log.textContent = (res.results || []).map(r => `${r.symbol}: +${r.rows} (${r.status})`).join("\n");
}
