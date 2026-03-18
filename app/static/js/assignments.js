let assig_teachers = [];
let assig_courses = [];
let selectedTeacherId = null;
let selectedCourseIds = new Set(); // نستخدم Set لمنع التكرار

// جلب البيانات من الخادم
function loadAssignmentsData() {
    fetch('/api/assignments/data')
        .then(res => res.json())
        .then(data => {
            assig_teachers = data.teachers;
            assig_courses = data.courses;
            // تصفير الاختيارات بعد كل تحديث
            selectedTeacherId = null;
            selectedCourseIds.clear();
            updateAssignButton();
            renderAssignments();
        });
}

// رسم القوائم بناءً على البحث والبيانات
function renderAssignments() {
    const teacherSearch = document.getElementById('search-teachers').value.toLowerCase();
    const courseSearch = document.getElementById('search-courses').value.toLowerCase();
    
    const teachersListEl = document.getElementById('assign-teachers-list');
    const coursesListEl = document.getElementById('assign-courses-list');
    
    teachersListEl.innerHTML = '';
    coursesListEl.innerHTML = '';

    // 1. رسم الأساتذة
    assig_teachers.forEach(teacher => {
        if(!teacher.name.toLowerCase().includes(teacherSearch)) return;
        
        // جلب المواد المسندة حالياً لهذا الأستاذ
        const teacherCourses = assig_courses.filter(c => c.teacher_id === teacher.id);
        const hasAssigned = teacherCourses.length > 0;
        
        const isSelected = teacher.id === selectedTeacherId;
        const classes = `list-item ${isSelected ? 'is-selected' : ''} ${hasAssigned ? 'is-assigned' : ''}`;
        
        const countText = hasAssigned ? ` <span style="color:#e67e22; font-size:12px;">(${teacherCourses.length})</span>` : '';
        let html = `<div class="${classes}" id="t-item-${teacher.id}">
            <div>
                <span class="toggle-btn" onclick="toggleTeacherList(${teacher.id}, event)">▶</span>
                <strong onclick="selectTeacher(${teacher.id})" ondblclick="unassignTeacher(${teacher.id})">${teacher.name}${countText}</strong>
            </div>`;
            
        // إضافة القائمة المنسدلة المخفية (المثلث)
        if(hasAssigned) {
            html += `<ul class="teacher-courses-list" id="t-list-${teacher.id}">
                        ${teacherCourses.map(c => `<li>${c.name} (${c.levels || ''})</li>`).join('')}
                     </ul>`;
        }
        html += `</div>`;
        teachersListEl.innerHTML += html;
    });

    // 2. رسم المواد
    assig_courses.forEach(course => {
        if(!course.name.toLowerCase().includes(courseSearch)) return;
        
        const isSelected = selectedCourseIds.has(course.id);
        const hasAssigned = course.teacher_id !== null;
        const classes = `list-item ${isSelected ? 'is-selected' : ''} ${hasAssigned ? 'is-assigned' : ''}`;
        
        let html = `<div class="${classes}" onclick="selectCourse(${course.id})" ondblclick="unassignCourse(${course.id}, event)">
            <strong>${course.name}</strong> <small style="color:#7f8c8d;">(${course.levels || 'بدون مستوى'})</small>`;
            
        if(hasAssigned) {
            html += `<span class="teacher-badge">${course.teacher_name}</span>`;
        }
        html += `</div>`;
        coursesListEl.innerHTML += html;
    });
}

// تحديد الأستاذ
function selectTeacher(id) {
    selectedTeacherId = id;
    updateAssignButton();
    renderAssignments();
}

// تحديد أو إلغاء تحديد المادة للتخصيص
function selectCourse(id) {
    if(selectedCourseIds.has(id)) {
        selectedCourseIds.delete(id);
    } else {
        selectedCourseIds.add(id);
    }
    updateAssignButton();
    renderAssignments();
}

// فتح وإغلاق قائمة مواد الأستاذ (المثلث)
function toggleTeacherList(id, event) {
    event.stopPropagation(); // منع تفعيل تحديد الأستاذ عند ضغط المثلث
    const list = document.getElementById(`t-list-${id}`);
    const btn = event.target;
    if(list) {
        if(list.style.display === 'block') {
            list.style.display = 'none';
            btn.innerText = '▶';
        } else {
            list.style.display = 'block';
            btn.innerText = '▼';
        }
    }
}

// تفعيل/تعطيل زر التخصيص
function updateAssignButton() {
    const btn = document.getElementById('main-assign-btn');
    btn.disabled = !(selectedTeacherId !== null && selectedCourseIds.size > 0);
}

// إرسال طلب التخصيص (الإسناد)
function performAssignment() {
    if(selectedTeacherId === null || selectedCourseIds.size === 0) return;
    
    fetch('/api/assignments/assign', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            teacher_id: selectedTeacherId,
            course_ids: Array.from(selectedCourseIds)
        })
    }).then(res => res.json()).then(data => {
        if(data.success) loadAssignmentsData();
    });
}

// إلغاء إسناد مادة (نقر مزدوج)
function unassignCourse(id, event) {
    event.stopPropagation(); // لمنع تفعيل الاختيار الفردي
    fetch(`/api/assignments/unassign_course/${id}`, { method: 'POST' })
    .then(res => res.json()).then(data => {
        if(data.success) loadAssignmentsData();
    });
}

// إلغاء إسناد كل مواد الأستاذ (نقر مزدوج)
function unassignTeacher(id) {
    if(!confirm('هل أنت متأكد من إلغاء إسناد جميع المواد لهذا الأستاذ؟')) return;
    fetch(`/api/assignments/unassign_teacher/${id}`, { method: 'POST' })
    .then(res => res.json()).then(data => {
        if(data.success) loadAssignmentsData();
    });
}