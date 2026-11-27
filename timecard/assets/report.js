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

    const entryDialog = document.getElementById('entry-dialog');
    const entryCard = document.getElementById('entry-card');
    const entryDayLabel = document.getElementById('entry-day-label');
    const entryHolidayLabel = document.getElementById('entry-holiday-label');
    const entryStatusBoxes = document.getElementById('entry-status-boxes');
    const entryEventBox = document.getElementById('entry-event-box');
    const entryEventText = document.getElementById('entry-event-text');
    const entryClosingBox = document.getElementById('entry-closing-box');
    const entrySummary = document.getElementById('entry-summary');
    const entryPrev = document.getElementById('entry-prev');
    const entryNext = document.getElementById('entry-next');
    const entryToday = document.getElementById('entry-today');
    const entryClose = document.getElementById('entry-close');
    const form = document.getElementById('entry-form');
    const start = form.elements.clock_in;
    const end = form.elements.clock_out;
    const breakInput = form.elements.break_minutes;
    const earlyCheck = document.getElementById('entry-early');
    const regular = document.getElementById('regular-time');

    const dataEl = document.getElementById('work-days-data');
    let daysData = {};
    if (dataEl) {
        try {
            daysData = JSON.parse(dataEl.textContent || '{}');
        } catch (error) {
            daysData = {};
        }
    }

    function updateRegular() {
        regular.disabled = Boolean(start.value.trim() && end.value.trim());
    }
    regular.addEventListener('click', function () {
        if (!start.value.trim()) start.value = regular.dataset.regularStart || '830';
        if (!end.value.trim()) end.value = regular.dataset.regularEnd || '1730';
        updateRegular();
    });
    document.querySelectorAll('[data-clear]').forEach(function (button) {
        button.addEventListener('click', function () {
            const field = form.elements[button.dataset.clear];
            if (field) { field.value = ''; field.focus(); updateRegular(); }
        });
    });
    document.querySelectorAll('.time-entry').forEach(function (field) {
        field.addEventListener('input', function () {
            field.value = field.value.replace(/[^0-9:]/g, '');
            updateRegular();
        });
        field.addEventListener('change', updateRegular);
    });

    function setActiveRow(dayStr) {
        document.querySelectorAll('tr.day-row.is-active').forEach(function (row) {
            row.classList.remove('is-active');
        });
        const target = document.querySelector('tr.day-row[data-day="' + dayStr + '"]');
        if (target) target.classList.add('is-active');
    }

    function populateEntry(data) {
        const hasEvent = Boolean(data.event);
        const isClosing = Boolean(data.is_closing);
        entryCard.className = 'card selected-day' + (data.cls ? ' ' + data.cls : '') + (isClosing ? ' is-closing' : '');
        entryDayLabel.textContent = data.day + '（' + data.weekday + '）';
        entryPrev.href = '/?day=' + encodeURIComponent(data.prev) + '&open=1';
        entryPrev.dataset.day = data.prev;
        entryNext.href = '/?day=' + encodeURIComponent(data.nxt) + '&open=1';
        entryNext.dataset.day = data.nxt;
        if (data.holiday_label) {
            entryHolidayLabel.textContent = data.holiday_label;
            entryHolidayLabel.hidden = false;
        } else {
            entryHolidayLabel.textContent = '';
            entryHolidayLabel.hidden = true;
        }
        if (entryEventBox && entryEventText) {
            if (hasEvent) {
                entryEventText.textContent = data.event;
                entryEventBox.hidden = false;
            } else {
                entryEventText.textContent = '';
                entryEventBox.hidden = true;
            }
        }
        if (entryClosingBox) {
            entryClosingBox.hidden = !isClosing;
        }
        if (entryStatusBoxes) {
            entryStatusBoxes.hidden = !(hasEvent || isClosing);
        }
        form.elements.day.value = data.day;
        start.value = data.clock_in || '';
        end.value = data.clock_out || '';
        if (earlyCheck) earlyCheck.checked = Boolean(data.early_work);
        breakInput.value = data.break_minutes || '';
        breakInput.placeholder = '自動 ' + (data.suggested_break || '60');
        form.elements.report.value = data.report || '';
        form.elements.note.value = data.note || '';
        entrySummary.textContent =
            '計算用時刻：' + (data.start || '—') + ' ～ ' + (data.end || '—') + '\u3000実績：' + (data.total_fmt || '—') +
            (data.early_fmt ? '（うち早出 ' + data.early_fmt + '）' : '');
        entryDialog.dataset.selectedDay = data.day;
        setActiveRow(data.day);
        updateRegular();
    }

    function openEntry(dayStr) {
        if (!dayStr) return;
        const data = daysData[dayStr];
        if (!data) {
            window.location.href = '/?day=' + encodeURIComponent(dayStr) + '&open=1';
            return;
        }
        populateEntry(data);
        if (entryDialog && !entryDialog.open) {
            entryDialog.showModal();
        }
    }

    function isModifiedClick(event) {
        return event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0;
    }

    if (entryClose && entryDialog) {
        entryClose.addEventListener('click', function () {
            entryDialog.close();
        });
        entryDialog.addEventListener('click', function (event) {
            if (event.target === entryDialog) {
                entryDialog.close();
            }
        });
    }

    [entryPrev, entryNext].forEach(function (link) {
        if (!link) return;
        link.addEventListener('click', function (event) {
            if (isModifiedClick(event)) return;
            const targetDay = link.dataset.day || new URL(link.href, window.location.href).searchParams.get('day');
            if (targetDay && daysData[targetDay]) {
                event.preventDefault();
                openEntry(targetDay);
            }
        });
    });

    if (entryToday && entryDialog) {
        entryToday.addEventListener('click', function (event) {
            if (isModifiedClick(event)) return;
            const todayDay = entryDialog.dataset.today;
            if (todayDay && daysData[todayDay]) {
                event.preventDefault();
                openEntry(todayDay);
            }
        });
    }

    document.querySelectorAll('tr.day-row[data-day]').forEach(function (row) {
        row.addEventListener('click', function (event) {
            if (event.target.closest('form, button')) return;
            if (isModifiedClick(event)) return;
            const link = event.target.closest('a');
            if (link) event.preventDefault();
            openEntry(row.dataset.day);
        });
    });

    const openTodayBtn = document.getElementById('open-today-entry');
    if (openTodayBtn && entryDialog) {
        openTodayBtn.addEventListener('click', function () {
            openEntry(entryDialog.dataset.today);
        });
    }

    updateRegular();
    window.addEventListener('pageshow', updateRegular);

    if (entryDialog && entryDialog.dataset.autoOpen === '1') {
        openEntry(entryDialog.dataset.selectedDay);
    }

    const search = document.getElementById('work-search');
    const button = document.getElementById('work-search-button');
    const toolbarSearchButton = document.getElementById('toolbar-search-button');
    const dialogSearch = document.getElementById('dialog-work-search');
    const dialogSearchButton = document.getElementById('dialog-work-search-button');
    const dialog = document.getElementById('search-dialog');
    const results = document.getElementById('search-results');
    const message = document.getElementById('search-message');

    document.getElementById('search-close').addEventListener('click', function () { dialog.close(); });
    dialog.addEventListener('click', function (event) {
        const rect = dialog.getBoundingClientRect();
        if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) {
            dialog.close();
        }
    });

    async function searchWork(querySource) {
        const query = (querySource || search.value).trim();
        if (!query || button.disabled) return;
        search.value = query;
        if (dialogSearch) dialogSearch.value = query;
        results.replaceChildren();
        message.textContent = '検索中…';
        if (!dialog.open) dialog.showModal();
        button.disabled = true;
        if (dialogSearchButton) dialogSearchButton.disabled = true;
        try {
            const response = await fetch('/?a=search&q=' + encodeURIComponent(query), { credentials: 'same-origin' });
            if (!response.ok) throw new Error('search failed');
            const rows = await response.json();
            message.textContent = rows.length ? rows.length + '件見つかりました' : '該当する実績はありません';
            rows.forEach(function (row) {
                const item = document.createElement('li');
                const link = document.createElement('a');
                link.href = '/?day=' + encodeURIComponent(row.day) + '&open=1';
                link.textContent = row.day + '　' + row.report + (row.note ? ' ／ ' + row.note : '');
                link.addEventListener('click', function (event) {
                    if (isModifiedClick(event)) return;
                    if (daysData[row.day]) {
                        event.preventDefault();
                        dialog.close();
                        openEntry(row.day);
                    }
                });
                item.appendChild(link);
                results.appendChild(item);
            });
        } catch (error) {
            message.textContent = '検索できませんでした。ログイン状態と通信状況を確認してください。';
        } finally {
            button.disabled = false;
            if (dialogSearchButton) dialogSearchButton.disabled = false;
        }
    }

    button.addEventListener('click', function () { searchWork(search.value); });
    search.addEventListener('keydown', function (event) {
        if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); searchWork(search.value); }
    });
    if (dialogSearch && dialogSearchButton) {
        dialogSearchButton.addEventListener('click', function () { searchWork(dialogSearch.value); });
        dialogSearch.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); searchWork(dialogSearch.value); }
        });
    }
    if (toolbarSearchButton) {
        toolbarSearchButton.addEventListener('click', function () {
            if (!dialog.open) dialog.showModal();
            if (dialogSearch) {
                dialogSearch.focus();
                dialogSearch.select();
            }
        });
    }

    function tick() {
        const clockEl = document.getElementById('clock');
        if (clockEl) {
            clockEl.textContent = new Date().toLocaleTimeString('ja-JP', { hour12: false });
        }
    }
    tick();
    setInterval(tick, 1000);
}());
