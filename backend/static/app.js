// static/app.js
const form = document.getElementById("upload-form");
const statusEl = document.getElementById("status");
const analyzeBtn = document.getElementById("analyze-btn");

const summaryEl = document.getElementById("summary-content");
const categoriesEl = document.getElementById("categories-content");
const suggestionsEl = document.getElementById("suggestions-content");
const previewEl = document.getElementById("preview-content");

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const fileInput = document.getElementById("statement");
  if (!fileInput.files || fileInput.files.length === 0) {
    setStatus("Please choose a file first.", "error");
    return;
  }

  const file = fileInput.files[0];
  const formData = new FormData();
  formData.append("statement", file);

  setStatus("Analyzing your statement...", "loading");
  setLoading(true);

  try {
    const response = await fetch("/api/analyze", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const msg =
        errorData.detail ||
        `Something went wrong (status ${response.status}). Please try another file.`;
      throw new Error(msg);
    }

    const data = await response.json();
    renderResults(data);
    setStatus("Analysis complete ✅", "success");
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Unexpected error during analysis.", "error");
    clearResults();
  } finally {
    setLoading(false);
  }
});

function setStatus(message, type) {
  statusEl.textContent = message;
  statusEl.className = `status status--${type}`;
}

function setLoading(isLoading) {
  analyzeBtn.disabled = isLoading;
  analyzeBtn.textContent = isLoading ? "Analyzing..." : "Analyze spending";
}

function clearResults() {
  summaryEl.innerHTML = "Upload a statement to see your totals.";
  categoriesEl.innerHTML = "Categories will appear here.";
  suggestionsEl.innerHTML = "Once we analyze your spending, we'll suggest where you could save.";
  previewEl.innerHTML = "A few example transactions will show up here.";

  summaryEl.classList.add("empty-state");
  categoriesEl.classList.add("empty-state");
  suggestionsEl.classList.add("empty-state");
  previewEl.classList.add("empty-state");
}

function renderResults(data) {
  const { summary, preview } = data;

  renderSummary(summary.overall);
  renderCategories(summary.by_category);
  renderSuggestions(summary.suggestions);
  renderPreview(preview);
}

function renderSummary(overall) {
  if (!overall) {
    summaryEl.innerHTML = "No summary data available.";
    summaryEl.classList.add("empty-state");
    return;
  }

  summaryEl.classList.remove("empty-state");

  const inflow = overall.total_inflow ?? 0;
  const outflow = overall.total_outflow ?? 0; // negative
  const net = overall.net ?? 0;

  const period =
    overall.period_start && overall.period_end
      ? `${overall.period_start} → ${overall.period_end}`
      : "Not available";

  summaryEl.innerHTML = `
    <div class="summary-grid">
      <div class="summary-item">
        <span class="summary-label">Total inflow</span>
        <span class="summary-value positive">$${inflow.toFixed(2)}</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">Total outflow</span>
        <span class="summary-value negative">$${Math.abs(outflow).toFixed(2)}</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">Net</span>
        <span class="summary-value ${net >= 0 ? "positive" : "negative"}">
          $${net.toFixed(2)}
        </span>
      </div>
      <div class="summary-item">
        <span class="summary-label">Transactions</span>
        <span class="summary-value">${overall.n_transactions}</span>
      </div>
      <div class="summary-item summary-item--span">
        <span class="summary-label">Statement period</span>
        <span class="summary-value">${period}</span>
      </div>
    </div>
  `;
}

function renderCategories(byCategory) {
  if (!byCategory || byCategory.length === 0) {
    categoriesEl.innerHTML = "No expense categories found.";
    categoriesEl.classList.add("empty-state");
    return;
  }

  categoriesEl.classList.remove("empty-state");

  const rows = byCategory
    .map((cat) => {
      const total = cat.total ?? 0;
      const share = (cat.share ?? 0) * 100;
      const count = cat.count ?? 0;

      return `
        <tr>
          <td>${cat.category}</td>
          <td>$${total.toFixed(2)}</td>
          <td>${count}</td>
          <td>${share.toFixed(1)}%</td>
        </tr>
      `;
    })
    .join("");

  categoriesEl.innerHTML = `
    <div class="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>Category</th>
            <th>Total spent</th>
            <th># Transactions</th>
            <th>Share of spend</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
        </tbody>
      </table>
    </div>
  `;
}

function renderSuggestions(suggestions) {
  if (!suggestions || suggestions.length === 0) {
    suggestionsEl.innerHTML =
      "We couldn't generate specific savings ideas from this file. Try a longer period.";
    suggestionsEl.classList.add("empty-state");
    return;
  }

  suggestionsEl.classList.remove("empty-state");

  const items = suggestions
    .map(
      (sugg) => `
      <li class="suggestion-item">
        <strong>${sugg.category}</strong><br />
        <span>${sugg.message}</span>
      </li>
    `
    )
    .join("");

  suggestionsEl.innerHTML = `
    <ul class="suggestions-list">
      ${items}
    </ul>
  `;
}

function renderPreview(preview) {
  if (!preview || preview.length === 0) {
    previewEl.innerHTML = "No preview rows available.";
    previewEl.classList.add("empty-state");
    return;
  }

  previewEl.classList.remove("empty-state");

  // Decide which columns to show
  const columns = ["date", "description", "amount", "category", "direction"].filter((col) =>
    preview.some((row) => col in row)
  );

  const headerRow = columns.map((col) => `<th>${col}</th>`).join("");

  const bodyRows = preview
    .map((row) => {
      const cells = columns
        .map((col) => {
          let value = row[col];
          if (col === "amount" && typeof value === "number") {
            value = `$${value.toFixed(2)}`;
          }
          if (col === "date" && typeof value === "string") {
            value = value.slice(0, 10);
          }
          return `<td>${value ?? ""}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");

  previewEl.innerHTML = `
    <div class="table-wrapper">
      <table>
        <thead><tr>${headerRow}</tr></thead>
        <tbody>${bodyRows}</tbody>
      </table>
    </div>
  `;
}
