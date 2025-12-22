// static/app.js
"use strict";

/* -------------------- DOM references -------------------- */
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

// OPTIONAL: if you add a button in index.html with this id, batch save will work
const saveVendorRulesBtn = document.getElementById("save-vendor-rules-btn");

const pageStartInput = document.getElementById("page-start");
const pageEndInput = document.getElementById("page-end");

// Tabs
const tabButtons = document.querySelectorAll(".tab-button");
const tabPanels = document.querySelectorAll(".tab-panel");

/* -------------------- State -------------------- */
let currentTransactions = [];
let currentSummary = null;
let isLoading = false;

const ANALYZE_BTN_DEFAULT_TEXT = analyzeBtn?.textContent || "Analyze spending";

/* -------------------- Business categories (keep aligned with backend taxonomy) -------------------- */
const BUSINESS_CATEGORIES = [
  "Transfers",
  "Sales Income",
  "Refunds & Chargebacks",
  "Interest Income",
  "Other Income",

  "Cost of Goods Sold",
  "Inventory & Supplies",
  "Shipping & Postage",

  "Payroll & Contractors",
  "Rent & Office",
  "Utilities",
  "Software & Subscriptions",
  "Advertising & Marketing",
  "Travel",
  "Meals & Entertainment",
  "Vehicle & Fuel",
  "Professional Services",
  "Insurance",
  "Bank & Fees",
  "Taxes & Licenses",
  "Repairs & Maintenance",
  "Other Operating Expense",

  "Owner Contribution",
  "Owner Draw",

  "Uncategorized",
];

/* -------------------- Utilities -------------------- */
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
  if (saveVendorRulesBtn) saveVendorRulesBtn.disabled = nextLoading;
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
  const t = String(s || "").trim();
  if (!t) return "";
  return t.length >= 10 ? t.slice(0, 10) : t;
}

/* -------------------- Vendor extraction (frontend fallback) -------------------- */
function normalizeTextForVendor(s) {
  let t = String(s || "").trim().toLowerCase();

  // remove common prefixes like "tst*", "sq*", "pp*"
  t = t.replace(/^(tst|sq|pp|clr|bh|dd|gp|py)\*+\s*/i, "");
  t = t.replace(/^(tst|sq|pp|clr|bh)\s+/i, "");

  // remove long numbers
  t = t.replace(/\b\d{2,}\b/g, " ");
  // keep letters/spaces/&/-
  t = t.replace(/[^a-z\s&\-]/g, " ");
  t = t.replace(/\s+/g, " ").trim();
  return t;
}

function extractVendor(description) {
  const t = normalizeTextForVendor(description);

  // very light location stopwords
  const stop = new Set(["new", "york", "ny", "ca", "ct", "nj"]);
  const toks = t.split(" ").filter((x) => x && !stop.has(x));
  return toks.slice(0, 4).join(" ").trim();
}

function categorySelectHtml(selected) {
  const sel = selected || "Uncategorized";
  return `
    <select class="category-select">
      ${BUSINESS_CATEGORIES.map((c) => {
        const s = c === sel ? "selected" : "";
        return `<option value="${escapeHtml(c)}" ${s}>${escapeHtml(c)}</option>`;
      }).join("")}
    </select>
  `;
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

/* -------------------- Tab switching -------------------- */
tabButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    const tab = btn.dataset.tab;

    tabButtons.forEach((b) => b.classList.toggle("tab-button--active", b === btn));
    tabPanels.forEach((panel) => {
      panel.classList.toggle("tab-panel--active", panel.dataset.tab === tab);
    });
  });
});

/* -------------------- Upload & analyze -------------------- */
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
      const data = await fetchJson("/api/analyze", { method: "POST", body: formData });
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

/* -------------------- Vendor map: save helpers -------------------- */
async function saveVendorMapping(vendor, category) {
  const v = String(vendor || "").trim().toLowerCase();
  const c = String(category || "").trim();
  if (!v) throw new Error("Vendor is empty; cannot save mapping.");
  if (!c) throw new Error("Category is empty; cannot save mapping.");

  return fetchJson("/api/vendor-map", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vendor: v, category: c }),
  });
}

function getVendorMapChangesFromTable() {
  // Returns [{ vendor, category, rowEl }]
  const table = document.getElementById("transactions-table");
  if (!table) return [];

  const rows = Array.from(table.querySelectorAll("tbody tr"));
  const changes = [];

  rows.forEach((row) => {
    const vendorCell = row.querySelector('td[data-field="vendor"]');
    const descCell = row.querySelector('td[data-field="description"]');
    const select = row.querySelector("select.category-select");

    if (!select) return;

    const vendorFromCell = (vendorCell?.textContent || "").trim();
    const description = (descCell?.textContent || "").trim();

    const vendor = vendorFromCell || extractVendor(description);
    const selected = select.value;

    const auto = row.getAttribute("data-auto-category") || "";
    const selectedNorm = String(selected || "").trim();
    const autoNorm = String(auto || "").trim();

    // if user changed away from auto category, treat as "mapping to save"
    if (selectedNorm && autoNorm && selectedNorm !== autoNorm) {
      changes.push({ vendor, category: selectedNorm, rowEl: row });
    }
  });

  return changes;
}

/* -------------------- Reanalyze after manual edits -------------------- */
reanalyzeBtn?.addEventListener("click", async () => {
  if (isLoading) return;

  if (!currentTransactions || currentTransactions.length === 0) {
    setStatus("No transactions to re-analyze. Upload a file first.", "error");
    return;
  }

  // 1) Save any vendor-map overrides (so reanalyze uses DB mappings)
  const changes = getVendorMapChangesFromTable();
  if (changes.length > 0) {
    setStatus(`Saving ${changes.length} vendor mapping(s)...`, "loading");
    setLoading(true);

    try {
      await Promise.all(
        changes.map(async (x) => {
          await saveVendorMapping(x.vendor, x.category);
          x.rowEl?.classList?.add("row-saved");
          x.rowEl?.setAttribute("data-auto-category", x.category); // treat as new baseline
        })
      );
      setStatus("Vendor mappings saved ✅ Re-analyzing...", "loading");
    } catch (e) {
      console.error(e);
      setStatus(e.message || "Failed to save vendor mappings.", "error");
      setLoading(false);
      return;
    }
  } else {
    setStatus("Updating analysis based on your edits...", "loading");
    setLoading(true);
  }

  // 2) Send edited transactions (date/desc/amount only)
  const updated = collectTransactionsFromTable({ includeAutoColumns: false });
  if (updated.length === 0) {
    setStatus("No valid transactions in table to re-analyze.", "error");
    setLoading(false);
    return;
  }

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

/* -------------------- Add new transaction row -------------------- */
addTransactionBtn?.addEventListener("click", () => {
  if (isLoading) return;

  const today = new Date().toISOString().slice(0, 10);

  currentTransactions.push({
    date: today,
    description: "",
    amount: 0.0,
    vendor: "",
    category: "Uncategorized",
    direction: "unknown",
    category_confidence: 0.0,
    category_reason: "manual_row",
    needs_review: true,
  });

  renderTransactionsTable(currentTransactions);
});

/* -------------------- Batch save button (optional) -------------------- */
saveVendorRulesBtn?.addEventListener("click", async () => {
  if (isLoading) return;

  const changes = getVendorMapChangesFromTable();
  if (changes.length === 0) {
    alert("No vendor overrides to save. Change a category in the dropdown first.");
    return;
  }

  setStatus(`Saving ${changes.length} vendor mapping(s)...`, "loading");
  setLoading(true);

  try {
    await Promise.all(
      changes.map(async (x) => {
        await saveVendorMapping(x.vendor, x.category);
        x.rowEl?.classList?.add("row-saved");
        x.rowEl?.setAttribute("data-auto-category", x.category);
      })
    );
    setStatus("Vendor mappings saved ✅", "success");
  } catch (e) {
    console.error(e);
    setStatus(e.message || "Failed to save vendor mappings.", "error");
  } finally {
    setLoading(false);
  }
});

/* -------------------- Download CSV -------------------- */
downloadCsvBtn?.addEventListener("click", async () => {
  if (isLoading) return;

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

/* -------------------- Rendering functions (unchanged except transactions table) -------------------- */
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

          if (col === "amount" && typeof value === "number") value = `$${value.toFixed(2)}`;
          if (col === "date") value = normalizeDateString(value);

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

/* -------------------- Transactions table (UPDATED) -------------------- */
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

      const vendor = (tx.vendor && String(tx.vendor).trim()) ? String(tx.vendor).trim() : extractVendor(desc);

      const categoryAuto = tx.category ?? "Uncategorized";
      const direction = tx.direction ?? "unknown";
      const conf = typeof tx.category_confidence === "number" ? tx.category_confidence : 0.0;
      const reason = tx.category_reason ?? "";
      const needsReview = !!tx.needs_review;

      return `
        <tr data-index="${idx}" data-auto-category="${escapeHtml(categoryAuto)}">
          <td data-field="date" contenteditable="true">${escapeHtml(date)}</td>
          <td data-field="description" contenteditable="true">${escapeHtml(desc)}</td>
          <td data-field="amount" contenteditable="true">${escapeHtml(amount)}</td>

          <td data-field="vendor">${escapeHtml(vendor)}</td>

          <td data-field="category">${escapeHtml(categoryAuto)}</td>
          <td data-field="category_override">
            ${categorySelectHtml(categoryAuto)}
          </td>

          <td data-field="confidence">${escapeHtml(conf.toFixed(2))}</td>
          <td data-field="needs_review">${needsReview ? "Yes" : "No"}</td>

          <td data-field="direction">${escapeHtml(direction)}</td>
          <td data-field="reason">${escapeHtml(reason)}</td>

          <td>
            <button type="button" class="table-btn save-vendor-btn">Save vendor</button>
          </td>
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

            <th>Vendor</th>

            <th>Category (auto)</th>
            <th>Set category</th>

            <th>Conf.</th>
            <th>Review?</th>

            <th>Direction</th>
            <th>Reason</th>

            <th>Save</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
      <p class="hint" style="margin-top:0.75rem;">
        Tip: change a category in the dropdown and click <strong>Save vendor</strong> (or click <strong>Update analysis</strong> which will save changes first).
      </p>
    </div>
  `;
}

/* -------------------- Table events: save vendor + keep vendor in sync -------------------- */
transactionsTableWrapper?.addEventListener("click", async (e) => {
  const btn = e.target?.closest?.(".save-vendor-btn");
  if (!btn) return;
  if (isLoading) return;

  const row = btn.closest("tr");
  if (!row) return;

  const vendorCell = row.querySelector('td[data-field="vendor"]');
  const descCell = row.querySelector('td[data-field="description"]');
  const select = row.querySelector("select.category-select");

  const vendorFromCell = (vendorCell?.textContent || "").trim();
  const description = (descCell?.textContent || "").trim();
  const vendor = vendorFromCell || extractVendor(description);

  const category = select?.value || "";

  if (!vendor) {
    alert("Vendor is empty. Add a description first.");
    return;
  }
  if (!category) {
    alert("Pick a category first.");
    return;
  }

  setStatus(`Saving mapping: "${vendor}" → "${category}"...`, "loading");
  setLoading(true);

  try {
    await saveVendorMapping(vendor, category);

    // Update baseline so it won't keep showing as "changed"
    row.setAttribute("data-auto-category", category);

    // Also update auto category cell (visual)
    const autoCatCell = row.querySelector('td[data-field="category"]');
    if (autoCatCell) autoCatCell.textContent = category;

    row.classList.add("row-saved");
    setStatus("Vendor mapping saved ✅ Re-analyze to apply everywhere.", "success");
  } catch (err) {
    console.error(err);
    alert(err.message || "Failed to save vendor mapping.");
    setStatus("Failed to save vendor mapping.", "error");
  } finally {
    setLoading(false);
  }
});

// When user edits description, update vendor cell (on blur)
transactionsTableWrapper?.addEventListener(
  "blur",
  (e) => {
    const cell = e.target;
    if (!cell || cell.getAttribute?.("data-field") !== "description") return;

    const row = cell.closest("tr");
    if (!row) return;

    const desc = (cell.textContent || "").trim();
    const vendorCell = row.querySelector('td[data-field="vendor"]');
    if (vendorCell) vendorCell.textContent = extractVendor(desc);
  },
  true
);

/* -------------------- Collect transactions from table -------------------- */
function collectTransactionsFromTable({ includeAutoColumns } = { includeAutoColumns: false }) {
  const table = document.getElementById("transactions-table");
  if (!table) return [];

  const rows = Array.from(table.querySelectorAll("tbody tr"));
  const result = [];

  rows.forEach((row) => {
    const dateCell = row.querySelector('td[data-field="date"]');
    const descCell = row.querySelector('td[data-field="description"]');
    const amountCell = row.querySelector('td[data-field="amount"]');

    const vendorCell = row.querySelector('td[data-field="vendor"]');
    const catAutoCell = row.querySelector('td[data-field="category"]');
    const dirCell = row.querySelector('td[data-field="direction"]');
    const reasonCell = row.querySelector('td[data-field="reason"]');
    const confCell = row.querySelector('td[data-field="confidence"]');
    const needsReviewCell = row.querySelector('td[data-field="needs_review"]');

    const select = row.querySelector("select.category-select");

    const date = normalizeDateString((dateCell?.textContent || "").trim());
    const description = (descCell?.textContent || "").trim();
    const amountStr = (amountCell?.textContent || "").trim();
    const parsedAmount = parseAmount(amountStr);

    const empty = !date && !description && (amountStr === "" || Number.isNaN(parsedAmount));
    if (empty) return;

    const tx = {
      date,
      description,
      amount: Number.isNaN(parsedAmount) ? null : parsedAmount,
    };

    if (includeAutoColumns) {
      // For export: include what is currently displayed
      tx.vendor = (vendorCell?.textContent || "").trim() || extractVendor(description);

      // If user chose a different category in the dropdown, export that selection
      const selectedCategory = select?.value?.trim();
      tx.category = selectedCategory || (catAutoCell?.textContent || "").trim() || "Uncategorized";

      tx.direction = (dirCell?.textContent || "").trim() || "unknown";
      tx.category_reason = (reasonCell?.textContent || "").trim() || "";
      tx.category_confidence = parseFloat((confCell?.textContent || "").trim()) || 0.0;
      tx.needs_review = ((needsReviewCell?.textContent || "").trim().toLowerCase() === "yes");
    }

    result.push(tx);
  });

  return result;
}
