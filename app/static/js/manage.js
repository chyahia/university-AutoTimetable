// دالة لجلب البيانات وتعبئة الجداول (محدثة بأزرار التعديل)
function loadManageTables() {
    // 1. جدول الأساتذة
    fetch('/teachers').then(res => res.json()).then(data => {
        const tbody = document.querySelector('#teachers-table tbody');
        tbody.innerHTML = data.map(t => `<tr><td>${t.name}</td><td>
            <button onclick="editItem('/api/teachers/${t.id}', '${t.name}')" class="btn-edit">تعديل</button>
            <button onclick="deleteItem('/api/teachers/${t.id}')" class="btn-delete">حذف</button>
        </td></tr>`).join('');
    });

    // 2. جدول القاعات
    fetch('/rooms').then(res => res.json()).then(data => {
        const tbody = document.querySelector('#rooms-table tbody');
        tbody.innerHTML = data.map(r => `<tr><td>${r.name}</td><td>${r.type}</td><td>
            <button onclick="editItem('/api/rooms/${r.id}', '${r.name}')" class="btn-edit">تعديل</button>
            <button onclick="deleteItem('/api/rooms/${r.id}')" class="btn-delete">حذف</button>
        </td></tr>`).join('');
    });

    // 3. جدول المستويات
    fetch('/api/levels').then(res => res.json()).then(data => {
        const tbody = document.querySelector('#levels-table tbody');
        tbody.innerHTML = data.map(l => `<tr><td>${l}</td><td>
            <button onclick="editItem('/api/levels/${encodeURIComponent(l)}', '${l}')" class="btn-edit">تعديل</button>
            <button onclick="deleteItem('/api/levels/${encodeURIComponent(l)}')" class="btn-delete">حذف</button>
        </td></tr>`).join('');
    });

    // 4. جدول المواد
    fetch('/api/courses').then(res => res.json()).then(data => {
        const tbody = document.querySelector('#courses-table tbody');
        tbody.innerHTML = data.map(c => `<tr><td>${c.name}</td><td>${c.levels || 'غير محدد'}</td><td>${c.room_type}</td><td>
            <button onclick="editItem('/api/courses/${c.id}', '${c.name}')" class="btn-edit">تعديل</button>
            <button onclick="deleteItem('/api/courses/${c.id}')" class="btn-delete">حذف</button>
        </td></tr>`).join('');
    });
}

// دالة التعديل (الجديدة)
function editItem(url, oldName) {
    // إظهار نافذة صغيرة تطلب من المستخدم إدخال الاسم الجديد
    const newName = prompt("أدخل الاسم الجديد:", oldName);
    
    // التحقق من أن المستخدم أدخل اسماً جديداً ولم يضغط "إلغاء"
    if (newName !== null && newName.trim() !== "" && newName !== oldName) {
        fetch(url, { 
            method: 'PUT',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name: newName.trim() })
        })
        .then(res => res.json())
        .then(data => {
            if(data.success) {
                loadManageTables(); // تحديث الجداول فوراً
                if(typeof loadPreviews === 'function') loadPreviews(); // تحديث المعاينة في المرحلة 1
            } else {
                alert('خطأ: ' + data.error);
            }
        });
    }
}

// دالة الحذف الموحدة
function deleteItem(url) {
    if(confirm('هل أنت متأكد من حذف هذا العنصر؟ (سيتم حذف أي ارتباطات له)')) {
        fetch(url, { method: 'DELETE' })
        .then(res => res.json())
        .then(data => {
            if(data.success) {
                loadManageTables(); // تحديث الجداول
                if(typeof loadPreviews === 'function') loadPreviews(); // تحديث المعاينة في المرحلة 1 إن أمكن
            }
        });
    }
}