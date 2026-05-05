const scanForm = document.getElementById('scanForm');
const resultBody = document.getElementById('resultBody');
const resultMeta = document.getElementById('resultMeta');
const errorBox = document.getElementById('errorBox');
const scanBtn = document.getElementById('scanBtn');
const marketCapInput = document.getElementById('marketCapMin');
const DEFAULT_MARKET_CAP = 5000000000;

function parseLocalizedNumber(value) {
  if (value === null || value === undefined) return NaN;
  const normalized = String(value).replace(/\./g, '').replace(/,/g, '.').replace(/\s/g, '');
  return Number(normalized);
}

function formatIntegerTR(value) {
  if (!Number.isFinite(value)) return '';
  return Math.round(value).toLocaleString('tr-TR');
}

function numberOrDash(value, fractionDigits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return '-';
  const num = Number(value);
  if (Number.isNaN(num)) return '-';
  return num.toLocaleString('tr-TR', {
    minimumFractionDigits: 0,
    maximumFractionDigits: fractionDigits,
  });
}

function formatMarketCap(value) {
  if (value === null || value === undefined) return '-';
  return `${numberOrDash(value, 0)} TL`;
}

function buildTradingViewUrl(row) {
  const rawSymbol = row.symbol || '';
  const fallbackTicker = (row.name || '').trim();
  const tvSymbol = rawSymbol || (fallbackTicker ? `BIST:${fallbackTicker}` : '');
  if (!tvSymbol) return null;
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tvSymbol)}`;
}

function rowTemplate(row) {
  const tvUrl = buildTradingViewUrl(row);
  const symbolLabel = row.name ?? row.symbol ?? '-';
  const tvLink = tvUrl
    ? `<a href="${tvUrl}" target="_blank" rel="noopener noreferrer" class="small ms-2">TradingView</a>`
    : '';

  return `
    <tr>
      <td><strong>${symbolLabel}</strong>${tvLink}</td>
      <td>${numberOrDash(row.close)}</td>
      <td>${numberOrDash(row.price_earnings_ttm)}</td>
      <td>${numberOrDash(row.dividend_yield_recent)}%</td>
      <td>${formatMarketCap(row.market_cap_basic)}</td>
      <td>${numberOrDash(row.debt_to_equity)}</td>
      <td>${numberOrDash(row.price_book_ratio)}</td>
      <td>${numberOrDash(row.return_on_equity)}%</td>
      <td>${row.sector ?? '-'}</td>
    </tr>
  `;
}

function setError(message) {
  errorBox.classList.remove('d-none');
  errorBox.textContent = message;
}

function clearError() {
  errorBox.classList.add('d-none');
  errorBox.textContent = '';
}

async function runScan(payload) {
  const response = await fetch('/api/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || 'Istek basarisiz oldu.');
  }

  return data;
}

scanForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  clearError();

  const marketCapRaw = parseLocalizedNumber(marketCapInput.value);

  const payload = {
    pe_max: Number(document.getElementById('peMax').value),
    dividend_min: Number(document.getElementById('dividendMin').value),
    market_cap_min: marketCapRaw,
    limit: Number(document.getElementById('limit').value),
  };

  if (!Number.isFinite(payload.market_cap_min)) {
    setError('Min. Piyasa Degeri alani gecerli bir sayi olmali.');
    return;
  }

  marketCapInput.value = formatIntegerTR(payload.market_cap_min);

  scanBtn.disabled = true;
  scanBtn.textContent = 'Taraniyor...';

  try {
    const result = await runScan(payload);
    const rows = result.rows || [];

    if (!rows.length) {
      resultBody.innerHTML = '<tr><td colspan="9" class="text-center text-secondary py-4">Sonuc bulunamadi.</td></tr>';
    } else {
      resultBody.innerHTML = rows.map(rowTemplate).join('');
    }

    resultMeta.textContent = `Toplam: ${result.totalCount} | Gosterilen: ${result.returnedCount}`;
  } catch (error) {
    resultBody.innerHTML = '<tr><td colspan="9" class="text-center text-secondary py-4">Hata olustu.</td></tr>';
    setError(error.message);
  } finally {
    scanBtn.disabled = false;
    scanBtn.textContent = 'Tara';
  }
});

marketCapInput.addEventListener('focus', () => {
  const value = parseLocalizedNumber(marketCapInput.value);
  if (Number.isFinite(value)) {
    marketCapInput.value = String(Math.round(value));
  }
});

marketCapInput.addEventListener('blur', () => {
  const value = parseLocalizedNumber(marketCapInput.value);
  if (Number.isFinite(value)) {
    marketCapInput.value = formatIntegerTR(value);
  }
});

(() => {
  const value = parseLocalizedNumber(marketCapInput.value);
  const initialValue = Number.isFinite(value) ? value : DEFAULT_MARKET_CAP;
  marketCapInput.value = formatIntegerTR(initialValue);
})();
