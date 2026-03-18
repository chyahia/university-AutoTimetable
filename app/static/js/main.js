// تشغيل دالة المعاينة بمجرد تحميل الصفحة
document.addEventListener('DOMContentLoaded', () => {
    loadPreviews();
});

// دالة مساعدة لتحويل النص
function getLinesFromTextarea(textareaId) {
    return document.getElementById(textareaId).value.split('\n').map(l => l.trim()).filter(l => l.length > 0);
}

// دالة تحديث كافة صناديق المعاينة والقوائم المنسدلة
function loadPreviews() {
    // 1. جلب الأساتذة
    fetch('/teachers').then(res => res.json()).then(data => {
        const box = document.getElementById('teachers-preview');
        if(data.length === 0) { box.innerHTML = '<i>لا يوجد أساتذة...</i>'; } 
        else { box.innerHTML = data.map(t => `<span class="data-tag">${t.name}</span>`).join(''); }
    });

    // 2. جلب القاعات
    fetch('/rooms').then(res => res.json()).then(data => {
        const box = document.getElementById('rooms-preview');
        if(data.length === 0) { box.innerHTML = '<i>لا توجد قاعات...</i>'; } 
        else { box.innerHTML = data.map(r => `<span class="data-tag">${r.name} (${r.type})</span>`).join(''); }
    });

    // 3. جلب المستويات (وتحديث القائمة المنسدلة للمواد)
    fetch('/api/levels').then(res => res.json()).then(data => {
        const box = document.getElementById('levels-preview');
        const select = document.getElementById('course-levels-select');
        
        if(data.length === 0) { 
            box.innerHTML = '<i>لا توجد مستويات...</i>'; 
            select.innerHTML = '<option disabled>أضف مستويات أولاً</option>';
        } else { 
            box.innerHTML = data.map(l => `<span class="data-tag">${l}</span>`).join(''); 
            select.innerHTML = data.map(l => `<option value="${l}">${l}</option>`).join('');
        }
    });

    // 4. جلب المواد
    fetch('/api/courses').then(res => res.json()).then(data => {
        const box = document.getElementById('courses-preview');
        if(data.length === 0) { box.innerHTML = '<i>لا توجد مواد...</i>'; } 
        else { 
            box.innerHTML = data.map(c => `
                <div class="course-tag">
                    <strong>${c.name}</strong> <br>
                    <small>المستويات: ${c.levels || 'غير محدد'} | القاعة: ${c.room_type}</small>
                </div>
            `).join(''); 
        }
    });
}

// إضافة الأساتذة
function addTeachers() {
    const lines = getLinesFromTextarea('teachers-input');
    if (lines.length === 0) return alert('يرجى إدخال اسم أستاذ واحد على الأقل.');
    fetch('/api/teachers', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ names: lines }) })
    .then(res => res.json()).then(data => {
        document.getElementById('teachers-input').value = ''; 
        loadPreviews(); // تحديث المعاينة فوراً
    });
}

// إضافة القاعات
function addRooms() {
    const lines = getLinesFromTextarea('rooms-input');
    const type = document.getElementById('room-type-select').value;
    if (lines.length === 0) return alert('يرجى إدخال اسم قاعة واحدة على الأقل.');
    fetch('/api/rooms', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ names: lines, type: type }) })
    .then(res => res.json()).then(data => {
        document.getElementById('rooms-input').value = ''; 
        loadPreviews(); // تحديث المعاينة فوراً
    });
}

// إضافة المستويات
function addLevels() {
    const lines = getLinesFromTextarea('levels-input');
    if (lines.length === 0) return alert('يرجى إدخال مستوى واحد على الأقل.');
    fetch('/api/levels', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ levels: lines }) })
    .then(res => res.json()).then(data => {
        document.getElementById('levels-input').value = ''; 
        loadPreviews(); // تحديث المعاينة فوراً
    });
}

// إضافة المواد (الجديدة)
function addCourses() {
    const lines = getLinesFromTextarea('courses-input');
    const roomType = document.getElementById('course-room-type-select').value;
    const levelSelect = document.getElementById('course-levels-select');
    // جمع المستويات التي اختارها المستخدم من القائمة المنسدلة
    const selectedLevels = Array.from(levelSelect.selectedOptions).map(opt => opt.value);

    if (lines.length === 0) return alert('يرجى إدخال مادة واحدة على الأقل.');
    if (selectedLevels.length === 0) return alert('يرجى اختيار مستوى واحد على الأقل للمادة.');

    // تجهيز البيانات لتطابق مسار البلاك الذي كتبناه في بايثون
    const coursesData = lines.map(name => ({
        name: name,
        room_type: roomType,
        levels: selectedLevels
    }));

    fetch('/api/students/bulk', { 
        method: 'POST', 
        headers: {'Content-Type': 'application/json'}, 
        body: JSON.stringify(coursesData) 
    })
    .then(res => res.json()).then(data => {
        if(data.success) {
            document.getElementById('courses-input').value = '';
            loadPreviews(); // تحديث المعاينة فوراً
        } else {
            alert('خطأ: ' + data.error);
        }
    });
}