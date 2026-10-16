const $ = id => document.getElementById(id);
let corpus = [];
let busy = false;
function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").className = error ? "error" : "";
}
function option(value, label) {
  const item = document.createElement("option");
  item.value = value; item.textContent = label; return item;
}
function updateScope() {
  const selected = corpus.find(c => c.ticker === $("ticker").value);
  const filings = (selected?.filings || []).filter(f => !$("form").value || f.form === $("form").value);
  $("filing-date").replaceChildren(option("", "All indexed dates"));
  for (const date of [...new Set(filings.map(f => f.filing_date))]) {
    $("filing-date").append(option(date, date));
  }
  $("coverage").replaceChildren();
  if (selected) {
    const title = document.createElement("strong");
    title.textContent = (selected.coverage === "selected excerpts" ? "Selected excerpts from " : "") + filings.length + " indexed filing" + (filings.length === 1 ? "" : "s");
    $("coverage").append(title);
    for (const filing of filings) {
      const line = document.createElement("div");
      line.textContent = filing.form + " · period ended " + (filing.report_date || "unspecified");
      $("coverage").append(line);
    }
  }
}
function renderResult(data) {
  $("result").hidden = false;
  $("empty-state").hidden = true;
  $("answer").textContent = data.answer;
  $("answer-state").textContent = data.status === "answered" ? "Grounding check passed" : "More evidence needed";
  $("snapshot").textContent = (data.snapshot.coverage === "selected excerpts" ? "Selected excerpts · built " : "Indexed snapshot · built ") + data.snapshot.built_at.slice(0, 10)
    + " · latest included filing " + data.snapshot.latest_filing_date;
  $("sources").replaceChildren();
  for (const source of data.sources) {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = "[" + source.source_id + "] " + source.form + " · " + source.filing_date
      + (source.section_hint ? " · " + source.section_hint : "");
    const metadata = document.createElement("p"); metadata.className = "source-meta";
    metadata.textContent = "Reporting period: " + (source.report_date || "not specified")
      + " · " + source.kind + " excerpt";
    const excerpt = document.createElement("div"); excerpt.className = "excerpt";
    excerpt.textContent = source.excerpt;
    details.append(summary, metadata, excerpt);
    try {
      const url = new URL(source.source_url);
      if (url.protocol === "https:" && url.hostname === "www.sec.gov") {
        const link = document.createElement("a");
        link.href = url.href; link.className = "source-link"; link.target = "_blank";
        link.rel = "noopener noreferrer"; link.textContent = "Read the SEC filing ↗";
        details.append(link);
      }
    } catch {}
    $("sources").append(details);
  }
}
$("ticker").addEventListener("change", updateScope);
$("form").addEventListener("change", updateScope);
for (const button of document.querySelectorAll("[data-question]")) {
  button.addEventListener("click", () => { if (!busy) { $("question").value = button.dataset.question; $("question").focus(); } });
}
$("question-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (busy || !$("ticker").value) return;
  busy = true; $("submit").disabled = true; $("submit").textContent = "Reading the evidence…";
  $("result").hidden = true;
  notice("Retrieving filing excerpts and checking the answer. This can take a moment.");
  const headers = {"Content-Type": "application/json"};
  if ($("token").value) headers.Authorization = "Bearer " + $("token").value;
  const payload = {ticker: $("ticker").value, question: $("question").value.trim()};
  if ($("form").value) payload.form = $("form").value;
  if ($("filing-date").value) payload.filing_date = $("filing-date").value;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 115000);
  try {
    const response = await fetch("/query", {method: "POST", headers, body: JSON.stringify(payload), signal: controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Check your question and selected filters.");
    renderResult(data);
    notice(data.status === "answered" ? "Answer checked against the retrieved excerpts. Verify the sources below." : "The available evidence did not support a complete answer.");
  } catch (error) {
    notice(error.name === "AbortError" ? "The request timed out. Try a narrower question." : error.message, true);
  } finally {
    clearTimeout(timer);
    // Do not retain the deployment token beyond this request.
    $("token").value = "";
    busy = false; $("submit").disabled = false; $("submit").textContent = "Find an answer ↗";
  }
});
async function init() {
  try {
    const response = await fetch("/corpus");
    if (!response.ok) throw new Error("The filing corpus could not be loaded.");
    const data = await response.json();
    corpus = data.tickers;
    $("token-area").hidden = !data.requires_token;
    $("ticker").replaceChildren();
    for (const item of corpus) $("ticker").append(option(item.ticker, item.ticker));
    if (!corpus.length) {
      $("ticker").append(option("", "No indexed companies"));
      notice("No filings have been indexed for this deployment yet. Add a filing corpus to begin.");
      return;
    }
    updateScope();
    if (!data.answering_configured) {
      notice("Filings are available. The deployment owner needs to configure the AI API key before questions can be answered.");
      return;
    }
    $("submit").disabled = false;
    notice("Ready. Choose a company and ask a question about its indexed filings.");
  } catch (error) {
    notice(error.message, true);
  }
}
init();
