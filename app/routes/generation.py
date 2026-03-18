from flask import Blueprint, request, jsonify, Response
import threading
import time
import json
import traceback
import sqlite3
import copy

# استدعاء المتغير العام ودالة السجل والخوارزميات من ملفك
from app.services.algorithms import (
    SCHEDULING_STATE, log_message,
    run_tabu_search, run_large_neighborhood_search, run_variable_neighborhood_search, 
    run_greedy_search_for_best_result, refine_and_compact_schedule
)
from app.database import DATABASE_FILE

generation_bp = Blueprint('generation', __name__)

class LogQueueWrapper:
    def put(self, msg):
        log_message(msg)

def background_generation_task(strict_hierarchy, algorithms, algo_settings):
    SCHEDULING_STATE["is_running"] = True
    SCHEDULING_STATE["should_stop"] = False
    SCHEDULING_STATE["logs"] = []
    log_q = LogQueueWrapper()

    try:
        log_message("🚀 بدء جلب البيانات من قاعدة البيانات وإعداد الهيكل الأولي...")
        
        # 1. الاتصال بقاعدة البيانات داخل الـ Thread
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # 2. جلب البيانات الأساسية
        teachers = [dict(row) for row in cur.execute('SELECT * FROM teachers').fetchall()]
        rooms_data = [dict(row) for row in cur.execute('SELECT * FROM rooms').fetchall()]
        levels = [row['name'] for row in cur.execute('SELECT name FROM levels ORDER BY name').fetchall()]
        
        # جلب المواد وربطها بالمستويات
        courses_raw = cur.execute('''
            SELECT c.id, c.name, c.room_type, t.name as teacher_name, group_concat(l.name, ',') as level_names
            FROM courses c
            LEFT JOIN teachers t ON c.teacher_id = t.id
            LEFT JOIN course_levels cl ON c.id = cl.course_id
            LEFT JOIN levels l ON cl.level_id = l.id
            GROUP BY c.id
        ''').fetchall()
        
        all_lectures = []
        from collections import defaultdict
        lectures_by_teacher_map = defaultdict(list)
        
        for c in courses_raw:
            lec = dict(c)
            lec['levels'] = lec['level_names'].split(',') if lec['level_names'] else []
            
            # --- توحيد التسميات لكي تفهمها الخوارزمية تماماً ---
            if lec['room_type'] in ['عادية', 'قاعة', 'صغيرة']: 
                lec['room_type'] = 'صغيرة'
            elif lec['room_type'] in ['مدرج', 'كبيرة']: 
                lec['room_type'] = 'كبيرة'
            # --------------------------------------------------
            
            all_lectures.append(lec)
            if lec.get('teacher_name'):
                lectures_by_teacher_map[lec['teacher_name']].append(lec)
        
        lectures_by_teacher_map['__all_lectures__'] = all_lectures

        for r in rooms_data:
            # --- توحيد التسميات للقاعات أيضاً ---
            if r['type'] in ['عادية', 'قاعة', 'صغيرة']: 
                r['type'] = 'صغيرة'
            elif r['type'] in ['مدرج', 'كبيرة']: 
                r['type'] = 'كبيرة'
            # ------------------------------------

        # 3. جلب الهيكل (المرحلة 4) والقيود (المرحلة 5)
        struct_row = cur.execute("SELECT value FROM settings WHERE key='schedule_structure'").fetchone()
        cond_row = cur.execute("SELECT value FROM settings WHERE key='schedule_conditions'").fetchone()
        
        structure_data = json.loads(struct_row['value']) if struct_row else []
        conditions_data = json.loads(cond_row['value']) if cond_row else {}

        if not structure_data:
            raise Exception("لم يتم إعداد هيكل الجدول (المرحلة 4).")

        # 4. ترجمة الهيكل للخوارزمية
        days = [d['name'] for d in structure_data]
        day_to_idx = {d: i for i, d in enumerate(days)}
        slots = []
        if structure_data and structure_data[0].get('slots'):
            slots = [f"{s['start']}-{s['end']}" for s in structure_data[0]['slots']]
        
        rules_grid = [[[] for _ in slots] for _ in days]
        for d_idx, day_obj in enumerate(structure_data):
            for s_idx, slot_obj in enumerate(day_obj.get('slots', [])):
                for constr in slot_obj.get('constraints', []):
                    rule_type = 'ANY_HALL'
                    if constr['room_rule'] == 'regular': rule_type = 'SMALL_HALLS_ONLY'
                    elif constr['room_rule'] == 'specific': rule_type = 'SPECIFIC_LARGE_HALL'
                    elif constr['room_rule'] == 'none': rule_type = 'NO_HALLS_ALLOWED'
                    
                    rules_grid[d_idx][s_idx].append({
                        'rule_type': rule_type,
                        'levels': constr['levels'],
                        'hall_name': constr['specific_halls'][0] if constr['specific_halls'] else None
                    })

        # 5. ترجمة القيود (المرحلة 5)
        identifiers_by_level = conditions_data.get('identifiers', {})
        teacher_rules = conditions_data.get('teacher_rules', {})
        global_rules = conditions_data.get('global', {})
        weights = conditions_data.get('weights', {})
        spec_teachers = conditions_data.get('special_teachers', {})
        
        # تجهيز متغيرات الخوارزمية الأساسية
        teacher_constraints = {}
        special_constraints = {}
        saturday_teachers = []
        last_slot_restrictions = {}
        
        for t_id_str, rule in teacher_rules.items():
            t_name = next((t['name'] for t in teachers if str(t['id']) == t_id_str), None)
            if not t_name: continue
            
            if rule.get('days'):
                teacher_constraints[t_name] = {'allowed_days': {day_to_idx[d] for d in rule['days'] if d in day_to_idx}}
            
            s_const = {}
            if 's2' in rule.get('limits', []): s_const['start_d1_s2'] = True
            if 's3' in rule.get('limits', []): s_const['start_d1_s3'] = True
            if 'e3' in rule.get('limits', []): s_const['end_s3'] = True
            if 'e4' in rule.get('limits', []): s_const['end_s4'] = True
            if rule.get('rule') != 'unspecified':
                # ترجمة القاعدة
                rules_map = {'group2': 'يومان متتاليان', 'group3': 'ثلاثة أيام متتالية', 'sep2': 'يومان منفصلان', 'sep3': 'ثلاثة ايام منفصلة'}
                s_const['distribution_rule'] = rules_map.get(rule['rule'], 'غير محدد')
            
            special_constraints[t_name] = s_const

        for t_id_str, spec in spec_teachers.items():
            t_name = next((t['name'] for t in teachers if str(t['id']) == t_id_str), None)
            if not t_name: continue
            if spec.get('allow_saturday'): saturday_teachers.append(t_name)
            if spec.get('prevent_last') == '1': last_slot_restrictions[t_name] = 'last_1'
            elif spec.get('prevent_last') == '2': last_slot_restrictions[t_name] = 'last_2'

        distribution_rule_type = 'strict' if global_rules.get('days_interpretation') == 'strict' else 'allowed'
        max_sess = global_rules.get('max_slots')
        max_sessions_per_day = int(max_sess) if max_sess and max_sess.isdigit() else None
        consecutive_large_hall_rule = global_rules.get('consecutive_hall_ban', 'none')
        
        globally_unavailable_slots = set()
        if global_rules.get('rest_tue_pm') and 'الثلاثاء' in day_to_idx and len(slots) >= 2:
            globally_unavailable_slots.update([(day_to_idx['الثلاثاء'], len(slots)-1), (day_to_idx['الثلاثاء'], len(slots)-2)])
        if global_rules.get('rest_thu_pm') and 'الخميس' in day_to_idx and len(slots) >= 2:
            globally_unavailable_slots.update([(day_to_idx['الخميس'], len(slots)-1), (day_to_idx['الخميس'], len(slots)-2)])

        level_specific_large_rooms = {}
        for lvl, r_id in conditions_data.get('level_amphis', {}).items():
            r_name = next((r['name'] for r in rooms_data if str(r['id']) == str(r_id)), None)
            if r_name: level_specific_large_rooms[lvl] = r_name

        specific_small_room_assignments = {} # لم تضف في الواجهة، نتركها فارغة
        
        pairs_data = conditions_data.get('pairs', {'share':[], 'noshare':[]})
        teacher_pairs = []
        for p in pairs_data.get('share', []):
            t1 = next((t['name'] for t in teachers if str(t['id']) == str(p[0])), None)
            t2 = next((t['name'] for t in teachers if str(t['id']) == str(p[1])), None)
            if t1 and t2: teacher_pairs.append((t1, t2))
            
        non_sharing_teacher_pairs = []
        for p in pairs_data.get('noshare', []):
            t1 = next((t['name'] for t in teachers if str(t['id']) == str(p[0])), None)
            t2 = next((t['name'] for t in teachers if str(t['id']) == str(p[1])), None)
            if t1 and t2: non_sharing_teacher_pairs.append((t1, t2))

        # ترجمة الأوزان
        constraint_severities = {
            'distribution': weights.get('distribution', '10'),
            'non_sharing_days': weights.get('no_share', '10'),
            'saturday_work': weights.get('saturday', '10'),
            'last_slot': weights.get('last_slot', '10'),
            'max_sessions': weights.get('max_daily', '10'),
            'teacher_pairs': weights.get('share_pairs', '10'),
            'consecutive_halls': weights.get('consecutive_halls', '10'),
            'prefer_morning': weights.get('morning_pref', '10')
        }
        # تحويل الأرقام النصية إلى الكلمات التي تفهمها الخوارزمية
        for k, v in constraint_severities.items():
            if v == 'strict': constraint_severities[k] = 'hard'
            elif v == '20': constraint_severities[k] = 'high'
            elif v == '10': constraint_severities[k] = 'medium'
            elif v == '1': constraint_severities[k] = 'low'
            elif v == '0': constraint_severities[k] = 'disabled'

        prefer_morning_slots = constraint_severities['prefer_morning'] != 'disabled'
        
        conn.close()
        log_q.put("✅ تمت قراءة ومعالجة جميع البيانات والقيود بنجاح!")
        time.sleep(0.5)

        # ====================================================================
        # قراءة الإعدادات المدخلة من الواجهة (أو استخدام الافتراضي إذا كانت فارغة)
        # ====================================================================
        tabu_iterations = int(algo_settings.get('tabu_iterations', 1000))
        tabu_tenure = int(algo_settings.get('tabu_tenure', 10))
        
        lns_iterations = int(algo_settings.get('lns_iterations', 500))
        lns_ruin_factor = float(algo_settings.get('lns_ruin_factor', 20)) / 100.0 # تقسيم على 100 لأنها نسبة مئوية
        
        vns_iterations = int(algo_settings.get('vns_iterations', 300))
        vns_k_max = int(algo_settings.get('vns_k_max', 5))

        
        
        # ====================================================================
        # تشغيل الخوارزميات (باستخدام المتغيرات الجديدة)
        # ====================================================================
        
        # 1. تجهيز الفترات الأساسية (الصباحية) والاحتياطية (المسائية) للطماعة
        primary_slots = []
        reserve_slots = []
        half_slots = max(1, len(slots) // 2)
        for d_idx in range(len(days)):
            for s_idx in range(len(slots)):
                if s_idx < half_slots:
                    primary_slots.append((d_idx, s_idx))
                else:
                    reserve_slots.append((d_idx, s_idx))

        # 2. تشغيل الخوارزمية الطماعة لبناء الأساس
        log_q.put("\n🚀 جاري بناء الجدول المبدئي السريع (الطماعة)...")
        
        current_solution, final_failures = run_greedy_search_for_best_result(
            log_q=log_q, 
            lectures_sorted=all_lectures,
            days=days, slots=slots, rules_grid=rules_grid, rooms_data=rooms_data, 
            teachers=teachers, all_levels=levels, # استخدمنا levels هنا
            teacher_constraints=teacher_constraints, globally_unavailable_slots=globally_unavailable_slots, 
            special_constraints=special_constraints,
            primary_slots=primary_slots, reserve_slots=reserve_slots, identifiers_by_level=identifiers_by_level, 
            prioritize_primary=True,
            saturday_teachers=saturday_teachers, day_to_idx=day_to_idx, level_specific_large_rooms=level_specific_large_rooms,
            specific_small_room_assignments=specific_small_room_assignments, consecutive_large_hall_rule=consecutive_large_hall_rule, 
            prefer_morning_slots=prefer_morning_slots,
            lectures_by_teacher_map=lectures_by_teacher_map, distribution_rule_type=distribution_rule_type, 
            teacher_pairs=teacher_pairs, constraint_severities=constraint_severities, 
            non_sharing_teacher_pairs=non_sharing_teacher_pairs,
            base_initial_schedule=None
        )
        
        final_cost = sum(f.get('penalty', 1) for f in final_failures)
        log_q.put(f"✅ تم بناء الجدول المبدئي بنجاح! (باقي {len(final_failures)} أخطاء مرنة)")

        if "tabu" in algorithms and not SCHEDULING_STATE["should_stop"]:
            log_q.put(f"\n=== 🔍 بدء البحث المحظور (Tabu Search) بتكرارات: {tabu_iterations} وذاكرة: {tabu_tenure} ===")
            current_solution, final_cost, final_failures = run_tabu_search(
                log_q, all_lectures, days, slots, rooms_data, teachers, levels, 
                identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, 
                lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, 
                day_to_idx, rules_grid, SCHEDULING_STATE, last_slot_restrictions, 
                level_specific_large_rooms, specific_small_room_assignments, constraint_severities, 
                mutation_hard_intensity=3, mutation_soft_probability=0.5, tabu_stagnation_threshold=50,
                max_sessions_per_day=max_sessions_per_day, initial_solution=current_solution, 
                max_iterations=tabu_iterations, tabu_tenure=tabu_tenure, neighborhood_size=50,  # <-- تم التغيير هنا
                consecutive_large_hall_rule=consecutive_large_hall_rule, progress_channel=SCHEDULING_STATE, 
                prefer_morning_slots=prefer_morning_slots, use_strict_hierarchy=strict_hierarchy, non_sharing_teacher_pairs=non_sharing_teacher_pairs
            )
            
        if "lns" in algorithms and not SCHEDULING_STATE["should_stop"]:
            log_q.put(f"\n=== 🌪️ بدء البحث الجواري الواسع (LNS) بتكرارات: {lns_iterations} وتخريب: {lns_ruin_factor*100}% ===")
            current_solution, final_cost, final_failures = run_large_neighborhood_search(
                log_q, all_lectures, days, slots, rooms_data, teachers, levels, 
                identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, 
                lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, 
                day_to_idx, rules_grid, max_iterations=lns_iterations, ruin_factor=lns_ruin_factor, prioritize_primary=True, # <-- تم التغيير هنا
                scheduling_state=SCHEDULING_STATE, last_slot_restrictions=last_slot_restrictions, 
                level_specific_large_rooms=level_specific_large_rooms, specific_small_room_assignments=specific_small_room_assignments, 
                constraint_severities=constraint_severities, initial_solution=current_solution, 
                max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, 
                progress_channel=SCHEDULING_STATE, prefer_morning_slots=prefer_morning_slots, 
                use_strict_hierarchy=strict_hierarchy, non_sharing_teacher_pairs=non_sharing_teacher_pairs
            )
            
        if "vns" in algorithms and not SCHEDULING_STATE["should_stop"]:
            log_q.put(f"\n=== 🌊 بدء البحث الجواري المتغير (VNS) بتكرارات: {vns_iterations} وجوار أقصى: {vns_k_max} ===")
            current_solution, final_cost, final_failures = run_variable_neighborhood_search(
                log_q, all_lectures, days, slots, rooms_data, teachers, levels,
                identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type,
                lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs,
                day_to_idx, rules_grid, max_iterations=vns_iterations, k_max=vns_k_max, prioritize_primary=True, # <-- تم التغيير هنا
                scheduling_state=SCHEDULING_STATE, last_slot_restrictions=last_slot_restrictions, 
                level_specific_large_rooms=level_specific_large_rooms, specific_small_room_assignments=specific_small_room_assignments, 
                constraint_severities=constraint_severities, algorithm_settings={'vns_local_search_iterations': 10}, 
                initial_solution=current_solution, max_sessions_per_day=max_sessions_per_day, 
                consecutive_large_hall_rule=consecutive_large_hall_rule, progress_channel=SCHEDULING_STATE, 
                prefer_morning_slots=prefer_morning_slots, use_strict_hierarchy=strict_hierarchy, non_sharing_teacher_pairs=non_sharing_teacher_pairs
            )

        if SCHEDULING_STATE["should_stop"]:
            log_message("\n🛑 تم إيقاف عملية التوزيع من قبل المستخدم.")
            return
        else:
            log_message("\n✅ تم الانتهاء من جميع الخوارزميات بنجاح!")

        # ====================================================================
        # 1. طباعة تقرير الأخطاء المتبقية بالتفصيل في السجل
        # ====================================================================
        if final_failures:
            log_message("\n" + "="*50)
            log_message("📊 تقرير الأخطاء المتبقية في الجدول النهائي:")
            log_message("="*50)
            
            # تصنيف الأخطاء
            missing = [f for f in final_failures if f.get('penalty', 0) >= 1000] # نقص المواد
            hard = [f for f in final_failures if 100 <= f.get('penalty', 0) < 1000] # أخطاء صارمة
            soft = [f for f in final_failures if 0 < f.get('penalty', 0) < 100] # أخطاء مرنة
            
            if missing:
                log_message(f"❌ المواد غير المجدولة (نقص): {len(missing)}")
                for f in missing[:10]: log_message(f"  - {f.get('course_name')} ({f.get('teacher_name')}): {f.get('reason')}")
                if len(missing) > 10: log_message("  ... والمزيد")
            
            if hard:
                log_message(f"\n🚫 الأخطاء الصارمة (تعارضات قوية): {len(hard)}")
                for f in hard[:10]: log_message(f"  - {f.get('course_name')} ({f.get('teacher_name')}): {f.get('reason')}")
                if len(hard) > 10: log_message("  ... والمزيد")
                
            if soft:
                log_message(f"\n⚠️ الأخطاء المرنة (تفضيلات لم تتحقق): {len(soft)}")
                for f in soft[:10]: log_message(f"  - {f.get('course_name')} ({f.get('teacher_name')}): {f.get('reason')}")
                if len(soft) > 10: log_message("  ... والمزيد")
                
            log_message("="*50 + "\n")
        else:
            log_message("\n🎉 الجدول مثالي! لا توجد أي أخطاء متبقية.")

        # ====================================================================
        # 2. بناء جداول الأساتذة والقاعات الفارغة للتصدير
        # ====================================================================
        log_message("جاري تجهيز ملفات التصدير (جداول الأساتذة والقاعات)...")
        
        prof_schedules = {t['name']: [[[] for _ in slots] for _ in days] for t in teachers}
        free_rooms = [[[] for _ in slots] for _ in days]
        
        if current_solution:
            # بناء جدول الأساتذة
            for level, grid in current_solution.items():
                for d, day in enumerate(grid):
                    for s, slot in enumerate(day):
                        for lec in slot:
                            t_name = lec.get('teacher_name')
                            if t_name and t_name in prof_schedules:
                                lec_copy = lec.copy()
                                lec_copy['level'] = level
                                prof_schedules[t_name][d][s].append(lec_copy)
            
            # بناء القاعات الفارغة
            for d in range(len(days)):
                for s in range(len(slots)):
                    busy_rooms = set()
                    for level, grid in current_solution.items():
                        for lec in grid[d][s]:
                            if lec.get('room'): busy_rooms.add(lec['room'])
                    
                    for r in rooms_data:
                        if r['name'] not in busy_rooms:
                            free_rooms[d][s].append(r['name'])
                            
        # تنظيف الأساتذة الذين ليس لديهم أي مواد
        prof_schedules = {p: g for p, g in prof_schedules.items() if any(lec for day in g for slot in day for lec in slot)}

        # ====================================================================
        # 3. إرسال النتائج النهائية للواجهة
        # ====================================================================
        final_result = {
            "schedule": current_solution if current_solution else {},
            "prof_schedules": prof_schedules, # الآن لم تعد فارغة!
            "free_rooms": free_rooms,         # الآن لم تعد فارغة!
            "days": days,
            "slots": slots,
            
            # ✨ --- الإضافة الجديدة لشريط التقدم --- ✨
            "final_failures": final_failures,        # إرسال قائمة الأخطاء المتبقية
            "total_lectures": len(all_lectures)      # إرسال إجمالي عدد المواد
            # ✨ ---------------------------------- ✨
        }
        
        SCHEDULING_STATE["schedule"] = current_solution
        log_message(f"DONE{json.dumps(final_result)}")

    except Exception as e:
        log_message(f"\n❌ حدث خطأ فادح أثناء التوزيع:\n{str(e)}")
        log_message(traceback.format_exc())
    finally:
        SCHEDULING_STATE["is_running"] = False

# ================= مسارات الويب =================
@generation_bp.route('/api/generate', methods=['POST'])
def generate_schedule():
    data = request.json
    if SCHEDULING_STATE.get("is_running"):
        return jsonify({"success": False, "error": "عملية التوزيع تعمل حالياً."}), 400

    # التعديل هنا: قمنا بإضافة data.get('settings', {}) لتمرير الإعدادات
    thread = threading.Thread(
        target=background_generation_task, 
        args=(data.get('strict_hierarchy'), data.get('algorithms'), data.get('settings', {}))
    )
    thread.start()
    return jsonify({"success": True})

@generation_bp.route('/stream-logs', methods=['GET'])
def stream_logs():
    def generate():
        last_idx = 0
        while SCHEDULING_STATE.get("is_running") or last_idx < len(SCHEDULING_STATE.get("logs", [])):
            logs = SCHEDULING_STATE.get("logs", [])
            if last_idx < len(logs):
                for i in range(last_idx, len(logs)):
                    yield f"data: {logs[i]}\n\n"
                last_idx = len(logs)
            time.sleep(0.5)
    return Response(generate(), mimetype='text/event-stream')

@generation_bp.route('/api/stop-generation', methods=['POST'])
def stop_generation():
    SCHEDULING_STATE["should_stop"] = True
    return jsonify({"success": True})


# ====================================================================
# مسار ودالة تحسين وضغط الجدول (سد الفجوات)
# ====================================================================

@generation_bp.route('/api/refine', methods=['POST'])
def start_refinement():
    if SCHEDULING_STATE["is_running"]:
        return jsonify({"error": "هناك عملية قيد التشغيل بالفعل"}), 400
    
    data = request.json
    current_schedule = data.get('schedule')
    refinement_level = data.get('level', 'balanced') # استلام المستوى
    selected_teachers = data.get('teachers', [])     # استلام قائمة الأساتذة
    
    if not current_schedule:
        return jsonify({"error": "الجدول غير موجود أو فارغ."}), 400
        
    # تمرير الإعدادات للثريد
    thread = threading.Thread(target=background_refinement_task, args=(current_schedule, refinement_level, selected_teachers))
    thread.start()
    
    return jsonify({"success": True})

def background_refinement_task(current_schedule, refinement_level, selected_teachers):
    SCHEDULING_STATE["is_running"] = True
    SCHEDULING_STATE["should_stop"] = False
    SCHEDULING_STATE["logs"] = []
    log_q = LogQueueWrapper()

    try:
        log_message("\n🚀 بدء عملية ضغط وتحسين جداول الأساتذة (سد الفجوات)...")
        
        conn = sqlite3.connect(DATABASE_FILE)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        teachers = [dict(row) for row in cur.execute('SELECT * FROM teachers').fetchall()]
        rooms_data = [dict(row) for row in cur.execute('SELECT * FROM rooms').fetchall()]
        levels = [row['name'] for row in cur.execute('SELECT name FROM levels ORDER BY name').fetchall()]
        
        # --- توحيد أنواع القاعات ---
        for r in rooms_data:
            if r['type'] in ['عادية', 'قاعة', 'صغيرة']: r['type'] = 'صغيرة'
            elif r['type'] in ['مدرج', 'كبيرة']: r['type'] = 'كبيرة'
            
        courses_raw = cur.execute('''
            SELECT c.id, c.name, c.room_type, t.name as teacher_name, group_concat(l.name, ',') as level_names
            FROM courses c
            LEFT JOIN teachers t ON c.teacher_id = t.id
            LEFT JOIN course_levels cl ON c.id = cl.course_id
            LEFT JOIN levels l ON cl.level_id = l.id
            GROUP BY c.id
        ''').fetchall()
        
        all_lectures = []
        from collections import defaultdict
        lectures_by_teacher_map = defaultdict(list)
        
        for c in courses_raw:
            lec = dict(c)
            lec['levels'] = lec['level_names'].split(',') if lec['level_names'] else []
            # --- توحيد أنواع قاعات المواد ---
            if lec['room_type'] in ['عادية', 'قاعة', 'صغيرة']: lec['room_type'] = 'صغيرة'
            elif lec['room_type'] in ['مدرج', 'كبيرة']: lec['room_type'] = 'كبيرة'
            
            all_lectures.append(lec)
            if lec.get('teacher_name'):
                lectures_by_teacher_map[lec['teacher_name']].append(lec)
        
        lectures_by_teacher_map['__all_lectures__'] = all_lectures

        struct_row = cur.execute("SELECT value FROM settings WHERE key='schedule_structure'").fetchone()
        cond_row = cur.execute("SELECT value FROM settings WHERE key='schedule_conditions'").fetchone()
        
        structure_data = json.loads(struct_row['value']) if struct_row else []
        conditions_data = json.loads(cond_row['value']) if cond_row else {}
        
        days = [d['name'] for d in structure_data]
        day_to_idx = {d: i for i, d in enumerate(days)}
        slots = []
        if structure_data and structure_data[0].get('slots'):
            slots = [f"{s['start']}-{s['end']}" for s in structure_data[0]['slots']]
        
        # --- استخراج قواعد الفترات (مهم جداً لعدم إفساد الجدول) ---
        rules_grid = [[[] for _ in slots] for _ in days]
        for d_idx, day_obj in enumerate(structure_data):
            for s_idx, slot_obj in enumerate(day_obj.get('slots', [])):
                for constr in slot_obj.get('constraints', []):
                    rule_type = 'ANY_HALL'
                    if constr['room_rule'] == 'regular': rule_type = 'SMALL_HALLS_ONLY'
                    elif constr['room_rule'] == 'specific': rule_type = 'SPECIFIC_LARGE_HALL'
                    elif constr['room_rule'] == 'none': rule_type = 'NO_HALLS_ALLOWED'
                    rules_grid[d_idx][s_idx].append({
                        'rule_type': rule_type,
                        'levels': constr['levels'],
                        'hall_name': constr['specific_halls'][0] if constr['specific_halls'] else None
                    })
        
        identifiers_by_level = conditions_data.get('identifiers', {})
        teacher_rules = conditions_data.get('teacher_rules', {})
        global_rules = conditions_data.get('global', {})
        weights = conditions_data.get('weights', {})
        spec_teachers = conditions_data.get('special_teachers', {})
        
        teacher_constraints = {}
        special_constraints = {}
        saturday_teachers = []
        last_slot_restrictions = {}
        
        for t_id_str, rule in teacher_rules.items():
            t_name = next((t['name'] for t in teachers if str(t['id']) == t_id_str), None)
            if not t_name: continue
            if rule.get('days'):
                teacher_constraints[t_name] = {'allowed_days': {day_to_idx[d] for d in rule['days'] if d in day_to_idx}}
            s_const = {}
            if 's2' in rule.get('limits', []): s_const['start_d1_s2'] = True
            if 's3' in rule.get('limits', []): s_const['start_d1_s3'] = True
            if 'e3' in rule.get('limits', []): s_const['end_s3'] = True
            if 'e4' in rule.get('limits', []): s_const['end_s4'] = True
            rules_map = {'group2': 'يومان متتاليان', 'group3': 'ثلاثة أيام متتالية', 'sep2': 'يومان منفصلان', 'sep3': 'ثلاثة ايام منفصلة'}
            if rule.get('rule') != 'unspecified': s_const['distribution_rule'] = rules_map.get(rule.get('rule'), 'غير محدد')
            special_constraints[t_name] = s_const

        for t_id_str, spec in spec_teachers.items():
            t_name = next((t['name'] for t in teachers if str(t['id']) == t_id_str), None)
            if not t_name: continue
            if spec.get('allow_saturday'): saturday_teachers.append(t_name)
            if spec.get('prevent_last') == '1': last_slot_restrictions[t_name] = 'last_1'
            elif spec.get('prevent_last') == '2': last_slot_restrictions[t_name] = 'last_2'

        distribution_rule_type = 'strict' if global_rules.get('days_interpretation') == 'strict' else 'allowed'
        max_sess = global_rules.get('max_slots')
        max_sessions_per_day = int(max_sess) if max_sess and max_sess.isdigit() else None
        consecutive_large_hall_rule = global_rules.get('consecutive_hall_ban', 'none')
        
        globally_unavailable_slots = set()
        if global_rules.get('rest_tue_pm') and 'الثلاثاء' in day_to_idx and len(slots) >= 2:
            globally_unavailable_slots.update([(day_to_idx['الثلاثاء'], len(slots)-1), (day_to_idx['الثلاثاء'], len(slots)-2)])
        if global_rules.get('rest_thu_pm') and 'الخميس' in day_to_idx and len(slots) >= 2:
            globally_unavailable_slots.update([(day_to_idx['الخميس'], len(slots)-1), (day_to_idx['الخميس'], len(slots)-2)])

        level_specific_large_rooms = {}
        for lvl, r_id in conditions_data.get('level_amphis', {}).items():
            r_name = next((r['name'] for r in rooms_data if str(r['id']) == str(r_id)), None)
            if r_name: level_specific_large_rooms[lvl] = r_name
            
        specific_small_room_assignments = {}
        
        # --- استخراج الأزواج (كان مفقوداً في دالة التحسين) ---
        pairs_data = conditions_data.get('pairs', {'share':[], 'noshare':[]})
        teacher_pairs = []
        for p in pairs_data.get('share', []):
            t1 = next((t['name'] for t in teachers if str(t['id']) == str(p[0])), None)
            t2 = next((t['name'] for t in teachers if str(t['id']) == str(p[1])), None)
            if t1 and t2: teacher_pairs.append((t1, t2))
            
        non_sharing_teacher_pairs = []
        for p in pairs_data.get('noshare', []):
            t1 = next((t['name'] for t in teachers if str(t['id']) == str(p[0])), None)
            t2 = next((t['name'] for t in teachers if str(t['id']) == str(p[1])), None)
            if t1 and t2: non_sharing_teacher_pairs.append((t1, t2))
        
        constraint_severities = {
            'distribution': weights.get('distribution', '10'),
            'non_sharing_days': weights.get('no_share', '10'),
            'saturday_work': weights.get('saturday', '10'),
            'last_slot': weights.get('last_slot', '10'),
            'max_sessions': weights.get('max_daily', '10'),
            'teacher_pairs': weights.get('share_pairs', '10'),
            'consecutive_halls': weights.get('consecutive_halls', '10'),
            'prefer_morning': weights.get('morning_pref', '10')
        }
        for k, v in constraint_severities.items():
            if v == 'strict': constraint_severities[k] = 'hard'
            elif v == '20': constraint_severities[k] = 'high'
            elif v == '10': constraint_severities[k] = 'medium'
            elif v == '1': constraint_severities[k] = 'low'
            elif v == '0': constraint_severities[k] = 'disabled'

        conn.close()

        actual_selected_names = []
        if selected_teachers and len(selected_teachers) > 0:
            for st in selected_teachers:
                # محاولة العثور على اسم الأستاذ بناءً على الـ ID الخاص به
                matched_name = next((t['name'] for t in teachers if str(t['id']) == str(st)), None)
                if matched_name:
                    actual_selected_names.append(matched_name)
                else:
                    # في حال كان ما وصل من الواجهة هو الاسم مباشرة، نأخذه كما هو
                    actual_selected_names.append(st)
        else:
            # إذا كانت القائمة فارغة (لم يؤشر المستخدم على أحد)، نستهدف الجميع
            actual_selected_names = [t['name'] for t in teachers]
        # =========================================================

        # 2. تشغيل دالة التحسين
        refined_schedule, refinement_log = refine_and_compact_schedule(
            initial_schedule=current_schedule, log_q=log_q, 
            selected_teachers=actual_selected_names, # ✨ هنا نمرر القائمة المُترجمة
            all_lectures=all_lectures, days=days, slots=slots, rooms_data=rooms_data, teachers=teachers, all_levels=levels, 
            identifiers_by_level=identifiers_by_level, special_constraints=special_constraints, teacher_constraints=teacher_constraints, distribution_rule_type=distribution_rule_type,
            lectures_by_teacher_map=lectures_by_teacher_map, globally_unavailable_slots=globally_unavailable_slots, saturday_teachers=saturday_teachers, teacher_pairs=teacher_pairs,
            day_to_idx=day_to_idx, rules_grid=rules_grid, last_slot_restrictions=last_slot_restrictions, level_specific_large_rooms=level_specific_large_rooms,
            specific_small_room_assignments=specific_small_room_assignments, constraint_severities=constraint_severities, max_sessions_per_day=max_sessions_per_day, 
            consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=True, non_sharing_teacher_pairs=non_sharing_teacher_pairs, 
            refinement_level=refinement_level # ✨ المستوى يمرر هنا بنجاح
        )

        prof_schedules = {t['name']: [[[] for _ in slots] for _ in days] for t in teachers}
        free_rooms = [[[] for _ in slots] for _ in days]
        
        for level_name, grid in refined_schedule.items():
            for d, day_slots in enumerate(grid):
                for s, slot_lectures in enumerate(day_slots):
                    for lec in slot_lectures:
                        t_name = lec.get('teacher_name')
                        if t_name and t_name in prof_schedules:
                            lec_copy = lec.copy()
                            lec_copy['level'] = level_name
                            prof_schedules[t_name][d][s].append(lec_copy)

        for d in range(len(days)):
            for s in range(len(slots)):
                busy_rooms = set()
                for grid in refined_schedule.values():
                    for lec in grid[d][s]:
                        if lec.get('room'): busy_rooms.add(lec['room'])
                for r in rooms_data:
                    if r['name'] not in busy_rooms:
                        free_rooms[d][s].append(r['name'])
                        
        prof_schedules = {p: g for p, g in prof_schedules.items() if any(lec for day in g for slot in day for lec in slot)}

        final_result = {
            "schedule": refined_schedule,
            "prof_schedules": prof_schedules,
            "free_rooms": free_rooms,
            "days": days,
            "slots": slots,
            "final_failures": [],
            "total_lectures": len(all_lectures)
        }
        
        SCHEDULING_STATE["schedule"] = refined_schedule
        log_message(f"DONE{json.dumps(final_result)}")

    except Exception as e:
        log_message(f"\n❌ حدث خطأ أثناء التحسين:\n{str(e)}")
        log_message(traceback.format_exc())
    finally:
        SCHEDULING_STATE["is_running"] = False