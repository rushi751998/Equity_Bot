async function runScanner() {
  const st = document.getElementById("scn_status");
  if (st) st.textContent = "Scanning...";
  const body = {
    timeframe: document.getElementById("scn_tf").value,
    min_chg_pct: parseFloat(document.getElementById("scn_min_chg").value || "-100"),
    max_chg_pct: parseFloat(document.getElementById("scn_max_chg").value || "100"),
    min_vol_mult: parseFloat(document.getElementById("scn_vol").value || "0"),
    above_ema21: document.getElementById("scn_ema").value === "1",
  };
  const res = await (
    await fetch("/api/scanners/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  ).json();
  if (st) st.textContent = `Scanned ${res.scanned || 0} symbols — ${(res.matches || []).length} match(es)`;
  const tb = document.getElementById("scnRows");
  if (tb) {
    tb.innerHTML = (res.matches || []).map(m => `<tr>
      <td class="left"><b>${m.symbol}</b></td>
      <td>${m.close}</td>
      <td>${m.low}</td>
      <td class="${m.chg_pct >= 0 ? "pos" : "neg"}">${m.chg_pct}%</td>
      <td>${m.vol_mult}x</td>
      <td>${m.ema21}</td>
      <td class="left"><button class="btn primary" onclick="sendToPortfolio('${m.symbol}', ${m.close}, ${m.low})">Load Trade &rarr;</button></td>
    </tr>`).join("") || `<tr><td colspan="7" class="left muted">No matches</td></tr>`;
  }
}

function sendToPortfolio(symbol, closePx, lowPx) {
  const sl = Math.min(lowPx, closePx * 0.985).toFixed(2);
  const risk = Math.max(0.5, closePx - parseFloat(sl));
  const target = (closePx + 3 * risk).toFixed(2);
  sessionStorage.setItem("tfalgo_prefill_order", JSON.stringify({ symbol, price: closePx, sl, target }));
  window.location.href = "/portfolio";
}
