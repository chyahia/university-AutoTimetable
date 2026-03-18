let currentGenerationData = null; // لتخزين البيانات عند انتهاء الخوارزمية لاستخدامها في التصدير
let eventSource = null;

// (جزء من app/static/js/generation.js)

// --- دالة مساعدة لتحديد لون شريط التقدم بناءً على النسبة ---
function getProgressBarColor(percentage) {
    percentage = parseInt(percentage);
    if (percentage < 40) {
        return '#e74c3c'; // أحمر (10-30%)
    } else if (percentage < 70) {
        return '#e67e22'; // برتقالي (40-60%)
    } else {
        return '#27ae60'; // أخضر (70-100%)
    }
}

// --- الدالة المعدلة بالكامل لـ startGeneration ---
function startGeneration() {
    const selectedAlgorithms = Array.from(document.querySelectorAll('.algo-chk:checked')).map(cb => cb.value);
    const strictHierarchy = document.getElementById('strict-hierarchy-chk')?.checked || false;
    const algoSettings = {
        tabu_iterations: document.getElementById('tabu_iter')?.value,
        tabu_tenure: document.getElementById('tabu_tenure').value,
        lns_iterations: document.getElementById('lns_iter').value,
        lns_ruin_factor: document.getElementById('lns_ruin').value,
        vns_iterations: document.getElementById('vns_iter').value,
        vns_k_max: document.getElementById('vns_k').value
    };

    if (selectedAlgorithms.length === 0) {
        alert("يرجى اختيار خوارزمية مساعدة واحدة على الأقل!");
        return;
    }

    const btnStart = document.getElementById('btn-start-gen');
    const btnStop = document.getElementById('btn-stop-gen');
    const logContainer = document.getElementById('live-log-container');
    const logOutput = document.getElementById('log-output');
    const resultsContainer = document.getElementById('schedule-results-container');
    
    // --- تصفير شريط التقدم وإخفائه عند بدء محاولة جديدة مع لون أولي أحمر ---
    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    if (progressContainer && progressBar) {
        progressContainer.style.display = 'none';
        progressBar.style.width = '0%';
        progressBar.style.backgroundColor = getProgressBarColor(0); // تطبيق اللون الأولي
        progressBar.textContent = '0%';
    }

    // تجهيز الواجهة للبدء
    btnStart.style.display = 'none';
    btnStop.style.display = 'block';
    btnStop.innerText = '🛑 إيقاف البحث';
    btnStop.disabled = false;
    resultsContainer.style.display = 'none';
    
    logContainer.style.display = 'block';
    logOutput.textContent = 'بدء الاتصال بالخادم وإرسال البيانات...\n';

    // طلب بدء الخوارزمية
    fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            strict_hierarchy: strictHierarchy,
            algorithms: selectedAlgorithms,
            settings: algoSettings
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success || data.status === 'ok') {
            logOutput.textContent += 'تم بدء العملية. جاري استقبال المتابعة الحية...\n';
            
            // فتح قناة استقبال السجل الحي (Server-Sent Events)
            eventSource = new EventSource('/stream-logs');
            
            eventSource.onmessage = function(event) {
                const message = event.data;
                
                // الكلمة المفتاحية "DONE" تعني انتهاء الخوارزمية
                if (message.startsWith("DONE")) {
                    eventSource.close();
                    const jsonData = message.substring(4);
                    
                    if (jsonData.trim().length > 0) {
                        try {
                            const parsedData = JSON.parse(jsonData);
                            currentGenerationData = parsedData; // تخزين البيانات لأزرار التصدير
                            
                            logOutput.textContent += '\n--- اكتملت عملية الجدولة بنجاح! ---\n';
                            
                            // --- حساب النسبة النهائي (مطابق تماماً لمنطق البايثون الذكي) ---
                            const finalFailures = parsedData.final_failures || [];
                            let hardErrorsCount = 0;
                            let softErrorsCount = 0;
                            
                            // فرز الأخطاء لمعرفة الصارم من المرن
                            finalFailures.forEach(f => {
                                const penalty = f.penalty !== undefined ? f.penalty : 1;
                                if (penalty >= 100) {
                                    hardErrorsCount++;
                                } else {
                                    softErrorsCount++;
                                }
                            });
                            
                            let finalPercentage = 0;
                            
                            // تطبيق نفس منطق البايثون:
                            // 1. إذا كان هناك أخطاء صارمة، التقدم هو 0 (أو 5% ليبقى الشريط ظاهراً)
                            if (hardErrorsCount > 0) {
                                finalPercentage = 5; 
                            } else {
                                // 2. إذا بقيت أخطاء مرنة فقط، نحسبها (كل خطأ يخصم 10%)
                                finalPercentage = Math.max(0, ((10 - softErrorsCount) / 10) * 100);
                                finalPercentage = Math.max(5, finalPercentage); // حد أدنى 5%
                            }

                            // تحديث الشريط باللون والنسبة الواقعية
                            if (progressContainer && progressBar) {
                                progressBar.style.width = finalPercentage + '%';
                                progressBar.style.backgroundColor = getProgressBarColor(finalPercentage);
                                
                                let errorText = "";
                                if (hardErrorsCount > 0) {
                                    errorText = ` (باقي ${hardErrorsCount} صارم و ${softErrorsCount} مرن)`;
                                } else if (softErrorsCount > 0) {
                                    errorText = ` (باقي ${softErrorsCount} مرن)`;
                                }
                                
                                progressBar.textContent = finalPercentage + '%' + errorText;
                            }
                            // ----------------------------------------------------------------
                            // ----------------------------------------------------------------------
                            
                            // إعادة الواجهة لحالة الانتهاء
                            btnStop.style.display = 'none';
                            btnStart.style.display = 'block';
                            btnStart.innerText = '🔄 إعادة الجدولة مرة أخرى';
                            
                            // إظهار النتائج وأزرار التصدير ورسم جداول المستويات
                            resultsContainer.style.display = 'block';
                            renderLevelSchedules(parsedData.schedule, parsedData.days, parsedData.slots);
                            
                        } catch(e) {
                            console.error("Error parsing DONE JSON:", e);
                            logOutput.textContent += '\nحدث خطأ أثناء قراءة النتيجة النهائية.\n';
                        }
                    }
                } 
                // --- إضافة: التقاط شريط التقدم وتحديث اللون ديناميكياً هنا ---
                else if (message.includes("PROGRESS:")) {
                    if (progressContainer && progressBar) {
                        let percentage = message.replace("PROGRESS:", "").trim();
                        progressContainer.style.display = 'block';
                        progressBar.style.width = percentage + '%';
                        progressBar.style.backgroundColor = getProgressBarColor(percentage); // تحديث اللون ديناميكياً
                        progressBar.textContent = percentage + '%';
                    }
                } 
                // ------------------------------------
                else {
                    // طباعة الرسالة الحية في الشاشة السوداء إذا لم تكن DONE أو PROGRESS
                    logOutput.textContent += message + '\n';
                    logOutput.scrollTop = logOutput.scrollHeight; // التمرير التلقائي للأسفل
                }
            };
            
            eventSource.onerror = function() {
                logOutput.textContent += '\n--- انقطع الاتصال بالخادم (قد تكون العملية انتهت أو توقفت). ---\n';
                eventSource.close();
                btnStop.style.display = 'none';
                btnStart.style.display = 'block';
                btnStart.innerText = '🔄 بدء محاولة جديدة';
            };
            
        } else {
            alert("حدث خطأ في بدء الخوارزمية:\n" + data.error);
            btnStop.style.display = 'none';
            btnStart.style.display = 'block';
        }
    }).catch(err => {
        console.error("Error:", err);
        alert("حدث خطأ في الاتصال بالخادم.");
        btnStop.style.display = 'none';
        btnStart.style.display = 'block';
    });
}
function stopGeneration() {
    if(confirm("هل أنت متأكد من إيقاف الخوارزمية؟ قد لا يتم حفظ النتائج الحالية.")) {
        fetch('/api/stop-generation', { method: 'POST' });
        const btnStop = document.getElementById('btn-stop-gen');
        btnStop.textContent = '⏳ جاري الإيقاف، يرجى الانتظار...';
        btnStop.disabled = true;
    }
}

// دالة رسم جداول المستويات (حصرياً) كما طلبت
function renderLevelSchedules(scheduleData, days, slots) {
    const outputDiv = document.getElementById('rendered-tables');
    outputDiv.innerHTML = ''; 

    if (!scheduleData || Object.keys(scheduleData).length === 0) {
        outputDiv.innerHTML = '<h3 style="text-align:center;">لم يتم إنشاء أي جداول أو البيانات فارغة.</h3>';
        return;
    }

    const sortedLevels = Object.keys(scheduleData).sort();
    
    for (const level of sortedLevels) {
        const grid = scheduleData[level];
        if (grid.length === 0) continue; 

        const container = document.createElement('div');
        container.style.marginBottom = '30px';
        container.style.border = '1px solid #34495e';
        container.style.borderRadius = '5px';
        container.style.overflow = 'hidden';

        const title = document.createElement('h3');
        title.style.backgroundColor = '#34495e';
        title.style.color = 'white';
        title.style.margin = '0';
        title.style.padding = '10px';
        title.textContent = "جدول: " + level;
        container.appendChild(title);

        const table = document.createElement('table');
        table.style.width = '100%';
        table.style.borderCollapse = 'collapse';
        table.style.textAlign = 'center';

        // رأس الجدول (الأيام)
        const thead = table.createTHead();
        const headerRow = thead.insertRow();
        headerRow.innerHTML = '<th style="padding:10px; background:#ecf0f1; border:1px solid #ccc;">الوقت</th>';
        days.forEach(day => headerRow.innerHTML += `<th style="padding:10px; background:#ecf0f1; border:1px solid #ccc;">${day}</th>`);

        // محتوى الجدول (الفترات والمواد)
        const tbody = table.createTBody();
        slots.forEach((slot, slotIdx) => {
            const row = tbody.insertRow();
            row.insertCell().innerHTML = `<strong style="display:block; padding:10px; border:1px solid #ccc; background:#fafafa;">${slot}</strong>`;
            
            days.forEach((day, dayIdx) => {
                const cell = row.insertCell();
                cell.style.border = '1px solid #ccc';
                cell.style.padding = '8px';
                cell.style.verticalAlign = 'top';
                
                const lecturesInCell = grid[dayIdx] ? grid[dayIdx][slotIdx] : [];
                if (lecturesInCell && lecturesInCell.length > 0) {
                    cell.innerHTML = lecturesInCell.map(lec => `
                        <div style="background:#e8f4f8; border:1px solid #3498db; border-radius:4px; padding:8px; margin-bottom:5px; font-size:13px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                            <strong style="color:#2980b9;">${lec.name}</strong><br>
                            <span style="color:#2c3e50;">${lec.teacher_name}</span><br>
                            <small style="color:#e67e22; font-weight:bold;">${lec.room}</small>
                        </div>
                    `).join('');
                } else {
                    cell.innerHTML = '<span style="color:#bdc3c7;">-</span>';
                }
            });
        });
        
        container.appendChild(table);
        outputDiv.appendChild(container);
    }
}

// ================= أزرار التصدير (نفس المسارات التي في app.py) =================

function exportFiles(url, fileName, isProfessor = false, isFreeRoom = false) {
    if (!currentGenerationData) { alert('لا توجد بيانات مصدرة. يرجى توليد الجدول أولاً.'); return; }
    
    // تحديد البيانات المطلوبة بناءً على نوع التصدير
    let scheduleToSend = currentGenerationData.schedule;
    if (isProfessor) scheduleToSend = currentGenerationData.prof_schedules;
    if (isFreeRoom) scheduleToSend = currentGenerationData.free_rooms;

    const payload = {
        schedule: scheduleToSend,
        days: currentGenerationData.days,
        slots: currentGenerationData.slots
    };

    fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.blob())
    .then(blob => triggerDownload(blob, fileName))
    .catch(err => alert("خطأ في التصدير: " + err));
}

function exportPedagogicalLoad() {
    // العبء البيداغوجي يستخدم مسار GET لأنه يقرأ من قاعدة البيانات مباشرة (كما في مشروعك)
    fetch('/api/export/teaching-load')
    .then(res => res.blob())
    .then(blob => triggerDownload(blob, 'العبء_البيداغوجي.xlsx'))
    .catch(err => alert("خطأ في تصدير العبء البيداغوجي: " + err));
}

// دالة مساعدة لعملية تنزيل الملف فعلياً في المتصفح
function triggerDownload(blob, fileName) {
    const downloadUrl = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = downloadUrl;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    window.URL.revokeObjectURL(downloadUrl);
    document.body.removeChild(a);
}

// ==========================================
// دوال حفظ واستعادة الجداول (الذاكرة المحلية)
// ==========================================

function saveResult(slotNumber) {
    if (!currentGenerationData || !currentGenerationData.schedule) {
        alert("لا توجد نتيجة حالية لحفظها! يرجى توليد جدول أولاً.");
        return;
    }
    
    // تحويل الجدول إلى نص وحفظه في ذاكرة المتصفح
    localStorage.setItem('savedSchedule_' + slotNumber, JSON.stringify(currentGenerationData));
    alert("✅ تم حفظ النتيجة الحالية في [الذاكرة رقم " + slotNumber + "] بنجاح!");
    
    // إظهار زر الاستعادة المقابل
    document.getElementById('btn-restore-' + slotNumber).style.display = 'inline-block';
}

function restoreResult(slotNumber) {
    const savedData = localStorage.getItem('savedSchedule_' + slotNumber);
    if (savedData) {
        // استرجاع البيانات وتحويلها لجدول
        currentGenerationData = JSON.parse(savedData);
        
        // إعادة رسم الجداول على الشاشة
        renderLevelSchedules(currentGenerationData.schedule, currentGenerationData.days, currentGenerationData.slots);
        alert("📂 تمت استعادة [النتيجة رقم " + slotNumber + "] بنجاح!");
    } else {
        alert("لا توجد نتيجة محفوظة في هذه الذاكرة.");
    }
}

// فحص عند تحميل الصفحة: إذا كان هناك جداول محفوظة مسبقاً، أظهر أزرار الاستعادة
document.addEventListener('DOMContentLoaded', function() {
    if (localStorage.getItem('savedSchedule_1')) {
        const btn1 = document.getElementById('btn-restore-1');
        if(btn1) btn1.style.display = 'inline-block';
    }
    if (localStorage.getItem('savedSchedule_2')) {
        const btn2 = document.getElementById('btn-restore-2');
        if(btn2) btn2.style.display = 'inline-block';
    }
});

// ==========================================
// دالة تشغيل التحسين والضغط
// ==========================================
function refineSchedule() {
    if (!currentGenerationData || !currentGenerationData.schedule) {
        alert("يرجى توليد جدول أولاً قبل محاولة تحسينه!");
        return;
    }

    // ✨ 1. جلب مستوى التحسين من أزرار الراديو (Radio Buttons) في واجهتك
    const levelRadio = document.querySelector('input[name="opt_level"]:checked');
    const selectedLevel = levelRadio ? levelRadio.value : 'balanced';

    // ✨ 2. جلب الأساتذة المحددين من الحاوية الخاصة بهم
    // نبحث عن كل مربع اختيار تم تأشيره داخل الحاوية optimization-teachers
    const teacherCheckboxes = document.querySelectorAll('#optimization-teachers input[type="checkbox"]:checked');
    const selectedTeachers = Array.from(teacherCheckboxes).map(cb => cb.value);

    const logContainer = document.getElementById('live-log-container');
    const logOutput = document.getElementById('log-output');
    const resultsContainer = document.getElementById('schedule-results-container');
    const btnRefine = document.getElementById('btn-refine');
    
    // إخفاء النتائج وإظهار الشاشة السوداء
    resultsContainer.style.display = 'none';
    logContainer.style.display = 'block';
    
    // ترجمة اسم المستوى للغة العربية لطباعته في الشاشة السوداء
    let levelNameAr = selectedLevel === 'simple' ? 'بسيط' : (selectedLevel === 'deep' ? 'عميق' : 'متوازن');
    let teachersText = selectedTeachers.length > 0 ? `لعدد ${selectedTeachers.length} أساتذة` : 'لجميع الأساتذة';
    
    logOutput.textContent = `🚀 جاري الاتصال بالخادم لضغط وتحسين أوقات الأساتذة...\n`;
    logOutput.textContent += `⚙️ المستوى: [${levelNameAr}] | النطاق: [${teachersText}]\n\n`;
    
    // إيقاف الزر مؤقتاً
    btnRefine.disabled = true;
    btnRefine.innerText = '⏳ جاري التحسين...';

    fetch('/api/refine', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
            schedule: currentGenerationData.schedule,
            level: selectedLevel,       // ✨ إرسال المستوى المختار
            teachers: selectedTeachers  // ✨ إرسال الأساتذة المحددين
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            const refineEventSource = new EventSource('/stream-logs');
            
            refineEventSource.onmessage = function(event) {
                const message = event.data;
                
                if (message.startsWith("DONE")) {
                    refineEventSource.close();
                    const jsonData = message.substring(4);
                    
                    try {
                        const parsedData = JSON.parse(jsonData);
                        currentGenerationData = parsedData; 
                        
                        logOutput.textContent += '\n--- ✨ اكتملت عملية التحسين وسد الفجوات بنجاح! ---\n';
                        
                        btnRefine.disabled = false;
                        btnRefine.innerText = '✨ ضغط وتحسين جداول الأساتذة (سد الفجوات)';
                        resultsContainer.style.display = 'block';
                        
                        renderLevelSchedules(parsedData.schedule, parsedData.days, parsedData.slots);
                        alert("✨ تم ضغط الجداول بنجاح! يمكنك الآن مراجعتها أو تصديرها.");
                        
                    } catch(e) {
                        console.error("Error parsing DONE JSON:", e);
                    }
                } else if (!message.includes("PROGRESS:")) {
                    logOutput.textContent += message + '\n';
                    logOutput.scrollTop = logOutput.scrollHeight;
                }
            };
            
            refineEventSource.onerror = function() {
                refineEventSource.close();
                btnRefine.disabled = false;
                btnRefine.innerText = '✨ ضغط وتحسين جداول الأساتذة (سد الفجوات)';
            };
        } else {
            alert("حدث خطأ: " + data.error);
            btnRefine.disabled = false;
            btnRefine.innerText = '✨ ضغط وتحسين جداول الأساتذة (سد الفجوات)';
        }
    })
    .catch(err => {
        console.error("Error:", err);
        alert("حدث خطأ في الاتصال.");
        btnRefine.disabled = false;
        btnRefine.innerText = '✨ ضغط وتحسين جداول الأساتذة (سد الفجوات)';
    });
}