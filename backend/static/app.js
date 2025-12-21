// static/app.js

"use strict";

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
const downloadCsvBtn = document.getElementById("download-csv-btn");

const pageStartInput = document.getElementById("page-start");
const pageEndInput = document.getElementById("page-end");

// Tabs
const tabButtons = document.querySelectorAll(".tab-button");
const tabPanels = document.querySelectorAll(".tab-panel");

// --- State ---
let currentTransactions = []; // latest transactions from backend
let currentSummary = null;
let isLoading = false;

const ANALYZE_BTN_DEFAULT_TEXT = analyzeBtn?.textContent || "Analyze spending";

// --- Utilities ---
function setStatus(message, type) {
  if (!statusEl) return;
  statusEl.textContent = message;
  statusEl.className = `status status--${type}`;
}

function setLoading(nextLoading) {
  isLoading = nextLoading;

  if (analyzeBtn) {
    analyzeBtn.disabled = nextLoading;
    analyzeBtn.textContent = nextLoading ? "Working..." : ANALYZE_BTN_DEFAULT_TEXT;
  }
  if (reanalyzeBtn) reanalyzeBtn.disabled = nextLoading;
  if (addTransactionBtn) addTransactionBtn.disabled = nextLoading;
  if (downloadCsvBtn) downloadCsvBtn.disabled = nextLoading;
}

async function safeReadJson(response) {
  const text = await response.text().catch(() => "");
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    const err = (await safeReadJson(res)) || {};
    const msg = err.detail || `Request failed (status ${res.status}).`;
    throw new Error(msg);
  }
  return res.json();
}

function clearResults() {
  if (summaryEl) {
    summaryEl.innerHTML = "Upload a statement to see your totals.";
    summaryEl.classList.add("empty-state");
  }
  if (categoriesOverviewEl) {
    categoriesOverviewEl.innerHTML = "Categories will appear here.";
    categoriesOverviewEl.classList.add("empty-state");
  }
  if (suggestionsOverviewEl) {
    suggestionsOverviewEl.innerHTML =
      "Once we analyze your spending, we'll suggest where you could save.";
    suggestionsOverviewEl.classList.add("empty-state");
  }
  if (previewEl) {
    previewEl.innerHTML = "A few example transactions will show up here.";
    previewEl.classList.add("empty-state");
  }
  if (categoriesFullEl) {
    categoriesFullEl.innerHTML =
      "Categories will appear here after you upload a statement.";
    categoriesFullEl.classList.add("empty-state");
  }
  if (suggestionsFullEl) {
    suggestionsFullEl.innerHTML =
      "Upload a statement and/or adjust your transactions, then recompute analysis to see suggestions here.";
    suggestionsFullEl.classList.add("empty-state");
  }
  if (transactionsTableWrapper) {
    transactionsTableWrapper.innerHTML = "No transactions loaded yet.";
    transactionsTableWrapper.classList.add("empty-state");
  }

  currentSummary = null;
  currentTransactions = [];
}

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function parseAmount(text) {
  if (!text) return NaN;
  const cleaned = String(text).replace(/[^0-9.\-]/g, "");
  return parseFloat(cleaned);
}

function normalizeDateString(s) {
  // Accept "YYYY-MM-DD" or longer ISO; return "YYYY-MM-DD" if possible.
  const t = String(s || "").trim();
  if (!t) return "";
  return t.length >= 10 ? t.slice(0, 10) : t;
}

function handleAnalysisResult(data) {
  const { summary, preview, transactions } = data || {};
  currentSummary = summary || null;
  currentTransactions = Array.isArray(transactions) ? transactions : [];

  renderSummary(summary?.overall);
  renderCategoriesOverview(summary?.by_category);
  renderCategoriesFull(summary?.by_category);
  renderSuggestionsOverview(summary?.suggestions);
  renderSuggestionsFull(summary?.suggestions);
  renderPreview(preview);
  renderTransactionsTable(currentTransactions);
}

// --- Tab switching ---
tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;

    tabButtons.forEach((b) => {
      b.classList.toggle("tab-button--active", b === btn);
    });

    tabPanels.forEach((panel) => {
      panel.classList.toggle("tab-panel--active", panel.dataset.tab === tab);
    });
  });
});

// --- Upload & analyze ---
if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (isLoading) return;

    const fileInput = document.getElementById("statement");
    if (!fileInput?.files || fileInput.files.length === 0) {
      setStatus("Please choose a file first.", "error");
      return;
    }

    const file = fileInput.files[0];
    const formData = new FormData();
    formData.append("statement", file);

    const pageStart = pageStartInput?.value?.trim();
    const pageEnd = pageEndInput?.value?.trim();
    if (pageStart) formData.append("page_start", pageStart);
    if (pageEnd) formData.append("page_end", pageEnd);

    setStatus("Analyzing your statement...", "loading");
    setLoading(true);

    try {
      const data = await fetchJson("/api/analyze", {
        method: "POST",
        body: formData,
      });

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
}

// --- Reanalyze after manual edits ---
reanalyzeBtn?.addEventListener("click", async () => {
  if (isLoading) return;

  if (!currentTransactions || currentTransactions.length === 0) {
    setStatus("No transactions to re-analyze. Upload a file first.", "error");
    return;
  }

  const updated = collectTransactionsFromTable({ includeAutoColumns: false });
  if (updated.length === 0) {
    setStatus("No valid transactions in table to re-analyze.", "error");
    return;
  }

  setStatus("Updating analysis based on your edits...", "loading");
  setLoading(true);

  try {
    const data = await fetchJson("/api/reanalyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transactions: updated }),
    });

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
addTransactionBtn?.addEventListener("click", () => {
  if (isLoading) return;

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

// --- Download CSV (exports what is currently shown/edited) ---
downloadCsvBtn?.addEventListener("click", async () => {
  if (isLoading) return;

  // Include category/direction as displayed in the table
  const txns = collectTransactionsFromTable({ includeAutoColumns: true });

  if (!txns || txns.length === 0) {
    alert("No transactions to export.");
    return;
  }

  setStatus("Preparing CSV download...", "loading");
  setLoading(true);

  try {
    const res = await fetch("/api/export/csv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transactions: txns }),
    });

    if (!res.ok) {
      const err = (await safeReadJson(res)) || {};
      throw new Error(err.detail || `Export failed (${res.status}).`);
    }

    // Try to use filename from Content-Disposition if provided
    let filename = "transactions_export.csv";
    const cd = res.headers.get("Content-Disposition");
    if (cd) {
      const match = cd.match(/filename="([^"]+)"/i);
      if (match?.[1]) filename = match[1];
    }

    const blob = await res.blob();
    const url = window.URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();

    window.URL.revokeObjectURL(url);
    setStatus("Download started ✅", "success");
  } catch (e) {
    console.error(e);
    alert(e.message || "Export failed.");
    setStatus("Export failed.", "error");
  } finally {
    setLoading(false);
  }
});

// --- Rendering functions ---
function renderSummary(overall) {
  if (!summaryEl) return;

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
        <span class="summary-value positive">$${Number(inflow).toFixed(2)}</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">Total outflow</span>
        <span class="summary-value negative">$${Math.abs(Number(outflow)).toFixed(2)}</span>
      </div>
      <div class="summary-item">
        <span class="summary-label">Net</span>
        <span class="summary-value ${net >= 0 ? "positive" : "negative"}">
          $${Number(net).toFixed(2)}
        </span>
      </div>
      <div class="summary-item">
        <span class="summary-label">Transactions</span>
        <span class="summary-value">${overall.n_transactions ?? 0}</span>
      </div>
      <div class="summary-item summary-item--span">
        <span class="summary-label">Statement period</span>
        <span class="summary-value">${escapeHtml(period)}</span>
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
  if (!targetEl) return;

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
          <td>${escapeHtml(cat.category)}</td>
          <td>$${Number(total).toFixed(2)}</td>
          <td>${Number(count)}</td>
          <td>${Number(share).toFixed(1)}%</td>
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
        <tbody>${rows}</tbody>
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
  if (!targetEl) return;

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
        <strong>${escapeHtml(sugg.category)}</strong><br />
        <span>${escapeHtml(sugg.message)}</span>
      </li>
    `
    )
    .join("");

  targetEl.innerHTML = `<ul class="suggestions-list">${items}</ul>`;
}

function renderPreview(preview) {
  if (!previewEl) return;

  if (!preview || preview.length === 0) {
    previewEl.innerHTML = "No preview rows available.";
    previewEl.classList.add("empty-state");
    return;
  }

  previewEl.classList.remove("empty-state");

  const columns = ["date", "description", "amount", "category", "direction"].filter((col) =>
    preview.some((row) => row && col in row)
  );

  const headerRow = columns.map((col) => `<th>${escapeHtml(col)}</th>`).join("");

  const bodyRows = preview
    .map((row) => {
      const cells = columns
        .map((col) => {
          let value = row?.[col];

          if (col === "amount" && typeof value === "number") {
            value = `$${value.toFixed(2)}`;
          }
          if (col === "date") {
            value = normalizeDateString(value);
          }
          return `<td>${escapeHtml(value ?? "")}</td>`;
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
  if (!transactionsTableWrapper) return;

  if (!transactions || transactions.length === 0) {
    transactionsTableWrapper.innerHTML = "No transactions loaded yet.";
    transactionsTableWrapper.classList.add("empty-state");
    return;
  }

  transactionsTableWrapper.classList.remove("empty-state");

  const rows = transactions
    .map((tx, idx) => {
      const date = normalizeDateString(tx.date);
      const desc = tx.description ?? "";
      const amount =
        typeof tx.amount === "number" ? tx.amount.toFixed(2) : (tx.amount ?? "");
      const category = tx.category ?? "Uncategorized";
      const direction = tx.direction ?? "unknown";

      return `
        <tr data-index="${idx}">
          <td data-field="date" contenteditable="true">${escapeHtml(date)}</td>
          <td data-field="description" contenteditable="true">${escapeHtml(desc)}</td>
          <td data-field="amount" contenteditable="true">${escapeHtml(amount)}</td>
          <td data-field="category">${escapeHtml(category)}</td>
          <td data-field="direction">${escapeHtml(direction)}</td>
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
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

/**
 * Collect transactions from the editable table.
 * - includeAutoColumns=false -> sends only date/description/amount (good for /api/reanalyze)
 * - includeAutoColumns=true  -> also includes category/direction from the table (good for export)
 */
function collectTransactionsFromTable({ includeAutoColumns } = { includeAutoColumns: false }) {
  const table = document.getElementById("transactions-table");
  if (!table) return [];

  const rows = Array.from(table.querySelectorAll("tbody tr"));
  const result = [];

  rows.forEach((row) => {
    const dateCell = row.querySelector('td[data-field="date"]');
    const descCell = row.querySelector('td[data-field="description"]');
    const amountCell = row.querySelector('td[data-field="amount"]');
    const catCell = row.querySelector('td[data-field="category"]');
    const dirCell = row.querySelector('td[data-field="direction"]');

    const date = normalizeDateString((dateCell?.textContent || "").trim());
    const description = (descCell?.textContent || "").trim();
    const amountStr = (amountCell?.textContent || "").trim();
    const parsedAmount = parseAmount(amountStr);

    // Skip totally empty rows
    const empty = !date && !description && (amountStr === "" || Number.isNaN(parsedAmount));
    if (empty) return;

    const tx = {
      date,
      description,
      amount: Number.isNaN(parsedAmount) ? null : parsedAmount,
    };

    if (includeAutoColumns) {
      tx.category = (catCell?.textContent || "").trim() || "Uncategorized";
      tx.direction = (dirCell?.textContent || "").trim() || "unknown";
    }

    result.push(tx);
  });

  return result;
}
