// ================= إدارة الإعدادات المحفوظة (Profiles) والخوارزميات =================

// 1. زر حفظ الإعدادات
document.getElementById('btn-save-settings').addEventListener('click', () => {
    if(typeof saveStructure === 'function' && scheduleStructure && scheduleStructure.length > 0) saveStructure();
    if(typeof saveAllConditions === 'function') saveAllConditions();
    saveAlgorithmSettings();
    alert("تم حفظ إعدادات المراحل (الهيكل، القيود، الخوارزميات) كإعدادات افتراضية.");
});

// دالة حفظ إعدادات المرحلة 6
function saveAlgorithmSettings() {
    // التقاط الخوارزميات المؤشر عليها
    const selectedAlgorithms = Array.from(document.querySelectorAll('.algo-chk:checked')).map(cb => cb.value);

    const algoSettings = {
        selected_algorithms: selectedAlgorithms, // <-- السطر المضاف لحفظ المربعات
        tabu_iterations: document.getElementById('tabu_iter')?.value || 1000,
        tabu_tenure: document.getElementById('tabu_tenure')?.value || 10,
        lns_iterations: document.getElementById('lns_iter')?.value || 500,
        lns_ruin_factor: document.getElementById('lns_ruin')?.value || 20,
        vns_iterations: document.getElementById('vns_iter')?.value || 300,
        vns_k_max: document.getElementById('vns_k')?.value || 5,
        strict_hierarchy: document.getElementById('strict-hierarchy-chk')?.checked || false
    };

    fetch('/api/algorithm-settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(algoSettings)
    });
}

// استرجاع إعدادات الخوارزميات عند تحميل الصفحة
document.addEventListener('DOMContentLoaded', () => {
    fetch('/api/algorithm-settings')
    .then(res => res.json())
    .then(data => {
        if (Object.keys(data).length > 0) {
            
            // استرجاع المربعات المؤشرة (صح)
            if (data.selected_algorithms) {
                document.querySelectorAll('.algo-chk').forEach(chk => {
                    chk.checked = data.selected_algorithms.includes(chk.value);
                    // تفعيل الحدث لإظهار/إخفاء الإعدادات المنسدلة تحتها
                    chk.dispatchEvent(new Event('change')); 
                });
            }

            if(data.tabu_iterations && document.getElementById('tabu_iter')) document.getElementById('tabu_iter').value = data.tabu_iterations;
            if(data.tabu_tenure && document.getElementById('tabu_tenure')) document.getElementById('tabu_tenure').value = data.tabu_tenure;
            if(data.lns_iterations && document.getElementById('lns_iter')) document.getElementById('lns_iter').value = data.lns_iterations;
            if(data.lns_ruin_factor && document.getElementById('lns_ruin')) document.getElementById('lns_ruin').value = data.lns_ruin_factor;
            if(data.vns_iterations && document.getElementById('vns_iter')) document.getElementById('vns_iter').value = data.vns_iterations;
            if(data.vns_k_max && document.getElementById('vns_k')) document.getElementById('vns_k').value = data.vns_k_max;
            if(data.strict_hierarchy !== undefined && document.getElementById('strict-hierarchy-chk')) {
                document.getElementById('strict-hierarchy-chk').checked = data.strict_hierarchy;
            }
        }
    });
});

// ================= نظام "حفظ باسم" و "استعادة" القوي =================

// 2. زر "حفظ باسم" (يقرأ من الخادم مباشرة لتفادي النقص)
document.getElementById('btn-save-as').addEventListener('click', async () => {
    const profileName = prompt("أدخل اسماً لهذه الإعدادات (مثال: إعدادات الفصل الأول):");
    if (!profileName) return;

    try {
        // جلب البيانات من الخادم لضمان أنها كاملة ومحدثة
        const structRes = await fetch('/api/structure');
        const structure = await structRes.json();
        
        const condRes = await fetch('/api/conditions');
        const conditions = await condRes.json();
        
        const algoRes = await fetch('/api/algorithm-settings');
        const algorithms = await algoRes.json();

        // تجميع اللقطة
        const snapshot = {
            name: profileName,
            structure: structure,
            conditions: conditions,
            algorithms: algorithms
        };
        
        // حفظ اللقطة في LocalStorage
        let profiles = JSON.parse(localStorage.getItem('schedule_profiles') || '{}');
        profiles[profileName] = snapshot;
        localStorage.setItem('schedule_profiles', JSON.stringify(profiles));
        
        alert(`تم حفظ الإعدادات باسم: "${profileName}" بنجاح!`);
    } catch (e) {
        alert("حدث خطأ أثناء الحفظ باسم: " + e);
    }
});

// 3. زر "استعادة" (يرسل البيانات للخادم ثم يحدّث الصفحة)
document.getElementById('btn-restore').addEventListener('click', async () => {
    const profiles = JSON.parse(localStorage.getItem('schedule_profiles') || '{}');
    const profileNames = Object.keys(profiles);
    
    if (profileNames.length === 0) {
        alert("لا توجد إعدادات محفوظة مسبقاً لاستعادتها.");
        return;
    }

    let message = "اختر رقم الإعدادات التي تريد استعادتها:\n\n";
    profileNames.forEach((name, index) => {
        message += `${index + 1}. ${name}\n`;
    });

    const choice = prompt(message);
    if(!choice) return; // تم الإلغاء
    const selectedIndex = parseInt(choice) - 1;

    if (!isNaN(selectedIndex) && selectedIndex >= 0 && selectedIndex < profileNames.length) {
        const selectedName = profileNames[selectedIndex];
        const data = profiles[selectedName];
        
        try {
            // استبدال الإعدادات الحالية في الخادم بالبيانات المسترجعة
            if(data.structure) await fetch('/api/structure', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data.structure)});
            if(data.conditions) await fetch('/api/conditions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data.conditions)});
            if(data.algorithms) await fetch('/api/algorithm-settings', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data.algorithms)});
            
            alert(`تمت استعادة إعدادات "${selectedName}" بنجاح! سيتم تحديث الصفحة الآن لتطبيقها.`);
            window.location.reload(); // تحديث إجباري لإظهار التغييرات في كل التبويبات
        } catch(e) {
            alert("حدث خطأ أثناء الاستعادة: " + e);
        }
    } else {
        alert("رقم غير صحيح، تم إلغاء الاستعادة.");
    }
});

// 4. زر "حذف إعدادات" (لمسح البروفايلات المحفوظة سابقاً)
const btnDeleteProfile = document.getElementById('btn-delete-profile');
if (btnDeleteProfile) {
    btnDeleteProfile.addEventListener('click', () => {
        const profiles = JSON.parse(localStorage.getItem('schedule_profiles') || '{}');
        const profileNames = Object.keys(profiles);
        
        if (profileNames.length === 0) {
            alert("لا توجد إعدادات محفوظة مسبقاً لحذفها.");
            return;
        }

        let message = "اختر رقم الإعدادات التي تريد حذفها نهائياً:\n\n";
        profileNames.forEach((name, index) => {
            message += `${index + 1}. ${name}\n`;
        });

        const choice = prompt(message);
        if(!choice) return; // تم الإلغاء
        
        const selectedIndex = parseInt(choice) - 1;

        if (!isNaN(selectedIndex) && selectedIndex >= 0 && selectedIndex < profileNames.length) {
            const selectedName = profileNames[selectedIndex];
            
            // رسالة تأكيد إضافية قبل الحذف
            if(confirm(`هل أنت متأكد جداً من أنك تريد حذف إعدادات "${selectedName}"؟ لا يمكن التراجع عن هذا الإجراء.`)) {
                // حذف الإعداد من الكائن
                delete profiles[selectedName];
                
                // حفظ الكائن الجديد في المتصفح
                localStorage.setItem('schedule_profiles', JSON.stringify(profiles));
                
                alert(`تم حذف إعدادات "${selectedName}" بنجاح!`);
            }
        } else {
            alert("رقم غير صحيح، تم إلغاء الحذف.");
        }
    });
}