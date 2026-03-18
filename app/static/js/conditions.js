let condTeachers = [];
let condLevels = [];
let condHalls = [];
let condDays = [];

// جلب البيانات الأساسية للقيود
function initConditionsData() {
    Promise.all([
        fetch('/teachers').then(res => res.json()),
        fetch('/api/levels').then(res => res.json()),
        fetch('/api/halls').then(res => res.json()),
        fetch('/api/structure').then(res => res.json()),
        fetch('/api/conditions').then(res => res.json())
    ]).then(([teachers, levels, halls, structure, savedConds]) => {
        condTeachers = teachers;
        condLevels = levels;
        condHalls = halls;
        condDays = (structure || []).map(d => d.name);
        
        renderConditionsUI();
        if(Object.keys(savedConds).length > 0) populateSavedConditions(savedConds);
    });
}

// بناء الواجهة ديناميكياً
function renderConditionsUI() {
    // 1. المعرفات
    const idContainer = document.getElementById('identifiers-container');
    idContainer.innerHTML = condLevels.map(lvl => `
        <div style="flex: 1; min-width: 150px;">
            <strong>${lvl}</strong>
            <textarea id="ident_${lvl}" rows="3" style="width:100%; font-size:12px;" placeholder="معرف 1\nمعرف 2..."></textarea>
        </div>
    `).join('');

    // 2. الجدول الشامل للأساتذة (ديناميكي بناءً على الأيام)
    const masterHead = document.getElementById('master-teachers-header');
    let thHtml = `<th>الأستاذ</th>`;
    condDays.forEach(d => thHtml += `<th>${d}</th>`);
    thHtml += `<th>بدء ح2</th><th>بدء ح3</th><th>إنهاء بـ ح3</th><th>إنهاء بـ ح4</th><th>بدء ح2 + إنهاء ح4 (يلغي ماسبقه)</th><th>قاعدة التوزيع</th>`;
    masterHead.innerHTML = thHtml;

    const masterBody = document.querySelector('#master-teachers-table tbody');
    masterBody.innerHTML = condTeachers.map(t => {
        let tr = `<tr><td><strong>${t.name}</strong></td>`;
        // مربعات الأيام
        condDays.forEach(d => tr += `<td><input type="checkbox" class="t-day-chk" data-tid="${t.id}" data-day="${d}"></td>`);
        
        // قيود البداية والنهاية
        tr += `
            <td><input type="checkbox" class="t-lim" data-tid="${t.id}" data-type="s2" onchange="checkMasterLimit(${t.id})"></td>
            <td><input type="checkbox" class="t-lim" data-tid="${t.id}" data-type="s3" onchange="checkMasterLimit(${t.id})"></td>
            <td><input type="checkbox" class="t-lim" data-tid="${t.id}" data-type="e3" onchange="checkMasterLimit(${t.id})"></td>
            <td><input type="checkbox" class="t-lim" data-tid="${t.id}" data-type="e4" onchange="checkMasterLimit(${t.id})"></td>
            <td style="background:#e8f4f8;"><input type="checkbox" class="t-lim-master" data-tid="${t.id}" onchange="checkMasterLimit(${t.id})"></td>
            <td>
                <select id="rule_${t.id}" style="font-size:11px;">
                    <option value="unspecified">غير محدد (مرن)</option>
                    <option value="group2">تجميع في يومين</option>
                    <option value="group3">تجميع في 3 أيام</option>
                    <option value="sep2">يومان منفصلان</option>
                    <option value="sep3">3 أيام منفصلة</option>
                </select>
            </td>
        </tr>`;
        return tr;
    }).join('');

    // 3. توالي القاعات
    const consecSelect = document.getElementById('consecutive-halls-rule');
    consecSelect.innerHTML = `<option value="none">لا يوجد منع (السماح بالتوالي)</option>` + 
        condHalls.map(h => `<option value="${h.id}">منع التوالي في: ${h.name}</option>`).join('');

    // 4. تخصيص المدرجات
    const lvlAmphiContainer = document.getElementById('level-amphis-container');
    lvlAmphiContainer.innerHTML = `<table class="overview-table" style="font-size:12px;"><tbody>` + 
        condLevels.map(lvl => `<tr>
            <td>${lvl}</td>
            <td><select id="lvl_amphi_${lvl}"><option value="">بدون تخصيص</option>${condHalls.map(h => `<option value="${h.id}">${h.name}</option>`).join('')}</select></td>
        </tr>`).join('') + `</tbody></table>`;

    // 5. السبت وآخر الحصص
    const specBody = document.querySelector('#special-teachers-table tbody');
    specBody.innerHTML = condTeachers.map(t => `<tr>
        <td>${t.name}</td>
        <td style="text-align:center;"><input type="checkbox" id="sat_${t.id}"></td>
        <td>
            <select id="last_${t.id}">
                <option value="none">لا يوجد قيد</option>
                <option value="1">منع آخر حصة</option>
                <option value="2">منع آخر حصتين</option>
            </select>
        </td>
    </tr>`).join('');

    // 6. التحسين
    const optContainer = document.getElementById('optimization-teachers');
    optContainer.innerHTML = condTeachers.map(t => `<label style="background:#fff; padding:5px; border:1px solid #ccc; border-radius:3px;"><input type="checkbox" class="opt-chk" value="${t.id}" checked> ${t.name}</label>`).join('');
}

// دالة تعطيل القيود الأخرى إذا تم اختيار القيد الشامل (ح2 + ح4)
function checkMasterLimit(tid) {
    const masterChk = document.querySelector(`.t-lim-master[data-tid="${tid}"]`);
    const otherChks = document.querySelectorAll(`.t-lim[data-tid="${tid}"]`);
    if(masterChk && masterChk.checked) {
        otherChks.forEach(chk => { chk.checked = false; chk.disabled = true; });
    } else {
        otherChks.forEach(chk => { chk.disabled = false; });
    }
}

// دالة إضافة صفوف تشارك الأيام
// دالة إضافة صفوف تشارك الأيام (محدثة لتدعم الاسترجاع)
function addPairRow(containerId, val1 = "", val2 = "") {
    const container = document.getElementById(containerId);
    if(!container) return;
    const div = document.createElement('div');
    div.style.marginBottom = "5px";
    
    // نستخدم == بدلاً من === لكي يتطابق النص مع الرقم
    let html = `<select class="pair-t1"><option value="">اختر أستاذ...</option>${condTeachers.map(t=>`<option value="${t.id}" ${t.id == val1 ? 'selected' : ''}>${t.name}</option>`).join('')}</select> مع `;
    html += `<select class="pair-t2"><option value="">اختر أستاذ...</option>${condTeachers.map(t=>`<option value="${t.id}" ${t.id == val2 ? 'selected' : ''}>${t.name}</option>`).join('')}</select> `;
    html += `<button onclick="this.parentElement.remove()" style="color:red; border:none; background:none; cursor:pointer;">❌</button>`;
    
    div.innerHTML = html;
    container.appendChild(div);
}

// ================= جمع وحفظ البيانات =================
function saveAllConditions() {
    const data = {
        identifiers: {},
        teacher_rules: {},
        weights: { // <--- هذا هو القسم الجديد
            distribution: document.getElementById('weight_distribution').value,
            no_share: document.getElementById('weight_no_share').value,
            saturday: document.getElementById('weight_saturday').value,
            last_slot: document.getElementById('weight_last_slot').value,
            max_daily: document.getElementById('weight_max_daily').value,
            share_pairs: document.getElementById('weight_share_pairs').value,
            consecutive_halls: document.getElementById('weight_consecutive_halls').value,
            morning_pref: document.getElementById('weight_morning_pref').value
        },
        global: {
            days_interpretation: document.querySelector('input[name="days_rule"]:checked').value,
            max_slots: document.getElementById('max-slots-per-day').value,
            consecutive_hall_ban: document.getElementById('consecutive-halls-rule').value,
            rest_tue_pm: document.getElementById('rest-tue-pm').checked,
            rest_thu_pm: document.getElementById('rest-thu-pm').checked
        },
        level_amphis: {},
        special_teachers: {},
        pairs: { share: [], noshare: [] },
        optimization: {
            level: document.querySelector('input[name="opt_level"]:checked').value,
            teachers: Array.from(document.querySelectorAll('.opt-chk:checked')).map(c => c.value)
        }
    };

    // 1. المعرفات
    condLevels.forEach(lvl => {
        const val = document.getElementById(`ident_${lvl}`).value.trim();
        if(val) data.identifiers[lvl] = val.split('\n').map(v=>v.trim()).filter(v=>v);
    });

    // 2. الأساتذة (الجدول الرئيسي)
    condTeachers.forEach(t => {
        const days = Array.from(document.querySelectorAll(`.t-day-chk[data-tid="${t.id}"]:checked`)).map(c => c.getAttribute('data-day'));
        const isMaster = document.querySelector(`.t-lim-master[data-tid="${t.id}"]`).checked;
        const limits = isMaster ? ['s2', 'e4'] : Array.from(document.querySelectorAll(`.t-lim[data-tid="${t.id}"]:checked`)).map(c => c.getAttribute('data-type'));
        
        data.teacher_rules[t.id] = {
            days: days,
            limits: limits,
            rule: document.getElementById(`rule_${t.id}`).value
        };

        // السبت وآخر حصص
        data.special_teachers[t.id] = {
            allow_saturday: document.getElementById(`sat_${t.id}`).checked,
            prevent_last: document.getElementById(`last_${t.id}`).value
        };
    });

    // 3. المدرجات
    condLevels.forEach(lvl => {
        const val = document.getElementById(`lvl_amphi_${lvl}`).value;
        if(val) data.level_amphis[lvl] = val;
    });

    // 4. الأزواج
    document.querySelectorAll('#share-days-container div').forEach(div => {
        const t1 = div.querySelector('.pair-t1').value;
        const t2 = div.querySelector('.pair-t2').value;
        if(t1 && t2 && t1 !== t2) data.pairs.share.push([t1, t2]);
    });
    document.querySelectorAll('#noshare-days-container div').forEach(div => {
        const t1 = div.querySelector('.pair-t1').value;
        const t2 = div.querySelector('.pair-t2').value;
        if(t1 && t2 && t1 !== t2) data.pairs.noshare.push([t1, t2]);
    });

    // إرسال للخادم
    fetch('/api/conditions', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    }).then(res => res.json()).then(res => {
        if(res.success) alert("تم حفظ جميع الشروط والقيود بنجاح!");
    });
}

function populateSavedConditions(data) {
    if(!data || Object.keys(data).length === 0) return;

    // 1. المعرفات
    if(data.identifiers) {
        for(const [lvl, idents] of Object.entries(data.identifiers)) {
            const el = document.getElementById(`ident_${lvl}`);
            if(el) el.value = idents.join('\n');
        }
    }

    // 2. الأساتذة (الجدول الرئيسي)
    if(data.teacher_rules) {
        for(const [tid, rules] of Object.entries(data.teacher_rules)) {
            if(rules.days) {
                rules.days.forEach(d => {
                    const chk = document.querySelector(`.t-day-chk[data-tid="${tid}"][data-day="${d}"]`);
                    if(chk) chk.checked = true;
                });
            }
            if(rules.limits) {
                rules.limits.forEach(lim => {
                    const chk = document.querySelector(`.t-lim[data-tid="${tid}"][data-type="${lim}"]`);
                    if(chk) chk.checked = true;
                });
            }
            const ruleSelect = document.getElementById(`rule_${tid}`);
            if(ruleSelect && rules.rule) ruleSelect.value = rules.rule;
        }
    }

    // 3. الأوزان
    if(data.weights) {
        const wMap = {
            'weight_distribution': data.weights.distribution,
            'weight_no_share': data.weights.no_share,
            'weight_saturday': data.weights.saturday,
            'weight_last_slot': data.weights.last_slot,
            'weight_max_daily': data.weights.max_daily,
            'weight_share_pairs': data.weights.share_pairs,
            'weight_consecutive_halls': data.weights.consecutive_halls,
            'weight_morning_pref': data.weights.morning_pref
        };
        for(const [id, val] of Object.entries(wMap)) {
            const el = document.getElementById(id);
            if(el && val) el.value = val;
        }
    }

    // 4. الإعدادات العامة
    if(data.global) {
        const daysRule = document.querySelector(`input[name="days_rule"][value="${data.global.days_interpretation}"]`);
        if(daysRule) daysRule.checked = true;
        
        const maxSlots = document.getElementById('max-slots-per-day');
        if(maxSlots && data.global.max_slots) maxSlots.value = data.global.max_slots;
        
        const consHalls = document.getElementById('consecutive-halls-rule');
        if(consHalls && data.global.consecutive_hall_ban) consHalls.value = data.global.consecutive_hall_ban;
        
        const restTue = document.getElementById('rest-tue-pm');
        if(restTue) restTue.checked = !!data.global.rest_tue_pm;
        
        const restThu = document.getElementById('rest-thu-pm');
        if(restThu) restThu.checked = !!data.global.rest_thu_pm;
    }

    // 5. المدرجات
    if(data.level_amphis) {
        for(const [lvl, hid] of Object.entries(data.level_amphis)) {
            const el = document.getElementById(`lvl_amphi_${lvl}`);
            if(el) el.value = hid;
        }
    }

    // 6. السبت وآخر حصص
    if(data.special_teachers) {
        for(const [tid, spec] of Object.entries(data.special_teachers)) {
            const sat = document.getElementById(`sat_${tid}`);
            if(sat) sat.checked = !!spec.allow_saturday;
            
            const last = document.getElementById(`last_${tid}`);
            if(last && spec.prevent_last) last.value = spec.prevent_last;
        }
    }

    // 7. إعدادات التحسين
    if(data.optimization) {
        const optLevel = document.querySelector(`input[name="opt_level"][value="${data.optimization.level}"]`);
        if(optLevel) optLevel.checked = true;
        
        const optChks = document.querySelectorAll('.opt-chk');
        optChks.forEach(chk => {
            chk.checked = data.optimization.teachers.includes(chk.value);
        });
    }

    // 8. استرجاع الأزواج (التشارك ومنع التشارك)
    if (data.pairs) {
        const shareContainer = document.getElementById('share-days-container');
        if (shareContainer) shareContainer.innerHTML = '';
        if (data.pairs.share) {
            data.pairs.share.forEach(p => addPairRow('share-days-container', p[0], p[1]));
        }

        const noshareContainer = document.getElementById('noshare-days-container');
        if (noshareContainer) noshareContainer.innerHTML = '';
        if (data.pairs.noshare) {
            data.pairs.noshare.forEach(p => addPairRow('noshare-days-container', p[0], p[1]));
        }
    }
}