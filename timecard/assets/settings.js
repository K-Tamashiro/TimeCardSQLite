(function () {
    'use strict';

    const header = document.querySelector('header');
    function syncHeaderHeight() {
        if (header) {
            document.documentElement.style.setProperty('--header-height', header.offsetHeight + 'px');
        }
    }
    syncHeaderHeight();
    window.addEventListener('resize', syncHeaderHeight);
    if (header && typeof ResizeObserver === 'function') {
        new ResizeObserver(syncHeaderHeight).observe(header);
    }

    const dataEl = document.getElementById('settings-data');
    if (!dataEl) return;
    let state;
    try {
        state = JSON.parse(dataEl.textContent || '{}');
    } catch (e) {
        return;
    }

    const WEEKDAYS_JA = ['日', '月', '火', '水', '木', '金', '土'];
    const ABSENCE_KEYWORDS = ['【欠勤】', '【休み】', '【病欠】', '【私用】'];

    function isAbsenceLabel(label) {
        const text = String(label || '');
        return ABSENCE_KEYWORDS.some(function (kw) { return text.indexOf(kw) !== -1; });
    }

    // =========================================================
    // 1. Invoice Sequence Live Preview (Sysadmin)
    // =========================================================
    const invBaseMonth = document.getElementById('invoice-base-month');
    const invBaseNum = document.getElementById('invoice-base-number');
    const invPreview = document.getElementById('invoice-seq-preview');

    function ymToNum(ym) {
        const m = /^(\d{4})-(\d{2})$/.exec(ym || '');
        if (!m) return null;
        return parseInt(m[1], 10) * 12 + parseInt(m[2], 10) - 1;
    }

    function updateInvoicePreview() {
        if (!invBaseMonth || !invBaseNum || !invPreview) return;
        const baseYm = invBaseMonth.value;
        const baseN = parseInt(invBaseNum.value, 10);
        const curYm = state.current_month || '';
        const bIdx = ymToNum(baseYm);
        const cIdx = ymToNum(curYm);
        if (bIdx === null || isNaN(baseN)) {
            invPreview.textContent = '';
            return;
        }
        const nextN = baseN + 1;
        const nextYmNum = bIdx + 1;
        const ny = Math.floor(nextYmNum / 12);
        const nm = (nextYmNum % 12) + 1;
        let text = baseYm.replace('-', '/') + ' = No.' + baseN + ' → ' + ny + '/' + String(nm).padStart(2, '0') + ' = No.' + nextN;
        if (cIdx !== null && cIdx !== bIdx) {
            text += '（' + curYm.replace('-', '/') + ' = No.' + Math.max(1, baseN + (cIdx - bIdx)) + '）';
        }
        invPreview.textContent = text;
    }

    if (invBaseMonth && invBaseNum) {
        invBaseMonth.addEventListener('change', updateInvoicePreview);
        invBaseNum.addEventListener('input', updateInvoicePreview);
        updateInvoicePreview();
    }

    // =========================================================
    // 2. Contract History Form & Click-to-Edit Table (Sysadmin)
    // =========================================================
    const contractForm = document.getElementById('contract-form');
    const contractModeBadge = document.getElementById('contract-form-mode');
    const contractSubmitBtn = document.getElementById('contract-submit-btn');
    const contractCancelBtn = document.getElementById('contract-cancel-btn');
    const contractResetBtn = document.getElementById('contract-reset-btn');
    const calcRatesBtn = document.getElementById('calc-rates-btn');
    const contractMap = {};
    (state.contracts || []).forEach(function (c) {
        contractMap[c.id] = c;
    });

    let manualDeduct = false;
    let manualExtra = false;

    function floor10(v) {
        return Math.floor(v / 10) * 10;
    }

    function autoCalculateRates(force) {
        if (!contractForm) return;
        const fee = parseFloat(contractForm.elements.contract_fee.value);
        const lower = parseFloat(contractForm.elements.contract_lower.value);
        const upper = parseFloat(contractForm.elements.contract_upper.value);
        const deductField = contractForm.elements.contract_deduct_rate;
        const extraField = contractForm.elements.contract_extra_rate;
        if (!isNaN(fee) && fee > 0 && !isNaN(lower) && lower > 0 && (force || !manualDeduct)) {
            deductField.value = String(floor10(fee / lower));
        }
        if (!isNaN(fee) && fee > 0 && !isNaN(upper) && upper > 0 && (force || !manualExtra)) {
            extraField.value = String(floor10(fee / upper));
        }
    }

    function setSelectedContractRow(cid) {
        document.querySelectorAll('#contract-table tbody tr[data-contract-id]').forEach(function (tr) {
            tr.classList.toggle('is-selected', Boolean(cid && tr.dataset.contractId === cid));
        });
    }

    function hhmmToMin(str) {
        const m = /^(\d{1,2}):(\d{2})$/.exec((str || '').trim());
        if (!m) return null;
        return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
    }

    function updateBreakDuration(idx) {
        if (!contractForm) return;
        const sEl = contractForm.elements['contract_break' + idx + '_start'];
        const eEl = contractForm.elements['contract_break' + idx + '_end'];
        const badge = document.getElementById('break' + idx + '-duration');
        if (!sEl || !eEl || !badge) return;
        const sv = sEl.value.trim();
        const ev = eEl.value.trim();
        if (!sv && !ev) {
            badge.textContent = 'なし';
            badge.classList.add('is-empty');
            return;
        }
        const sm = hhmmToMin(sv);
        const em = hhmmToMin(ev);
        if (sm !== null && em !== null && em > sm) {
            badge.textContent = (em - sm) + '分';
            badge.classList.remove('is-empty');
        } else {
            badge.textContent = '時刻を確認';
            badge.classList.add('is-empty');
        }
    }

    function updateAllBreakDurations() {
        updateBreakDuration(1);
        updateBreakDuration(2);
    }

    function setSubtotalLayoutValue(layoutVal) {
        if (!contractForm) return;
        const val = layoutVal === 'bottom' ? 'bottom' : 'split';
        contractForm.querySelectorAll('input[name="contract_subtotal_layout"]').forEach(function (radio) {
            radio.checked = radio.value === val;
        });
    }

    function syncSubtotalLayoutState() {
        if (!contractForm) return;
        const hsubCb = contractForm.elements.contract_show_half_subtotals;
        const enabled = Boolean(hsubCb && hsubCb.checked);
        const box = document.getElementById('subtotal-layout-options');
        if (box) box.classList.toggle('is-disabled', !enabled);
        contractForm.querySelectorAll('input[name="contract_subtotal_layout"]').forEach(function (radio) {
            radio.disabled = !enabled;
        });
    }

    function resetContractForm() {
        if (!contractForm) return;
        contractForm.reset();
        contractForm.elements.contract_id.value = '';
        contractForm.elements.contract_tax.value = '10';
        contractForm.elements.contract_closing.value = '末';
        if (contractForm.elements.contract_pay_month_offset) contractForm.elements.contract_pay_month_offset.value = '2';
        if (contractForm.elements.contract_pay_day) contractForm.elements.contract_pay_day.value = '15';
        if (contractForm.elements.contract_pay_holiday_rule) contractForm.elements.contract_pay_holiday_rule.value = 'next';
        if (contractForm.elements.contract_regular_start) contractForm.elements.contract_regular_start.value = '08:30';
        if (contractForm.elements.contract_regular_end) contractForm.elements.contract_regular_end.value = '17:30';
        if (contractForm.elements.contract_round_unit) contractForm.elements.contract_round_unit.value = '15';
        if (contractForm.elements.contract_break1_start) contractForm.elements.contract_break1_start.value = '11:45';
        if (contractForm.elements.contract_break1_end) contractForm.elements.contract_break1_end.value = '12:45';
        if (contractForm.elements.contract_break2_start) contractForm.elements.contract_break2_start.value = '17:30';
        if (contractForm.elements.contract_break2_end) contractForm.elements.contract_break2_end.value = '17:40';
        for (let d = 0; d < 7; d++) {
            const cb = contractForm.elements['workday_' + d];
            if (cb) cb.checked = d < 5;
        }
        const holCb = contractForm.elements.workday_holiday;
        if (holCb) holCb.checked = false;
        const hsubCb = contractForm.elements.contract_show_half_subtotals;
        if (hsubCb) hsubCb.checked = false;
        setSubtotalLayoutValue('split');
        syncSubtotalLayoutState();
        manualDeduct = false;
        manualExtra = false;
        if (contractModeBadge) {
            contractModeBadge.textContent = '新規契約の登録';
            contractModeBadge.classList.remove('is-editing');
        }
        if (contractSubmitBtn) {
            const label = contractSubmitBtn.querySelector('span');
            if (label) label.textContent = '契約を登録';
        }
        if (contractCancelBtn) contractCancelBtn.hidden = true;
        setSelectedContractRow('');
        updateAllBreakDurations();
    }

    function loadContractIntoForm(cid) {
        const c = contractMap[cid];
        if (!c || !contractForm) return;
        contractForm.elements.contract_id.value = c.id || '';
        contractForm.elements.contract_name.value = c.name || '';
        contractForm.elements.contract_display_title.value = c.display_title || '';
        contractForm.elements.contract_customer.value = c.customer || '';
        contractForm.elements.contract_start_date.value = c.start_date || '';
        contractForm.elements.contract_end_date.value = c.end_date || '';
        contractForm.elements.contract_closing.value = c.closing || '末';
        if (contractForm.elements.contract_pay_month_offset) {
            contractForm.elements.contract_pay_month_offset.value = c.pay_month_offset != null ? String(c.pay_month_offset) : '2';
        }
        if (contractForm.elements.contract_pay_day) {
            contractForm.elements.contract_pay_day.value = c.pay_day || '15';
        }
        if (contractForm.elements.contract_pay_holiday_rule) {
            contractForm.elements.contract_pay_holiday_rule.value = c.pay_holiday_rule || 'next';
        }
        contractForm.elements.contract_tax.value = c.tax !== '' && c.tax != null ? c.tax : '10';
        contractForm.elements.contract_fee.value = c.fee || '';
        contractForm.elements.contract_lower.value = c.lower || '';
        contractForm.elements.contract_upper.value = c.upper || '';
        contractForm.elements.contract_deduct_rate.value = c.deduct_rate || '';
        contractForm.elements.contract_extra_rate.value = c.extra_rate || '';
        if (contractForm.elements.contract_regular_start) contractForm.elements.contract_regular_start.value = c.regular_start || '08:30';
        if (contractForm.elements.contract_regular_end) contractForm.elements.contract_regular_end.value = c.regular_end || '17:30';
        if (contractForm.elements.contract_round_unit) contractForm.elements.contract_round_unit.value = c.round_unit != null ? String(c.round_unit) : '15';
        if (contractForm.elements.contract_break1_start) contractForm.elements.contract_break1_start.value = c.break1_start != null ? c.break1_start : '11:45';
        if (contractForm.elements.contract_break1_end) contractForm.elements.contract_break1_end.value = c.break1_end != null ? c.break1_end : '12:45';
        if (contractForm.elements.contract_break2_start) contractForm.elements.contract_break2_start.value = c.break2_start != null ? c.break2_start : '17:30';
        if (contractForm.elements.contract_break2_end) contractForm.elements.contract_break2_end.value = c.break2_end != null ? c.break2_end : '17:40';
        const wdays = new Set(Array.isArray(c.workdays) ? c.workdays : [0, 1, 2, 3, 4]);
        for (let d = 0; d < 7; d++) {
            const cb = contractForm.elements['workday_' + d];
            if (cb) cb.checked = wdays.has(d);
        }
        const holCb = contractForm.elements.workday_holiday;
        if (holCb) holCb.checked = Boolean(c.work_on_holiday);
        const hsubCb = contractForm.elements.contract_show_half_subtotals;
        if (hsubCb) hsubCb.checked = Boolean(c.show_half_subtotals);
        setSubtotalLayoutValue(c.subtotal_layout || 'split');
        syncSubtotalLayoutState();
        manualDeduct = true;
        manualExtra = true;
        if (contractModeBadge) {
            contractModeBadge.textContent = '編集中：' + c.name;
            contractModeBadge.classList.add('is-editing');
        }
        if (contractSubmitBtn) {
            const label = contractSubmitBtn.querySelector('span');
            if (label) label.textContent = '契約を更新';
        }
        if (contractCancelBtn) contractCancelBtn.hidden = false;
        setSelectedContractRow(cid);
        updateAllBreakDurations();
        contractForm.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    if (contractForm) {
        [1, 2].forEach(function (idx) {
            ['start', 'end'].forEach(function (side) {
                const el = contractForm.elements['contract_break' + idx + '_' + side];
                if (el) {
                    el.addEventListener('input', function () { updateBreakDuration(idx); });
                    el.addEventListener('change', function () { updateBreakDuration(idx); });
                }
            });
        });
        contractForm.querySelectorAll('[data-clear-break]').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const idx = btn.dataset.clearBreak;
                const sEl = contractForm.elements['contract_break' + idx + '_start'];
                const eEl = contractForm.elements['contract_break' + idx + '_end'];
                if (sEl) sEl.value = '';
                if (eEl) eEl.value = '';
                updateBreakDuration(idx);
            });
        });
        updateAllBreakDurations();
        syncSubtotalLayoutState();
        const hsubCbInit = contractForm.elements.contract_show_half_subtotals;
        if (hsubCbInit) {
            hsubCbInit.addEventListener('change', syncSubtotalLayoutState);
        }
        ['contract_fee', 'contract_lower', 'contract_upper'].forEach(function (name) {
            const el = contractForm.elements[name];
            if (el) {
                el.addEventListener('input', function () {
                    if (!contractForm.elements.contract_id.value) autoCalculateRates(false);
                });
            }
        });
        contractForm.elements.contract_deduct_rate.addEventListener('input', function () {
            manualDeduct = contractForm.elements.contract_deduct_rate.value.trim() !== '';
        });
        contractForm.elements.contract_extra_rate.addEventListener('input', function () {
            manualExtra = contractForm.elements.contract_extra_rate.value.trim() !== '';
        });
        if (calcRatesBtn) {
            calcRatesBtn.addEventListener('click', function () {
                manualDeduct = false;
                manualExtra = false;
                autoCalculateRates(true);
            });
        }
        if (contractResetBtn) contractResetBtn.addEventListener('click', resetContractForm);
        if (contractCancelBtn) contractCancelBtn.addEventListener('click', resetContractForm);
    }

    document.querySelectorAll('#contract-table tbody tr[data-contract-id]').forEach(function (tr) {
        tr.addEventListener('click', function (event) {
            if (event.target.closest('form, button, a')) return;
            loadContractIntoForm(tr.dataset.contractId);
        });
    });

    // =========================================================
    // 3. Role-Scoped Annual Holiday & Event Calendar
    // =========================================================
    const canEditHolidays = Boolean(state.can_edit_holidays);
    const canEditPublicEvents = Boolean(state.can_edit_public_events);

    const calContainer = document.getElementById('annual-calendar');
    const calContractSelect = document.getElementById('cal-contract-select');
    const calFiscalMonth = document.getElementById('cal-fiscal-month');
    const calFiscalDay = document.getElementById('cal-fiscal-day');
    const calFiscalSaveBtn = document.getElementById('cal-fiscal-save');
    const calPrevBtn = document.getElementById('cal-prev-fy');
    const calNextBtn = document.getElementById('cal-next-fy');
    const calFyTitle = document.getElementById('cal-fy-title');
    const calStats = document.getElementById('cal-stats');
    const calCopySource = document.getElementById('cal-copy-source');
    const calCopyBtn = document.getElementById('cal-copy-btn');
    const calClearBtn = document.getElementById('cal-clear-btn');
    const calSyncBar = document.getElementById('cal-sync-bar');
    const calSyncSame = document.getElementById('cal-sync-same');
    const calSyncLabel = document.getElementById('cal-sync-label');

    const holidayForm = document.getElementById('holiday-form');
    const holidayDayInput = document.getElementById('holiday-day-input');
    const holidayNameInput = document.getElementById('holiday-name-input');
    const holidayDeleteBtn = document.getElementById('holiday-delete-btn');
    const eventForm = document.getElementById('event-form');
    const eventScopeInput = document.getElementById('event-scope-input');
    const eventDayInput = document.getElementById('event-day-input');
    const eventTextInput = document.getElementById('event-text-input');
    const eventDeleteBtn = document.getElementById('event-delete-btn');
    const editorTabs = document.querySelectorAll('[data-editor-tab]');
    const holidaySelectedMeta = document.getElementById('holiday-selected-meta');
    const holidayStatus = document.getElementById('holiday-status');
    const holidayList = document.getElementById('holiday-list');
    const holidayListCount = document.getElementById('holiday-list-count');
    const holidayOtherNote = document.getElementById('holiday-other-note');
    const eventList = document.getElementById('event-list');
    const eventListCount = document.getElementById('event-list-count');
    const eventOtherNote = document.getElementById('event-other-note');

    let calData = state.initial_calendar || null;
    let selectedDate = '';
    let activeEditorTab = canEditHolidays ? 'holiday' : 'event';
    const pendingHolidayDays = new Set();

    function syncHolidayChipHighlight() {
        const cur = holidayNameInput ? holidayNameInput.value.trim() : '';
        document.querySelectorAll('[data-holiday-preset]').forEach(function (chip) {
            const active = Boolean(cur) && chip.dataset.holidayPreset === cur;
            chip.classList.toggle('is-active', active);
            chip.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
    }

    function setActiveEditorTab(tab) {
        if (!canEditHolidays) tab = 'event';
        activeEditorTab = tab === 'event' ? 'event' : 'holiday';
        editorTabs.forEach(function (btn) {
            const active = btn.dataset.editorTab === activeEditorTab;
            btn.classList.toggle('is-active', active);
            btn.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        if (holidayForm) holidayForm.hidden = activeEditorTab !== 'holiday';
        if (eventForm) eventForm.hidden = activeEditorTab !== 'event';
        if (!selectedDate && holidaySelectedMeta) {
            holidaySelectedMeta.textContent = (canEditHolidays && activeEditorTab === 'holiday')
                ? '先に休日名を選択・入力して日付をクリックすると即登録されます（再クリックで解除）'
                : 'カレンダーの日付をクリックして選択してください';
        }
    }

    function parseIso(iso) {
        const parts = (iso || '').split('-').map(Number);
        return new Date(parts[0], parts[1] - 1, parts[2]);
    }

    function formatIso(d) {
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }

    function pyWeekday(d) {
        return (d.getDay() + 6) % 7;
    }

    function setStatus(msg, isError) {
        if (!holidayStatus) return;
        holidayStatus.textContent = msg || '';
        holidayStatus.classList.toggle('is-error', Boolean(isError));
    }

    function currentEventScope() {
        if (!canEditPublicEvents) return 'private';
        return eventScopeInput && eventScopeInput.value === 'public' ? 'public' : 'private';
    }

    function syncEventInputForSelected() {
        if (!calData || !eventTextInput) return;
        const scope = currentEventScope();
        const map = scope === 'public' ? (calData.public_events || {}) : (calData.private_events || {});
        const existing = selectedDate ? (map[selectedDate] || '') : '';
        eventTextInput.value = existing;
        if (eventDeleteBtn) eventDeleteBtn.disabled = !existing;
    }

    function updateSelectedPanel(iso, syncHolidayName) {
        selectedDate = iso || '';
        if (holidayDayInput) holidayDayInput.value = selectedDate;
        if (eventDayInput) eventDayInput.value = selectedDate;
        if (!calData || !selectedDate) {
            if (holidaySelectedMeta) {
                holidaySelectedMeta.textContent = (canEditHolidays && activeEditorTab === 'holiday')
                    ? '先に休日名を選択・入力して日付をクリックすると即登録されます（再クリックで解除）'
                    : 'カレンダーの日付をクリックして選択してください';
            }
            if (holidayDeleteBtn) holidayDeleteBtn.disabled = true;
            if (eventTextInput) eventTextInput.value = '';
            if (eventDeleteBtn) eventDeleteBtn.disabled = true;
            return;
        }
        const d = parseIso(selectedDate);
        const w = WEEKDAYS_JA[d.getDay()];
        const officialName = (calData.official_holidays || {})[selectedDate] || '';
        const officeName = (calData.office_holidays || {})[selectedDate] || '';
        const pubEv = (calData.public_events || {})[selectedDate] || '';
        const privEv = (calData.private_events || {})[selectedDate] || '';
        const parts = [selectedDate + '（' + w + '）'];
        if (officialName) parts.push('祝日：' + officialName);
        if (officeName) parts.push((isAbsenceLabel(officeName) ? '欠勤扱い：' : '事業所休日：') + officeName);
        if (pubEv) parts.push('全体予定：' + pubEv);
        if (privEv) parts.push('個人予定：' + privEv);
        if (holidaySelectedMeta) holidaySelectedMeta.textContent = parts.join(' ／ ');
        if (syncHolidayName && holidayNameInput) {
            holidayNameInput.value = officeName;
            syncHolidayChipHighlight();
        }
        if (holidayDeleteBtn) holidayDeleteBtn.disabled = !officeName;
        syncEventInputForSelected();

        if (calContainer) {
            calContainer.querySelectorAll('.cal-day.is-selected').forEach(function (el) {
                el.classList.remove('is-selected');
            });
            const btn = calContainer.querySelector('.cal-day[data-date="' + selectedDate + '"]');
            if (btn) btn.classList.add('is-selected');
        }
        [holidayList, eventList].forEach(function (listEl) {
            if (!listEl) return;
            listEl.querySelectorAll('li[data-date]').forEach(function (li) {
                li.classList.toggle('is-selected', li.dataset.date === selectedDate);
            });
        });
    }

    async function handleCalendarDateClick(iso) {
        if (!canEditHolidays || activeEditorTab === 'event') {
            updateSelectedPanel(iso, false);
            if (eventTextInput) eventTextInput.focus();
            return;
        }
        updateSelectedPanel(iso, false);
        if (pendingHolidayDays.has(iso)) return;
        const existingOffice = ((calData && calData.office_holidays) || {})[iso] || '';
        const activeName = holidayNameInput ? holidayNameInput.value.trim() : '';

        if (existingOffice) {
            await saveHoliday(iso, '', { existingLabel: existingOffice });
            return;
        }
        if (activeName) {
            await saveHoliday(iso, activeName);
            return;
        }
        const officialName = ((calData && calData.official_holidays) || {})[iso] || '';
        if (!officialName) {
            setStatus('先に右パネルで休日名を選択（または入力）してから日付をクリックしてください。', false);
        } else {
            setStatus('', false);
        }
        if (holidayNameInput) holidayNameInput.focus();
    }

    function renderHolidayList() {
        if (!holidayList || !calData) return;
        const office = calData.office_holidays || {};
        const fyStart = calData.fy_start;
        const fyEnd = calData.fy_end;
        const allDays = Object.keys(office).sort();
        const inRange = allDays.filter(function (d) { return d >= fyStart && d <= fyEnd; });
        const outRange = allDays.length - inRange.length;

        if (holidayListCount) holidayListCount.textContent = inRange.length + '件';
        holidayList.replaceChildren();
        if (!inRange.length) {
            const empty = document.createElement('li');
            empty.className = 'muted small holiday-list-empty';
            empty.textContent = 'この年度の事業所指定休日は登録されていません。';
            holidayList.appendChild(empty);
        } else {
            inRange.forEach(function (iso) {
                const d = parseIso(iso);
                const li = document.createElement('li');
                li.dataset.date = iso;
                if (iso === selectedDate) li.classList.add('is-selected');
                const selectBtn = document.createElement('button');
                selectBtn.type = 'button';
                selectBtn.className = 'holiday-item-select';
                const dateSpan = document.createElement('span');
                dateSpan.className = 'holiday-item-date' + (isAbsenceLabel(office[iso]) ? ' is-absence' : '');
                dateSpan.textContent = iso + '（' + WEEKDAYS_JA[d.getDay()] + '）';
                const lblSpan = document.createElement('span');
                lblSpan.className = 'holiday-item-label';
                lblSpan.textContent = office[iso];
                selectBtn.appendChild(dateSpan);
                selectBtn.appendChild(lblSpan);
                selectBtn.addEventListener('click', function () {
                    setActiveEditorTab('holiday');
                    updateSelectedPanel(iso, true);
                });
                const delBtn = document.createElement('button');
                delBtn.type = 'button';
                delBtn.className = 'holiday-item-del';
                delBtn.title = '削除';
                delBtn.textContent = '×';
                delBtn.addEventListener('click', function () {
                    saveHoliday(iso, '');
                });
                li.appendChild(selectBtn);
                li.appendChild(delBtn);
                holidayList.appendChild(li);
            });
        }
        if (holidayOtherNote) {
            holidayOtherNote.textContent = outRange > 0 ? '※他年度に ' + outRange + '件の事業所指定休日があります。' : '';
        }
    }

    function renderEventList() {
        if (!eventList || !calData) return;
        const pub = calData.public_events || {};
        const priv = calData.private_events || {};
        const fyStart = calData.fy_start;
        const fyEnd = calData.fy_end;
        const items = [];
        Object.keys(pub).forEach(function (d) {
            items.push({ day: d, scope: 'public', text: pub[d] });
        });
        Object.keys(priv).forEach(function (d) {
            items.push({ day: d, scope: 'private', text: priv[d] });
        });
        items.sort(function (a, b) {
            return a.day < b.day ? -1 : a.day > b.day ? 1 : (a.scope === 'public' ? -1 : 1);
        });

        const inRange = items.filter(function (it) { return it.day >= fyStart && it.day <= fyEnd; });
        const outRange = items.length - inRange.length;

        if (eventListCount) eventListCount.textContent = inRange.length + '件';
        eventList.replaceChildren();
        if (!inRange.length) {
            const empty = document.createElement('li');
            empty.className = 'muted small holiday-list-empty';
            empty.textContent = 'この年度の予定は登録されていません。';
            eventList.appendChild(empty);
        } else {
            inRange.forEach(function (it) {
                const d = parseIso(it.day);
                const li = document.createElement('li');
                li.dataset.date = it.day;
                if (it.day === selectedDate) li.classList.add('is-selected');
                const selectBtn = document.createElement('button');
                selectBtn.type = 'button';
                selectBtn.className = 'holiday-item-select';
                const dateSpan = document.createElement('span');
                dateSpan.className = 'event-item-date';
                dateSpan.textContent = (it.scope === 'public' ? '[全体] ' : '[個人] ') + it.day + '（' + WEEKDAYS_JA[d.getDay()] + '）';
                if (it.scope === 'public') dateSpan.classList.add('is-public');
                const lblSpan = document.createElement('span');
                lblSpan.className = 'holiday-item-label';
                lblSpan.textContent = it.text;
                selectBtn.appendChild(dateSpan);
                selectBtn.appendChild(lblSpan);
                selectBtn.addEventListener('click', function () {
                    setActiveEditorTab('event');
                    if (eventScopeInput && canEditPublicEvents) {
                        eventScopeInput.value = it.scope;
                    }
                    updateSelectedPanel(it.day);
                    if (eventTextInput) eventTextInput.focus();
                });
                li.appendChild(selectBtn);

                const canDeleteThis = it.scope === 'private' || canEditPublicEvents;
                if (canDeleteThis) {
                    const delBtn = document.createElement('button');
                    delBtn.type = 'button';
                    delBtn.className = 'holiday-item-del';
                    delBtn.title = '削除';
                    delBtn.textContent = '×';
                    delBtn.addEventListener('click', function () {
                        saveEvent(it.day, '', it.scope);
                    });
                    li.appendChild(delBtn);
                }
                eventList.appendChild(li);
            });
        }
        if (eventOtherNote) {
            eventOtherNote.textContent = outRange > 0 ? '※他年度に ' + outRange + '件の予定があります。' : '';
        }
    }

    function renderAnnualCalendar() {
        if (!calContainer || !calData) return;
        const fyStart = parseIso(calData.fy_start);
        const fyEnd = parseIso(calData.fy_end);
        const workdays = new Set(calData.workdays || [0, 1, 2, 3, 4]);
        const workOnHoliday = Boolean(calData.work_on_holiday);
        const official = calData.official_holidays || {};
        const office = calData.office_holidays || {};
        const pubEvents = calData.public_events || {};
        const privEvents = calData.private_events || {};
        const todayIso = state.today || '';

        if (calFyTitle) {
            calFyTitle.textContent = calData.fiscal_year + '年度（' + calData.fy_start.replace(/-/g, '/') + ' ～ ' + calData.fy_end.replace(/-/g, '/') + '）';
        }
        if (calFiscalMonth) calFiscalMonth.value = String(calData.fiscal_start_month);
        if (calFiscalDay) calFiscalDay.value = String(calData.fiscal_start_day);
        if (holidayForm) {
            holidayForm.elements.contract_id.value = calData.contract_id;
            holidayForm.elements.fy.value = String(calData.fiscal_year);
        }
        if (eventForm) {
            eventForm.elements.contract_id.value = calData.contract_id;
            eventForm.elements.fy.value = String(calData.fiscal_year);
        }
        if (calSyncBar) {
            const count = calData.same_workplace_count || 0;
            calSyncBar.hidden = count <= 1;
            if (calSyncLabel && count > 1) {
                calSyncLabel.textContent = '同じ表示タイトル「' + calData.display_title + '」の契約（' + count + '件）にも休日変更を同時反映する';
            }
        }

        const months = [];
        let curY = fyStart.getFullYear();
        let curM = fyStart.getMonth();
        const endY = fyEnd.getFullYear();
        const endM = fyEnd.getMonth();
        while (curY < endY || (curY === endY && curM <= endM)) {
            months.push({ y: curY, m: curM });
            curM += 1;
            if (curM > 11) { curM = 0; curY += 1; }
        }

        let totalWorkdays = 0;
        let totalOfficeHolidays = 0;
        let totalAbsenceDays = 0;
        let totalEvents = 0;
        calContainer.replaceChildren();

        months.forEach(function (ym) {
            const box = document.createElement('div');
            box.className = 'cal-month';
            const head = document.createElement('div');
            head.className = 'cal-month-head';
            const title = document.createElement('span');
            title.className = 'cal-month-title';
            title.textContent = ym.y + '年 ' + (ym.m + 1) + '月';
            const monthStat = document.createElement('span');
            monthStat.className = 'cal-month-count';
            head.appendChild(title);
            head.appendChild(monthStat);
            box.appendChild(head);

            const grid = document.createElement('div');
            grid.className = 'cal-month-grid';
            WEEKDAYS_JA.forEach(function (lbl, idx) {
                const dow = document.createElement('div');
                dow.className = 'cal-dow' + (idx === 0 ? ' is-sun' : idx === 6 ? ' is-sat' : '');
                dow.textContent = lbl;
                grid.appendChild(dow);
            });

            const firstOfMonth = new Date(ym.y, ym.m, 1);
            const daysInMonth = new Date(ym.y, ym.m + 1, 0).getDate();
            for (let pad = 0; pad < firstOfMonth.getDay(); pad++) {
                const empty = document.createElement('span');
                empty.className = 'cal-day is-empty';
                grid.appendChild(empty);
            }

            let monthWorkdays = 0;
            for (let dayNum = 1; dayNum <= daysInMonth; dayNum++) {
                const d = new Date(ym.y, ym.m, dayNum);
                const iso = formatIso(d);
                const inFy = d >= fyStart && d <= fyEnd;
                if (!inFy) {
                    const outCell = document.createElement('span');
                    outCell.className = 'cal-day is-outside';
                    outCell.textContent = String(dayNum);
                    grid.appendChild(outCell);
                    continue;
                }
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'cal-day';
                btn.dataset.date = iso;
                btn.textContent = String(dayNum);

                const officeLabel = office[iso] || '';
                const isOfficeAbsence = isAbsenceLabel(officeLabel);
                const isOfficeHoliday = Boolean(officeLabel) && !isOfficeAbsence;
                const isOfficial = Boolean(official[iso]);
                const isRegularWorkday = workdays.has(pyWeekday(d));
                const isNationalOff = isOfficial && !workOnHoliday;
                const isWorkday = !isOfficeHoliday && !isNationalOff && isRegularWorkday;
                const pubEv = pubEvents[iso] || '';
                const privEv = privEvents[iso] || '';
                const tips = [iso + '（' + WEEKDAYS_JA[d.getDay()] + '）'];

                if (isWorkday) {
                    monthWorkdays += 1;
                    totalWorkdays += 1;
                }
                if (isOfficeAbsence) {
                    btn.classList.add('is-absence-holiday');
                    totalAbsenceDays += 1;
                    tips.push('欠勤扱い：' + officeLabel);
                } else if (isOfficeHoliday) {
                    btn.classList.add('is-office-holiday');
                    totalOfficeHolidays += 1;
                    tips.push('事業所指定休日：' + officeLabel);
                } else if (isNationalOff) {
                    btn.classList.add('is-national-holiday');
                    tips.push('国民の祝日：' + official[iso]);
                } else if (!isRegularWorkday) {
                    btn.classList.add('is-off-weekday');
                    tips.push('所定休日');
                } else {
                    btn.classList.add('is-workday');
                    if (isOfficial) tips.push('祝日稼働：' + official[iso]);
                }
                if (pubEv) {
                    btn.classList.add('has-public-event');
                    totalEvents += 1;
                    tips.push('全体予定：' + pubEv);
                }
                if (privEv) {
                    btn.classList.add('has-event');
                    totalEvents += 1;
                    tips.push('個人予定：' + privEv);
                }
                if (iso === todayIso) btn.classList.add('is-today');
                if (iso === selectedDate) btn.classList.add('is-selected');
                btn.title = tips.join('\n');
                btn.addEventListener('click', function () {
                    handleCalendarDateClick(iso);
                });
                grid.appendChild(btn);
            }
            monthStat.textContent = '稼働 ' + monthWorkdays + '日';
            box.appendChild(grid);
            calContainer.appendChild(box);
        });

        if (calStats) {
            calStats.textContent = '年度稼働日：' + totalWorkdays + '日 ／ 事業所指定休日：' + totalOfficeHolidays + '日' + (totalAbsenceDays > 0 ? ' ／ 欠勤扱い：' + totalAbsenceDays + '日' : '') + ' ／ 予定：' + totalEvents + '件';
        }
        renderHolidayList();
        renderEventList();
        if (selectedDate && selectedDate >= calData.fy_start && selectedDate <= calData.fy_end) {
            updateSelectedPanel(selectedDate);
        } else {
            updateSelectedPanel('');
        }
    }

    async function loadCalendar(contractId, fy) {
        setStatus('読み込み中…', false);
        try {
            let url = '/?a=calendar_data&contract=' + encodeURIComponent(contractId);
            if (fy !== undefined && fy !== null && fy !== '') {
                url += '&fy=' + encodeURIComponent(String(fy));
            }
            const res = await fetch(url, { credentials: 'same-origin' });
            if (!res.ok) throw new Error('カレンダーの取得に失敗しました。');
            calData = await res.json();
            renderAnnualCalendar();
            setStatus('', false);
        } catch (err) {
            setStatus(err.message || '通信エラーが発生しました。', true);
        }
    }

    async function postCalendarAction(action, bodyObj) {
        const params = new URLSearchParams();
        Object.keys(bodyObj).forEach(function (k) {
            params.set(k, bodyObj[k]);
        });
        const res = await fetch('/?a=' + encodeURIComponent(action), {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8' },
            body: params.toString(),
        });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || '更新に失敗しました。');
        return data;
    }

    async function saveHoliday(dayStr, label, opts) {
        if (!calData || !dayStr) return;
        pendingHolidayDays.add(dayStr);
        const syncSame = Boolean(calSyncSame && calSyncSame.checked && (calData.same_workplace_count || 0) > 1);
        setStatus('保存中…', false);
        try {
            const res = await postCalendarAction('holiday_save', {
                contract_id: calData.contract_id,
                fy: String(calData.fiscal_year),
                holiday_day: dayStr,
                holiday_name: label,
                sync_same_title: syncSame ? '1' : '0',
            });
            calData = res.calendar;
            selectedDate = dayStr;
            renderAnnualCalendar();
            if (label) {
                setStatus(dayStr + ' を「' + label + '」で登録しました。', false);
            } else if (opts && opts.existingLabel) {
                setStatus(dayStr + '（' + opts.existingLabel + '）を解除しました。', false);
            } else {
                setStatus(dayStr + ' の指定休日を解除しました。', false);
            }
        } catch (err) {
            setStatus(err.message, true);
        } finally {
            pendingHolidayDays.delete(dayStr);
        }
    }

    async function saveEvent(dayStr, text, scope) {
        if (!calData || !dayStr) return;
        const sc = scope || currentEventScope();
        setStatus('保存中…', false);
        try {
            const res = await postCalendarAction('event_save', {
                contract_id: calData.contract_id,
                fy: String(calData.fiscal_year),
                event_day: dayStr,
                event_text: text,
                event_scope: sc,
            });
            calData = res.calendar;
            selectedDate = dayStr;
            renderAnnualCalendar();
            const prefix = sc === 'public' ? '全体予定' : '個人予定';
            setStatus(text ? dayStr + ' の' + prefix + 'を登録しました。' : dayStr + ' の' + prefix + 'を削除しました。', false);
        } catch (err) {
            setStatus(err.message, true);
        }
    }

    editorTabs.forEach(function (btn) {
        btn.addEventListener('click', function () {
            setActiveEditorTab(btn.dataset.editorTab);
            setStatus('', false);
        });
    });
    if (eventScopeInput) {
        eventScopeInput.addEventListener('change', syncEventInputForSelected);
    }

    if (calContractSelect) {
        calContractSelect.addEventListener('change', function () {
            loadCalendar(calContractSelect.value, '');
        });
    }
    if (calPrevBtn) {
        calPrevBtn.addEventListener('click', function () {
            if (calData) loadCalendar(calData.contract_id, calData.fiscal_year - 1);
        });
    }
    if (calNextBtn) {
        calNextBtn.addEventListener('click', function () {
            if (calData) loadCalendar(calData.contract_id, calData.fiscal_year + 1);
        });
    }
    if (calFiscalSaveBtn && calFiscalMonth && calFiscalDay) {
        calFiscalSaveBtn.addEventListener('click', async function () {
            if (!calData) return;
            setStatus('年度開始日を保存中…', false);
            try {
                const res = await postCalendarAction('contract_fiscal_save', {
                    contract_id: calData.contract_id,
                    fy: String(calData.fiscal_year),
                    fiscal_start_month: calFiscalMonth.value,
                    fiscal_start_day: calFiscalDay.value,
                });
                calData = res.calendar;
                renderAnnualCalendar();
                setStatus('年度開始日を保存しました。', false);
            } catch (err) {
                setStatus(err.message, true);
            }
        });
    }
    if (calCopyBtn && calCopySource) {
        calCopyBtn.addEventListener('click', async function () {
            if (!calData) return;
            const src = calCopySource.value;
            if (!src) { setStatus('コピー元の契約を選択してください。', true); return; }
            if (src === calData.contract_id) { setStatus('同じ契約からはコピーできません。', true); return; }
            if (!window.confirm('選択した契約の事業所指定休日を現在の契約へ上書きコピーします。よろしいですか？')) return;
            try {
                const res = await postCalendarAction('holiday_copy', {
                    target_contract_id: calData.contract_id,
                    source_contract_id: src,
                    fy: String(calData.fiscal_year),
                });
                calData = res.calendar;
                renderAnnualCalendar();
                setStatus(res.copied + '件の事業所指定休日をコピーしました。', false);
            } catch (err) {
                setStatus(err.message, true);
            }
        });
    }
    if (calClearBtn) {
        calClearBtn.addEventListener('click', async function () {
            if (!calData) return;
            if (!window.confirm('この契約の事業所指定休日をすべてクリアします。よろしいですか？')) return;
            const syncSame = Boolean(calSyncSame && calSyncSame.checked && (calData.same_workplace_count || 0) > 1);
            try {
                const res = await postCalendarAction('holiday_clear', {
                    contract_id: calData.contract_id,
                    fy: String(calData.fiscal_year),
                    sync_same_title: syncSame ? '1' : '0',
                });
                calData = res.calendar;
                renderAnnualCalendar();
                setStatus('事業所指定休日をすべてクリアしました。', false);
            } catch (err) {
                setStatus(err.message, true);
            }
        });
    }

    if (holidayForm) {
        holidayForm.addEventListener('submit', function (event) {
            event.preventDefault();
            const dayStr = holidayDayInput ? holidayDayInput.value.trim() : '';
            const label = holidayNameInput ? holidayNameInput.value.trim() : '';
            if (!dayStr) { setStatus('日付を選択してください。', true); return; }
            if (!label) {
                setStatus('休日名を入力してください（解除する場合は削除ボタンを押してください）。', true);
                if (holidayNameInput) holidayNameInput.focus();
                return;
            }
            saveHoliday(dayStr, label);
        });
    }
    if (holidayDeleteBtn) {
        holidayDeleteBtn.addEventListener('click', function () {
            const dayStr = holidayDayInput ? holidayDayInput.value.trim() : '';
            if (dayStr) saveHoliday(dayStr, '');
        });
    }
    if (eventForm) {
        eventForm.addEventListener('submit', function (event) {
            event.preventDefault();
            const dayStr = eventDayInput ? eventDayInput.value.trim() : '';
            const text = eventTextInput ? eventTextInput.value.trim() : '';
            if (!dayStr) { setStatus('日付を選択してください。', true); return; }
            saveEvent(dayStr, text, currentEventScope());
        });
    }
    if (eventDeleteBtn) {
        eventDeleteBtn.addEventListener('click', function () {
            const dayStr = eventDayInput ? eventDayInput.value.trim() : '';
            if (dayStr) saveEvent(dayStr, '', currentEventScope());
        });
    }
    document.querySelectorAll('[data-holiday-preset]').forEach(function (chip) {
        chip.addEventListener('click', function () {
            if (!holidayNameInput) return;
            const preset = chip.dataset.holidayPreset || '';
            const current = holidayNameInput.value.trim();
            if (current === preset) {
                holidayNameInput.value = '';
                syncHolidayChipHighlight();
                setStatus('休日名をクリアしました（登録モード解除）。', false);
            } else {
                holidayNameInput.value = preset;
                syncHolidayChipHighlight();
                setStatus('「' + preset + '」を選択中：カレンダーの日付をクリックすると即登録されます。', false);
            }
        });
    });
    if (holidayNameInput) {
        holidayNameInput.addEventListener('input', syncHolidayChipHighlight);
    }

    if (calData) {
        setActiveEditorTab(activeEditorTab);
        renderAnnualCalendar();
        syncHolidayChipHighlight();
    }
}());
