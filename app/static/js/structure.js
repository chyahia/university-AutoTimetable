let scheduleStructure = []; // سيحفظ كل الهيكل هنا
let cachedLevelsForStruct = [];
let cachedHallsForStruct = [];
let activeDayId = null;

// توليد مُعرّف عشوائي فريد
const genId = () => 'id_' + Math.random().toString(36).substr(2, 9);

// جلب البيانات الأساسية عند فتح التبويب
function initStructureData() {
    fetch('/api/levels').then(res => res.json()).then(data => cachedLevelsForStruct = data);
    fetch('/api/halls').then(res => res.json()).then(data => cachedHallsForStruct = data);
    fetch('/api/structure').then(res => res.json()).then(data => {
        scheduleStructure = data || [];
        if(scheduleStructure.length > 0) activeDayId = scheduleStructure[0].id;
        renderStructure();
    });
}

// ================= إدارة الأيام =================
// متغيرات لتتبع حالة نافذة الأيام
let dayModalAction = null; 
let targetDayIdForDuplicate = null;

// ================= إدارة الأيام (بالقائمة المنسدلة) =================

// فتح نافذة اختيار اليوم للإضافة
function addDay() {
    dayModalAction = 'add';
    document.getElementById('day-modal').style.display = 'flex';
    document.getElementById('day-modal-title').innerText = 'إضافة يوم جديد';
}

// فتح نافذة اختيار اليوم للتكرار
function duplicateDay(dayId) {
    dayModalAction = 'duplicate';
    targetDayIdForDuplicate = dayId;
    document.getElementById('day-modal').style.display = 'flex';
    document.getElementById('day-modal-title').innerText = 'تكرار اليوم (اختر اليوم الجديد)';
}

// إغلاق النافذة
function closeDayModal() {
    document.getElementById('day-modal').style.display = 'none';
}

// تأكيد اختيار اليوم من القائمة المنسدلة
function confirmDaySelection() {
    const selectedDayName = document.getElementById('selected-day').value;

    if (dayModalAction === 'add') {
        // إضافة يوم جديد فارغ
        const newDay = { id: genId(), name: selectedDayName, slots: [] };
        scheduleStructure.push(newDay);
        activeDayId = newDay.id;

    } else if (dayModalAction === 'duplicate') {
        // نسخ اليوم المختار مع تغيير المعرّفات واسم اليوم
        const dayToCopy = scheduleStructure.find(d => d.id === targetDayIdForDuplicate);
        if (dayToCopy) {
            const newDay = JSON.parse(JSON.stringify(dayToCopy)); // نسخ عميق
            newDay.id = genId();
            newDay.name = selectedDayName;
            
            // تحديث معرّفات الفترات والقيود حتى لا تتداخل مع اليوم الأصلي
            newDay.slots.forEach(slot => {
                slot.id = genId();
                slot.constraints.forEach(c => c.id = genId());
            });
            
            scheduleStructure.push(newDay);
            activeDayId = newDay.id;
        }
    }

    closeDayModal(); // إخفاء النافذة
    renderStructure(); // إعادة رسم الواجهة
}

function deleteDay(dayId) {
    if(!confirm('هل أنت متأكد من حذف هذا اليوم بالكامل؟')) return;
    scheduleStructure = scheduleStructure.filter(d => d.id !== dayId);
    if(scheduleStructure.length > 0) activeDayId = scheduleStructure[0].id;
    else activeDayId = null;
    renderStructure();
}
// ================= نهاية إدارة الأيام =================

// ================= إدارة الفترات والقيود =================
function addSlot(dayId) {
    const day = scheduleStructure.find(d => d.id === dayId);
    day.slots.push({ id: genId(), start: "08:00", end: "09:30", constraints: [] });
    renderStructure();
}

function deleteSlot(dayId, slotId) {
    const day = scheduleStructure.find(d => d.id === dayId);
    day.slots = day.slots.filter(s => s.id !== slotId);
    renderStructure();
}

function addConstraint(dayId, slotId) {
    const day = scheduleStructure.find(d => d.id === dayId);
    const slot = day.slots.find(s => s.id === slotId);
    slot.constraints.push({ 
        id: genId(), 
        room_rule: "all", 
        specific_halls: [], 
        levels: [] 
    });
    renderStructure();
}

function deleteConstraint(dayId, slotId, constraintId) {
    const day = scheduleStructure.find(d => d.id === dayId);
    const slot = day.slots.find(s => s.id === slotId);
    slot.constraints = slot.constraints.filter(c => c.id !== constraintId);
    renderStructure();
}

// ================= تحديث البيانات في المصفوفة عند التعديل =================
function updateSlotTime(dayId, slotId, field, value) {
    const slot = scheduleStructure.find(d => d.id === dayId).slots.find(s => s.id === slotId);
    slot[field] = value;
}

function updateConstraintRule(dayId, slotId, constraintId, value) {
    const constraint = scheduleStructure.find(d => d.id === dayId).slots.find(s => s.id === slotId).constraints.find(c => c.id === constraintId);
    constraint.room_rule = value;
    renderStructure(); // إعادة الرسم لإظهار/إخفاء قائمة المدرجات المحددة
}

function toggleConstraintLevel(dayId, slotId, constraintId, levelName, isChecked) {
    const constraint = scheduleStructure.find(d => d.id === dayId).slots.find(s => s.id === slotId).constraints.find(c => c.id === constraintId);
    if(isChecked) constraint.levels.push(levelName);
    else constraint.levels = constraint.levels.filter(l => l !== levelName);
}

function toggleConstraintHall(dayId, slotId, constraintId, hallName, isChecked) {
    const constraint = scheduleStructure.find(d => d.id === dayId).slots.find(s => s.id === slotId).constraints.find(c => c.id === constraintId);
    if(isChecked) constraint.specific_halls.push(hallName);
    else constraint.specific_halls = constraint.specific_halls.filter(h => h !== hallName);
}

// ================= رسم الواجهة (Rendering) =================
function renderStructure() {
    const tabsContainer = document.getElementById('days-tabs-container');
    const contentContainer = document.getElementById('days-content-container');
    
    tabsContainer.innerHTML = '';
    contentContainer.innerHTML = '';

    scheduleStructure.forEach(day => {
        // إنشاء التبويب العلوي
        const isActive = day.id === activeDayId;
        tabsContainer.innerHTML += `<div class="day-tab ${isActive ? 'active' : ''}" onclick="activeDayId='${day.id}'; renderStructure();">${day.name}</div>`;
        
        // إنشاء محتوى اليوم
        if (isActive) {
            let dayHtml = `<div class="day-content active">
                <div class="day-actions">
                    <button onclick="duplicateDay('${day.id}')" style="padding: 5px; cursor:pointer;">🔂 تكرار هذا اليوم</button>
                    <button onclick="deleteDay('${day.id}')" style="padding: 5px; color: red; cursor:pointer;">❌ حذف اليوم</button>
                </div>`;
            
            day.slots.forEach(slot => {
                dayHtml += `
                <div class="time-slot">
                    <div class="slot-header">
                        <span>من:</span> <input type="time" value="${slot.start}" onchange="updateSlotTime('${day.id}', '${slot.id}', 'start', this.value)">
                        <span>إلى:</span> <input type="time" value="${slot.end}" onchange="updateSlotTime('${day.id}', '${slot.id}', 'end', this.value)">
                        <button onclick="deleteSlot('${day.id}', '${slot.id}')" style="margin-right:auto; color:red; cursor:pointer;">حذف الفترة</button>
                    </div>
                    <div class="slot-body">
                        <button onclick="addConstraint('${day.id}', '${slot.id}')" style="margin-bottom:10px; cursor:pointer;">➕ إضافة قيد</button>
                `;

                slot.constraints.forEach(c => {
                    dayHtml += `<div class="constraint-box">
                        <div style="display:flex; gap:10px; margin-bottom:10px;">
                            <label><strong>نوع القاعة المتاحة:</strong></label>
                            <select onchange="updateConstraintRule('${day.id}', '${slot.id}', '${c.id}', this.value)" style="padding:5px;">
                                <option value="all" ${c.room_rule === 'all' ? 'selected' : ''}>جميع المدرجات والقاعات متاحة</option>
                                <option value="regular" ${c.room_rule === 'regular' ? 'selected' : ''}>القاعات العادية فقط</option>
                                <option value="specific" ${c.room_rule === 'specific' ? 'selected' : ''}>المدرجات المحددة</option>
                                <option value="none" ${c.room_rule === 'none' ? 'selected' : ''}>لا توجد أي قاعة</option>
                            </select>
                            <button onclick="deleteConstraint('${day.id}', '${slot.id}', '${c.id}')" style="margin-right:auto; color:red; cursor:pointer; background:none; border:none;">حذف القيد ❌</button>
                        </div>`;
                    
                    // إظهار المدرجات المحددة فقط إذا تم اختيار "المدرجات المحددة"
                    if(c.room_rule === 'specific') {
                        dayHtml += `<div class="halls-dropdown" style="display:block;">
                            <strong>اختر المدرجات:</strong><br>`;
                        cachedHallsForStruct.forEach(hall => {
                            const checked = c.specific_halls.includes(hall.name) ? 'checked' : '';
                            dayHtml += `<label style="margin-left:10px;"><input type="checkbox" ${checked} onchange="toggleConstraintHall('${day.id}', '${slot.id}', '${c.id}', '${hall.name}', this.checked)"> ${hall.name}</label>`;
                        });
                        dayHtml += `</div>`;
                    }

                    // قائمة المستويات
                    dayHtml += `<div class="levels-grid">`;
                    cachedLevelsForStruct.forEach(lvl => {
                        const checked = c.levels.includes(lvl) ? 'checked' : '';
                        dayHtml += `<label><input type="checkbox" ${checked} onchange="toggleConstraintLevel('${day.id}', '${slot.id}', '${c.id}', '${lvl}', this.checked)"> ${lvl}</label>`;
                    });
                    dayHtml += `</div></div>`; // إغلاق constraint-box
                });

                dayHtml += `</div></div>`; // إغلاق slot-body و time-slot
            });
            dayHtml += `<button onclick="addSlot('${day.id}')" style="display: block; width: 100%; margin-top: 15px; padding: 10px; background: #34495e; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: bold;">➕ إضافة فترة زمنية جديدة هنا</button>`;
            dayHtml += `</div>`; // إغلاق day-content
            contentContainer.innerHTML += dayHtml;
        }
    });
}

// حفظ الهيكل النهائي في الخادم
function saveStructure() {
    fetch('/api/structure', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(scheduleStructure)
    }).then(res => res.json()).then(data => {
        if(data.success) alert('تم حفظ الهيكل الزمني بنجاح!');
    });
}