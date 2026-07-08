// =============================================================
//  OI Alert System — static/app.js
//  Frontend logic for the control panel
// =============================================================

// ── LIVE CLOCK ───────────────────────────────────────────────
function updateClock() {
    const now = new Date();
    const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
    const h = String(ist.getHours()).padStart(2, "0");
    const m = String(ist.getMinutes()).padStart(2, "0");
    const s = String(ist.getSeconds()).padStart(2, "0");
    document.getElementById("live-time").textContent = `${h}:${m}:${s} IST`;
}

setInterval(updateClock, 1000);
updateClock();


// ── SHOW MESSAGE ─────────────────────────────────────────────
function showMsg(id, text, type = "success") {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = `msg ${type}`;
    setTimeout(() => { el.textContent = ""; el.className = "msg"; }, 4000);
}


// ── TOKEN FUNCTIONS ──────────────────────────────────────────
async function saveToken() {
    const token = document.getElementById("token-input").value.trim();
    const pin = document.getElementById("pin-input").value.trim();

    if (!token) { showMsg("token-msg", "Please paste your token first", "error"); return; }
    if (!pin) { showMsg("token-msg", "Please enter your PIN", "error"); return; }

    showMsg("token-msg", "Saving...", "info");

    try {
        const res = await fetch("/api/update-token", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token, pin })
        });
        const data = await res.json();

        if (data.success) {
            showMsg("token-msg", data.message, "success");
            document.getElementById("masked-token").textContent = data.masked;
            document.getElementById("token-input").value = "";
            document.getElementById("pin-input").value = "";
            refreshStatus();
        } else {
            showMsg("token-msg", data.message, "error");
        }
    } catch (e) {
        showMsg("token-msg", "Network error — try again", "error");
    }
}


async function renewToken() {
    const pin = document.getElementById("pin-input").value.trim();
    if (!pin) { showMsg("token-msg", "Please enter your PIN first", "error"); return; }

    showMsg("token-msg", "Renewing token...", "info");

    try {
        const res = await fetch("/api/renew-token", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ pin })
        });
        const data = await res.json();

        if (data.success) {
            showMsg("token-msg", data.message, "success");
            document.getElementById("masked-token").textContent = data.masked;
            refreshStatus();
        } else {
            showMsg("token-msg", data.message, "error");
        }
    } catch (e) {
        showMsg("token-msg", "Network error — try again", "error");
    }
}


async function validateToken() {
    showMsg("token-msg", "Validating...", "info");

    try {
        const res = await fetch("/api/validate-token");
        const data = await res.json();
        const type = data.valid ? "success" : "error";
        showMsg("token-msg", data.message, type);
    } catch (e) {
        showMsg("token-msg", "Network error", "error");
    }
}


// ── SETTINGS ─────────────────────────────────────────────────
async function saveSettings() {
    const payload = {
        thresholds: {
            oi_3sec_pct: parseInt(document.getElementById("oi-3sec").value),
            oi_day_pct: parseInt(document.getElementById("oi-day").value),
            cooldown_minutes: parseInt(document.getElementById("cooldown").value),
        },
        strike_filter: {
            itm_depth: parseInt(document.getElementById("itm-depth").value),
        }
    };

    try {
        const res = await fetch("/api/save-settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        showMsg("settings-msg", data.message, data.success ? "success" : "error");
    } catch (e) {
        showMsg("settings-msg", "Network error", "error");
    }
}


// ── UNDERLYINGS ──────────────────────────────────────────────
async function saveUnderlyings() {
    const checkboxes = document.querySelectorAll("input[name='underlying']:checked");
    const selected = Array.from(checkboxes).map(c => c.value);

    if (selected.length === 0) {
        showMsg("underlying-msg", "Select at least one underlying", "error");
        return;
    }

    try {
        const res = await fetch("/api/save-settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ underlyings: selected })
        });
        const data = await res.json();
        showMsg("underlying-msg", data.message, data.success ? "success" : "error");
    } catch (e) {
        showMsg("underlying-msg", "Network error", "error");
    }
}


// ── EXPIRIES ─────────────────────────────────────────────────
let fetchedExpiries = {};

async function loadExpiries() {
    const checkboxes = document.querySelectorAll("input[name='underlying']:checked");
    const selected = Array.from(checkboxes).map(c => c.value);
    const container = document.getElementById("expiry-container");

    if (selected.length === 0) {
        container.innerHTML = "<p class='muted'>Select underlyings first</p>";
        return;
    }

    container.innerHTML = "<p class='muted'>Loading expiries from Dhan...</p>";
    fetchedExpiries = {};

    let html = "";

    for (const name of selected) {
        try {
            const res = await fetch(`/api/get-expiries/${name}`);
            const data = await res.json();

            if (data.success && data.expiries.length > 0) {
                fetchedExpiries[name] = data.expiries;
                const options = data.expiries
                    .slice(0, 4)
                    .map(e => `<option value="${e}">${e}</option>`)
                    .join("");

                html += `
                    <div class="expiry-row">
                        <label>${name}</label>
                        <select id="expiry-${name}">${options}</select>
                    </div>
                `;
            } else {
                html += `<div class="expiry-row"><label>${name}</label><span class='muted'>No expiries found</span></div>`;
            }
        } catch (e) {
            html += `<div class="expiry-row"><label>${name}</label><span class='muted'>Failed to load</span></div>`;
        }
    }

    container.innerHTML = html || "<p class='muted'>No expiries found</p>";
}


async function saveExpiries() {
    const checkboxes = document.querySelectorAll("input[name='underlying']:checked");
    const selected = Array.from(checkboxes).map(c => c.value);
    const payload = {};

    for (const name of selected) {
        const sel = document.getElementById(`expiry-${name}`);
        if (sel) {
            payload[name] = [sel.value];
        }
    }

    if (Object.keys(payload).length === 0) {
        showMsg("expiry-msg", "Load expiries first", "error");
        return;
    }

    try {
        const res = await fetch("/api/save-expiries", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        showMsg("expiry-msg", data.message, data.success ? "success" : "error");
    } catch (e) {
        showMsg("expiry-msg", "Network error", "error");
    }
}


// ── STATUS REFRESH ───────────────────────────────────────────
async function refreshStatus() {
    try {
        const res = await fetch("/api/status");
        const data = await res.json();

        // Monitor status
        document.getElementById("monitor-status").innerHTML = data.monitor_running
            ? `<span class='dot green'></span> Running`
            : `<span class='dot red'></span> Stopped`;

        // Market status
        const mDot = data.market_status === "open" ? "green" : "red";
        document.getElementById("market-status").innerHTML =
            `<span class='dot ${mDot}'></span> ${data.market_msg}`;

        // Token status
        document.getElementById("token-status").innerHTML = data.token_valid
            ? `<span class='dot green'></span> Valid`
            : `<span class='dot red'></span> Expired`;

        // Alert count
        document.getElementById("alert-count").textContent = data.alert_count;
        document.getElementById("alert-badge").textContent = data.alert_count;

        // Last updated
        const lu = document.getElementById("last-updated");
        if (lu) lu.textContent = data.last_token_update;

    } catch (e) {
        console.log("Status refresh failed:", e);
    }
}


// ── ALERTS TABLE REFRESH ─────────────────────────────────────
async function refreshAlerts() {
    try {
        const res = await fetch("/api/alerts");
        const data = await res.json();

        if (!data.success || data.alerts.length === 0) return;

        const tbody = document.getElementById("alerts-tbody");
        const noMsg = document.getElementById("no-alerts-msg");

        if (!tbody) return;

        if (noMsg) noMsg.style.display = "none";

        tbody.innerHTML = data.alerts.map(a => `
            <tr>
                <td>${a.Time}</td>
                <td><strong>${a.Strike}</strong></td>
                <td><span class="badge-type ${a.Type.toLowerCase()}">${a.Type}</span></td>
                <td>${a.Label}</td>
                <td class="chg up">+${a['OI Chg 3sec %']}%</td>
                <td class="chg up">+${a['OI Chg Day %']}%</td>
                <td>₹${a.LTP}</td>
            </tr>
        `).join("");

    } catch (e) {
        console.log("Alerts refresh failed:", e);
    }
}


// ── AUTO REFRESH ─────────────────────────────────────────────
// Refresh status every 10 seconds
setInterval(refreshStatus, 10000);

// Refresh alerts table every 15 seconds
setInterval(refreshAlerts, 15000);


async function refreshSnapshot() {
    try {
        const res  = await fetch("/api/market-snapshot");
        const data = await res.json();

        if (!data.success) return;

        const snapshots   = data.snapshots;
        const keys        = Object.keys(snapshots);
        if (keys.length === 0) return;

        const container = document.getElementById("snapshot-container");
        if (!container) return;

        let html = "";

        for (const key of keys) {
            const s  = snapshots[key];
            const tg = s.top_gamma  || {};
            const tv = s.top_volume || {};

            // update time
            const timeEl = document.getElementById("snapshot-time");
            if (timeEl) timeEl.textContent = `as of ${s.time}`;

            html += `
                <div style="margin-bottom:14px">
                    <div style="font-size:12px; color:#718096; margin-bottom:8px">
                        ${s.underlying} | Spot: ${s.spot_price}
                    </div>

                    <table class="strike-table">
                        <tr>
                            <td>Highest Gamma</td>
                            <td>
                                <strong>${tg.strike} ${tg.option_type}</strong>
                                &nbsp;|&nbsp; γ ${tg.gamma?.toFixed(4)}
                                &nbsp;|&nbsp; ₹${tg.ltp}
                            </td>
                        </tr>
                        <tr>
                            <td>Highest Volume</td>
                            <td>
                                <strong>${tv.strike} ${tv.option_type}</strong>
                                &nbsp;|&nbsp; Vol: ${tv.volume?.toLocaleString()}
                                &nbsp;|&nbsp; ₹${tv.ltp}
                            </td>
                        </tr>
                    </table>

                    <div style="margin-top:10px; font-size:11px; color:#718096">
                        TOP 3 BY VOLUME
                    </div>
                    <table class="strike-table">
                        ${(s.top3_volume || []).map((v, i) => `
                        <tr>
                            <td>${i + 1}. ${v.strike} ${v.option_type}</td>
                            <td>${v.volume?.toLocaleString()} vol &nbsp;|&nbsp; ₹${v.ltp}</td>
                        </tr>`).join("")}
                    </table>

                    <div style="margin-top:10px; font-size:11px; color:#718096">
                        TOP 3 BY OI
                    </div>
                    <table class="strike-table">
                        ${(s.top3_oi || []).map((v, i) => `
                        <tr>
                            <td>${i + 1}. ${v.strike} ${v.option_type}</td>
                            <td>${v.oi?.toLocaleString()} OI &nbsp;|&nbsp; ₹${v.ltp}</td>
                        </tr>`).join("")}
                    </table>
                </div>
            `;
        }

        container.innerHTML = html;

    } catch (e) {
        console.log("Snapshot refresh failed:", e);
    }
}

// Add to auto refresh
setInterval(refreshSnapshot, 30000);
refreshSnapshot();