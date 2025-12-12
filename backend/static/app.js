// static/app.js

// --- DOM references ---
const form = document.getElementById("upload-form");
const statusEl = document.getElementById("status");
const analyzeBtn = document.getElementById("analyze-btn");

const summaryEl = document.getElementById("summary-content");
const categoriesOverviewEl = document.getElementById("categories-content");
const suggestionsOverviewEl = document.getElementById("suggestions-content");
const previewEl = document.getElementById("preview-content");

const categoriesFullEl = document.getElementById("categories-full-content");
const suggestionsFullEl = document.getElementById("suggestions-full-content");
const transactionsTableWrapper = document.getElementById("transactions-table-wrapper");
const addTransactionBtn = document.getElementById("add-transaction-btn");
const reanalyzeBtn = document.getElementById("reanalyze-btn");

const pageStartInput = document.getElementById("page-start");
const pageEndInput = document.getElementById("page-end");

// Tabs
const tabButtons = document.querySelectorAll(".tab-button");
const tabPanels = document.querySelectorAll(".tab-panel");

// --- State ---
let currentTransactions = []; // full list of transactions from backend
let currentSummary = null;

// --- Tab switching ---
tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;

    tabButtons.forEach((b) => {
      b.classList.toggle("tab-button--active", b === btn);
    });

    tabPanels.forEach((panel) => {
      panel.classList.toggle(
        "tab-panel--active",
        panel.dataset.tab === tab
      );
    });
  });
});

// --- Upload & analyze ---
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

  const pageStart = pageStartInput.value.trim();
  const pageEnd = pageEndInput.value.trim();
  if (pageStart) formData.append("page_start", pageStart);
  if (pageEnd) formData.append("page_end", pageEnd);

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
    handleAnalysisResult(data);
    setStatus("Analysis complete ✅", "success");
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Unexpected error during analysis.", "error");
    clearResults();
  } finally {
    setLoading(false);
  }
});

// --- Reanalyze after manual edits ---
reanalyzeBtn.addEventListener("click", async () => {
  if (!currentTransactions || currentTransactions.length === 0) {
    setStatus("No transactions to re-analyze. Upload a file first.", "error");
    return;
  }

  const updated = collectTransactionsFromTable();
  if (updated.length === 0) {
    setStatus("No valid transactions in table to re-analyze.", "error");
    return;
  }

  setStatus("Updating analysis based on your edits...", "loading");
  setLoading(true);

  try {
    const response = await fetch("/api/reanalyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transactions: updated }),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const msg =
        errorData.detail ||
        `Re-analysis failed (status ${response.status}).`;
      throw new Error(msg);
    }

    const data = await response.json();
    handleAnalysisResult(data);
    setStatus("Analysis updated ✅", "success");
  } catch (err) {
    console.error(err);
    setStatus(err.message || "Unexpected error during re-analysis.", "error");
  } finally {
    setLoading(false);
  }
});

// --- Add new transaction row ---
addTransactionBtn.addEventListener("click", () => {
  if (!currentTransactions) {
    currentTransactions = [];
  }
  const today = new Date().toISOString().slice(0, 10);

  currentTransactions.push({
    date: today,
    description: "",
    amount: 0.0,
    category: "Uncategorized",
    direction: "unknown",
  });

  renderTransactionsTable(currentTransactions);
});

// --- Helpers ---

function setStatus(message, type) {
  statusEl.textContent = message;
  statusEl.className = `status status--${type}`;
}

function setLoading(isLoading) {
  analyzeBtn.disabled = isLoading;
  reanalyzeBtn.disabled = isLoading;
  addTransactionBtn.disabled = isLoading;

  analyzeBtn.textContent = isLoading ? "Analyzing..." : "Analyze spending";
}

function clearResults() {
  summaryEl.innerHTML = "Upload a statement to see your totals.";
  categoriesOverviewEl.innerHTML = "Categories will appear here.";
  suggestionsOverviewEl.innerHTML =
    "Once we analyze your spending, we'll suggest where you could save.";
  previewEl.innerHTML = "A few example transactions will show up here.";

  categoriesFullEl.innerHTML =
    "Categories will appear here after you upload a statement.";
  suggestionsFullEl.innerHTML =
    "Upload a statement and/or adjust your transactions, then recompute analysis to see suggestions here.";

  transactionsTableWrapper.innerHTML = "No transactions loaded yet.";

  summaryEl.classList.add("empty-state");
  categoriesOverviewEl.classList.add("empty-state");
  suggestionsOverviewEl.classList.add("empty-state");
  previewEl.classList.add("empty-state");
  categoriesFullEl.classList.add("empty-state");
  suggestionsFullEl.classList.add("empty-state");
  transactionsTableWrapper.classList.add("empty-state");
}

function handleAnalysisResult(data) {
  const { summary, preview, transactions } = data;
  currentSummary = summary;
  currentTransactions = transactions || [];

  renderSummary(summary.overall);
  renderCategoriesOverview(summary.by_category);
  renderCategoriesFull(summary.by_category);
  renderSuggestionsOverview(summary.suggestions);
  renderSuggestionsFull(summary.suggestions);
  renderPreview(preview);
  renderTransactionsTable(currentTransactions);
}

// --- Rendering functions ---

function renderSummary(overall) {
  if (!overall) {
    summaryEl.innerHTML = "No summary data available.";
    summaryEl.classList.add("empty-state");
    return;
  }

  summaryEl.classList.remove("empty-state");

  const inflow = overall.total_inflow ?? 0;
  const outflow = overall.total_outflow ?? 0;
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

function renderCategoriesOverview(byCategory) {
  renderCategoriesIntoElement(byCategory, categoriesOverviewEl);
}

function renderCategoriesFull(byCategory) {
  renderCategoriesIntoElement(byCategory, categoriesFullEl);
}

function renderCategoriesIntoElement(byCategory, targetEl) {
  if (!byCategory || byCategory.length === 0) {
    targetEl.innerHTML = "No expense categories found.";
    targetEl.classList.add("empty-state");
    return;
  }

  targetEl.classList.remove("empty-state");

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

  targetEl.innerHTML = `
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

function renderSuggestionsOverview(suggestions) {
  renderSuggestionsIntoElement(suggestions, suggestionsOverviewEl);
}

function renderSuggestionsFull(suggestions) {
  renderSuggestionsIntoElement(suggestions, suggestionsFullEl);
}

function renderSuggestionsIntoElement(suggestions, targetEl) {
  if (!suggestions || suggestions.length === 0) {
    targetEl.innerHTML =
      "We couldn't generate specific savings ideas from this file. Try a longer period or adjust your transactions.";
    targetEl.classList.add("empty-state");
    return;
  }

  targetEl.classList.remove("empty-state");

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

  targetEl.innerHTML = `
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

function renderTransactionsTable(transactions) {
  if (!transactions || transactions.length === 0) {
    transactionsTableWrapper.innerHTML = "No transactions loaded yet.";
    transactionsTableWrapper.classList.add("empty-state");
    return;
  }

  transactionsTableWrapper.classList.remove("empty-state");

  const rows = transactions
    .map((tx, idx) => {
      const date = tx.date ? String(tx.date).slice(0, 10) : "";
      const desc = tx.description ?? "";
      const amount =
        typeof tx.amount === "number" ? tx.amount.toFixed(2) : tx.amount ?? "";
      const category = tx.category ?? "Uncategorized";
      const direction = tx.direction ?? "unknown";

      return `
        <tr data-index="${idx}">
          <td data-field="date" contenteditable="true">${date}</td>
          <td data-field="description" contenteditable="true">${escapeHtml(desc)}</td>
          <td data-field="amount" contenteditable="true">${amount}</td>
          <td>${category}</td>
          <td>${direction}</td>
        </tr>
      `;
    })
    .join("");

  transactionsTableWrapper.innerHTML = `
    <div class="table-wrapper">
      <table id="transactions-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Description</th>
            <th>Amount</th>
            <th>Category (auto)</th>
            <th>Direction (auto)</th>
          </tr>
        </thead>
        <tbody>
          ${rows}
        </tbody>
      </table>
    </div>
  `;
}

function collectTransactionsFromTable() {
  const table = document.getElementById("transactions-table");
  if (!table) return [];

  const rows = Array.from(table.querySelectorAll("tbody tr"));
  const result = [];

  rows.forEach((row) => {
    const dateCell = row.querySelector('td[data-field="date"]');
    const descCell = row.querySelector('td[data-field="description"]');
    const amountCell = row.querySelector('td[data-field="amount"]');

    const date = (dateCell?.textContent || "").trim();
    const description = (descCell?.textContent || "").trim();
    const amountStr = (amountCell?.textContent || "").trim();
    const parsedAmount = parseAmount(amountStr);

    if (!date && (amountStr === "" || isNaN(parsedAmount))) {
      // Completely empty row – skip
      return;
    }

    result.push({
      date,
      description,
      amount: isNaN(parsedAmount) ? null : parsedAmount,
    });
  });

  return result;
}

function parseAmount(text) {
  if (!text) return NaN;
  const cleaned = text.replace(/[^0-9.\-]/g, "");
  return parseFloat(cleaned);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
