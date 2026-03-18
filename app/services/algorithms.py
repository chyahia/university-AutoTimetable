import copy
import random
import time
import math
from collections import defaultdict, deque
import json
import traceback
from collections import defaultdict




# هذا المتغير العام ضروري لتتبع حالة الخوارزمية، إرسال السجل الحي، وإيقاف العملية
SCHEDULING_STATE = {
    "is_running": False,
    "should_stop": False,
    "progress": 0,
    "logs": [],
    "schedule": {},
    "prof_schedules": {},
    "free_rooms": {}
}

# دالة مساعدة لإضافة نصوص للسجل الحي لكي تظهر في الواجهة
def log_message(*args, **kwargs):
    # دمج كل المتغيرات الممررة في نص واحد (تماما كما تفعل print)
    msg = " ".join(map(str, args))
    if "logs" in SCHEDULING_STATE:
        SCHEDULING_STATE["logs"].append(msg)
    # الاحتفاظ بالطباعة في الطرفية أيضاً
    print(*args, **kwargs)

SEVERITY_PENALTIES = {
    "hard": 100,
    "high": 20,
    "medium": 10,
    "low": 1,
    "disabled": 0
}

class StopByUserException(Exception):
    pass


# =====================================================================
# START: TABU SEARCH (MODIFIED WITH HIERARCHICAL FITNESS)
# =====================================================================

def run_tabu_search(
    log_q, all_lectures, days, slots, rooms_data, teachers, levels, 
    identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, 
    lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, 
    day_to_idx, rules_grid, scheduling_state, last_slot_restrictions, 
    level_specific_large_rooms, specific_small_room_assignments, constraint_severities, 
    mutation_hard_intensity, mutation_soft_probability, tabu_stagnation_threshold,
    max_sessions_per_day=None, initial_solution=None, max_iterations=1000, 
    tabu_tenure=10, neighborhood_size=50, consecutive_large_hall_rule="none", 
    progress_channel=None, prefer_morning_slots=False, use_strict_hierarchy=False, non_sharing_teacher_pairs=[]
):
    """
    تنفيذ خوارزمية البحث المحظور (Tabu Search) مع استراتيجية موجهة بالأخطاء.
    تركز هذه النسخة على تحديد المحاضرات المسببة للأخطاء الصارمة ومحاولة إصلاحها أولاً،
    ثم تنتقل إلى الأخطاء المرنة والاستكشاف العشوائي.
    """
    log_q.put("--- بدء البحث المحظور (النسخة الموجهة بالأخطاء) ---")
    
    # --- إعدادات أولية ---
    # تحديد الفترات الزمنية المتاحة بشكل عام ولكل أستاذ على حدة
    all_possible_slots = [(d, s) for d in range(len(days)) for s in range(len(slots))]
    globally_valid_slots = {slot for slot in all_possible_slots if slot not in globally_unavailable_slots}

    teacher_specific_valid_slots = {}
    for teacher in teachers:
        teacher_name = teacher['name']
        manual_days = teacher_constraints.get(teacher_name, {}).get('allowed_days')
        if manual_days:
            teacher_specific_valid_slots[teacher_name] = {slot for slot in globally_valid_slots if slot[0] in manual_days}
        else:
            teacher_specific_valid_slots[teacher_name] = globally_valid_slots
    
    if initial_solution:
        log_q.put("البحث المحظور: الانطلاق من الحل المُعطى.")
        current_solution = copy.deepcopy(initial_solution)
    else:
        # منطق إنشاء حل عشوائي إذا لم يتم توفير حل مبدئي
        log_q.put("البحث المحظور: الانطلاق من حل عشوائي.")
        current_solution = {level: [[[] for _ in slots] for _ in days] for level in levels}
        if not all_lectures or not days or not slots:
            return current_solution, 9999, ["بيانات الإدخال فارغة"]
        
        small_rooms = [r['name'] for r in rooms_data if r['type'] == 'صغيرة']
        large_rooms = [r['name'] for r in rooms_data if r['type'] == 'كبيرة']
        for lec in all_lectures:
            valid_slots_for_lec = teacher_specific_valid_slots.get(lec.get('teacher_name'), globally_valid_slots)
            if valid_slots_for_lec:
                day_idx, slot_idx = random.choice(list(valid_slots_for_lec))
                lec_with_room = lec.copy()
                if lec['room_type'] == 'كبيرة' and large_rooms:
                    lec_with_room['room'] = random.choice(large_rooms)
                elif lec['room_type'] == 'صغيرة' and small_rooms:
                    lec_with_room['room'] = random.choice(small_rooms)
                else: lec_with_room['room'] = None
                
                for level_name in lec.get('levels', []):
                    if level_name in current_solution:
                        current_solution[level_name][day_idx][slot_idx].append(lec_with_room)


    # حساب اللياقة الأولية للحل
    current_fitness, _ = calculate_fitness(current_solution, all_lectures, days, slots, teachers, rooms_data, levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)

    best_fitness = current_fitness
    best_solution = copy.deepcopy(current_solution)
    
    unplaced, hard, soft = -best_fitness[0], -best_fitness[1], -best_fitness[2]
    log_q.put(f"البحث المحظور: اللياقة الأولية (نقص, صارم, مرن) = ({unplaced}, {hard}, {soft})")
    
    tabu_list = deque(maxlen=tabu_tenure)

    # ✨ --- بداية الجزء الجديد --- ✨
    stagnation_counter = 0
    last_best_fitness = best_fitness
    stagnation_percentage = float(tabu_stagnation_threshold) / 100.0
    STAGNATION_LIMIT = max(50, int(max_iterations * stagnation_percentage))
    # ✨ --- نهاية الجزء الجديد --- ✨
    
    # --- حلقة البحث الرئيسية ---
    for i in range(max_iterations):
        if scheduling_state.get('should_stop'):
            # رفع استثناء للتوقف إذا طلب المستخدم ذلك
            raise StopByUserException()
        
        # ✨✨ --- بداية الإضافة الجديدة: التحقق من الطفرة اليدوية --- ✨✨
        if SCHEDULING_STATE.get('force_mutation'):
            intensity = SCHEDULING_STATE.get('mutation_intensity', 4)
            log_q.put(f'   >>> 🚀 تم تفعيل طفرة يدوية من قبل المستخدم بقوة {intensity}! <<<')
            
            # نفس منطق طفرة الركود بالضبط
            current_solution = mutate(
                best_solution, all_lectures, days, slots, rooms_data, teachers, levels, teacher_constraints, 
                special_constraints, identifiers_by_level, rules_grid, lectures_by_teacher_map, globally_unavailable_slots, 
                saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, constraint_severities, 
                consecutive_large_hall_rule, prefer_morning_slots,
                extra_teachers_on_hard_error=intensity,
                soft_error_shake_probability=mutation_soft_probability,
                non_sharing_teacher_pairs=non_sharing_teacher_pairs
            )
            
            current_fitness, _ = calculate_fitness(current_solution, all_lectures, days, slots, teachers, rooms_data, levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
            
            # إعادة تعيين الإشارة والعدادات
            SCHEDULING_STATE['force_mutation'] = False 
            SCHEDULING_STATE.pop('mutation_intensity', None)
            stagnation_counter = 0
            tabu_list.clear()
        # ✨✨ --- نهاية الإضافة الجديدة --- ✨✨
        
        # ✨ --- بداية الجزء الجديد --- ✨
        if stagnation_counter >= STAGNATION_LIMIT:
            log_q.put(f'   >>> ⚠️ تم كشف الركود لـ {STAGNATION_LIMIT} دورة. تطبيق طفرة قوية...')
            
            # استدعاء دالة الطفرة على أفضل حل تم العثور عليه
            current_solution = mutate(
                best_solution, all_lectures, days, slots, rooms_data, teachers, levels, teacher_constraints, 
                special_constraints, identifiers_by_level, rules_grid, lectures_by_teacher_map, globally_unavailable_slots, 
                saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, constraint_severities, 
                consecutive_large_hall_rule, prefer_morning_slots,
                extra_teachers_on_hard_error=mutation_hard_intensity,
                soft_error_shake_probability=mutation_soft_probability,
                non_sharing_teacher_pairs=non_sharing_teacher_pairs
            )
            
            # إعادة تقييم الحل الجديد وتصفير العدادات
            current_fitness, _ = calculate_fitness(current_solution, all_lectures, days, slots, teachers, rooms_data, levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
            stagnation_counter = 0
            tabu_list.clear() # مسح قائمة الحظر بعد الهزة الكبيرة
        # ✨ --- نهاية الجزء الجديد --- ✨
        
        if (i + 1) % 50 == 0 and i > 0:
            unplaced, hard, soft = -best_fitness[0], -best_fitness[1], -best_fitness[2]
            log_q.put(f"--- (متابعة) دورة {i+1}: أفضل لياقة حالية (ن,ص,م)=({unplaced}, {hard}, {soft}) ---")
        
        time.sleep(0) # للسماح لواجهة المستخدم بالتحديث
        
        if best_fitness == (0, 0, 0):
            log_q.put("تم العثور على حل مثالي (اللياقة=0)!")
            break

        # ✨ --- بداية المنطق الجديد والمحسن --- ✨

        # الخطوة 1: تشخيص الأخطاء وتحديد المحاضرات المسببة للمشاكل
        _, failures_list = calculate_fitness(current_solution, all_lectures, days, slots, teachers, rooms_data, levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
        
        # إنشاء قوائم بالمحاضرات التي تسبب أخطاء صارمة (أو عدم تنسيب) أو مرنة
        hard_error_lecs_ids = {lec['id'] for f in failures_list if f.get('penalty', 0) >= 100 for lec in f.get('involved_lectures', [])}
        soft_error_lecs_ids = {lec['id'] for f in failures_list if 0 < f.get('penalty', 0) < 100 for lec in f.get('involved_lectures', [])}
        
        hard_error_lecs = [lec for lec in all_lectures if lec['id'] in hard_error_lecs_ids]
        soft_error_lecs = [lec for lec in all_lectures if lec['id'] in soft_error_lecs_ids]


        best_neighbor = None
        best_neighbor_fitness = (-float('inf'), -float('inf'), -float('inf'))
        move_to_make = None
        
        # تقسيم حجم الجوار: 70% لمحاولة حل الأخطاء الصارمة، 30% للبقية
        num_hard_attempts = int(neighborhood_size * 0.7)
        num_soft_attempts = neighborhood_size - num_hard_attempts
        
        # ================== تم استبدال الحلقتين القديمتين بهذا المنطق الجديد ==================
        if hard_error_lecs:
            # --- الحالة الأولى: لا تزال هناك أخطاء صارمة (المنطق القديم يعمل هنا) ---
            for _ in range(num_hard_attempts):
                lec_to_move = random.choice(hard_error_lecs)
                
                # --- بداية كود توليد الجار (المنطق الصحيح) ---
                teacher_of_lec_to_move = lec_to_move.get('teacher_name')
                valid_slots_for_move = teacher_specific_valid_slots.get(teacher_of_lec_to_move, globally_valid_slots)
                if not valid_slots_for_move: continue

                new_day_idx, new_slot_idx = random.choice(list(valid_slots_for_move))

                new_room = None
                large_rooms = [r['name'] for r in rooms_data if r['type'] == 'كبيرة']
                small_rooms = [r['name'] for r in rooms_data if r['type'] == 'صغيرة']

                if lec_to_move['room_type'] == 'كبيرة' and large_rooms:
                    new_room = random.choice(large_rooms)
                elif lec_to_move['room_type'] == 'صغيرة' and small_rooms:
                    new_room = random.choice(small_rooms)

                potential_move = (lec_to_move['id'], new_day_idx, new_slot_idx, new_room)

                neighbor_solution = copy.deepcopy(current_solution)
                lec_id_to_move = lec_to_move.get('id')
                for level_grid in neighbor_solution.values():
                    for day_slots in level_grid:
                        for slot_lectures in day_slots:
                            slot_lectures[:] = [lec for lec in slot_lectures if lec.get('id') != lec_id_to_move]

                lec_with_new_room = lec_to_move.copy()
                lec_with_new_room['room'] = new_room
                for level_name in lec_to_move.get('levels', []):
                    if level_name in neighbor_solution:
                        neighbor_solution[level_name][new_day_idx][new_slot_idx].append(lec_with_new_room)
                # --- نهاية كود توليد الجار ---

                neighbor_fitness, _ = calculate_fitness(neighbor_solution, all_lectures, days, slots, teachers, rooms_data, levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)

                if potential_move not in tabu_list or neighbor_fitness > best_fitness:
                    best_neighbor_unplaced, best_neighbor_hard, _ = -best_neighbor_fitness[0], -best_neighbor_fitness[1], -best_neighbor_fitness[2]
                    neighbor_unplaced, neighbor_hard, _ = -neighbor_fitness[0], -neighbor_fitness[1], -neighbor_fitness[2]
                    is_better_neighbor = (neighbor_unplaced < best_neighbor_unplaced) or (neighbor_unplaced == best_neighbor_unplaced and neighbor_hard < best_neighbor_hard) or (neighbor_unplaced == best_neighbor_unplaced and neighbor_hard == best_neighbor_hard and neighbor_fitness > best_neighbor_fitness)
                    if is_better_neighbor:
                        best_neighbor_fitness, best_neighbor, move_to_make = neighbor_fitness, neighbor_solution, potential_move

            for _ in range(num_soft_attempts):
                lec_to_move = random.choice(soft_error_lecs or all_lectures)
                
                # --- بداية كود توليد الجار (المنطق الصحيح) ---
                teacher_of_lec_to_move = lec_to_move.get('teacher_name')
                valid_slots_for_move = teacher_specific_valid_slots.get(teacher_of_lec_to_move, globally_valid_slots)
                if not valid_slots_for_move: continue
                new_day_idx, new_slot_idx = random.choice(list(valid_slots_for_move))
                new_room = None
                large_rooms = [r['name'] for r in rooms_data if r['type'] == 'كبيرة']
                small_rooms = [r['name'] for r in rooms_data if r['type'] == 'صغيرة']
                if lec_to_move['room_type'] == 'كبيرة' and large_rooms: new_room = random.choice(large_rooms)
                elif lec_to_move['room_type'] == 'صغيرة' and small_rooms: new_room = random.choice(small_rooms)
                potential_move = (lec_to_move['id'], new_day_idx, new_slot_idx, new_room)
                neighbor_solution = copy.deepcopy(current_solution)
                lec_id_to_move = lec_to_move.get('id')
                for level_grid in neighbor_solution.values():
                    for day_slots in level_grid:
                        for slot_lectures in day_slots:
                            slot_lectures[:] = [lec for lec in slot_lectures if lec.get('id') != lec_id_to_move]
                lec_with_new_room = lec_to_move.copy()
                lec_with_new_room['room'] = new_room
                for level_name in lec_to_move.get('levels', []):
                    if level_name in neighbor_solution:
                        neighbor_solution[level_name][new_day_idx][new_slot_idx].append(lec_with_new_room)
                # --- نهاية كود توليد الجار ---
                neighbor_fitness, _ = calculate_fitness(neighbor_solution, all_lectures, days, slots, teachers, rooms_data, levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
                if potential_move not in tabu_list or neighbor_fitness > best_fitness:
                    best_neighbor_unplaced, best_neighbor_hard, _ = -best_neighbor_fitness[0], -best_neighbor_fitness[1], -best_neighbor_fitness[2]
                    neighbor_unplaced, neighbor_hard, _ = -neighbor_fitness[0], -neighbor_fitness[1], -neighbor_fitness[2]
                    is_better_neighbor = (neighbor_unplaced < best_neighbor_unplaced) or (neighbor_unplaced == best_neighbor_unplaced and neighbor_hard < best_neighbor_hard) or (neighbor_unplaced == best_neighbor_unplaced and neighbor_hard == best_neighbor_hard and neighbor_fitness > best_neighbor_fitness)
                    if is_better_neighbor:
                        best_neighbor_fitness, best_neighbor, move_to_make = neighbor_fitness, neighbor_solution, potential_move
        else:
            # --- الحالة الثانية: لا توجد أخطاء صارمة، نستخدم كل الجهد (100%) للأخطاء المرنة ---
            for _ in range(neighborhood_size): # نستخدم حجم الجوار الكامل
                lec_to_move = random.choice(soft_error_lecs or all_lectures)

                # --- بداية كود توليد الجار (المنطق الصحيح) ---
                teacher_of_lec_to_move = lec_to_move.get('teacher_name')
                valid_slots_for_move = teacher_specific_valid_slots.get(teacher_of_lec_to_move, globally_valid_slots)
                if not valid_slots_for_move: continue
                new_day_idx, new_slot_idx = random.choice(list(valid_slots_for_move))
                new_room = None
                large_rooms = [r['name'] for r in rooms_data if r['type'] == 'كبيرة']
                small_rooms = [r['name'] for r in rooms_data if r['type'] == 'صغيرة']
                if lec_to_move['room_type'] == 'كبيرة' and large_rooms: new_room = random.choice(large_rooms)
                elif lec_to_move['room_type'] == 'صغيرة' and small_rooms: new_room = random.choice(small_rooms)
                potential_move = (lec_to_move['id'], new_day_idx, new_slot_idx, new_room)
                neighbor_solution = copy.deepcopy(current_solution)
                lec_id_to_move = lec_to_move.get('id')
                for level_grid in neighbor_solution.values():
                    for day_slots in level_grid:
                        for slot_lectures in day_slots:
                            slot_lectures[:] = [lec for lec in slot_lectures if lec.get('id') != lec_id_to_move]
                lec_with_new_room = lec_to_move.copy()
                lec_with_new_room['room'] = new_room
                for level_name in lec_to_move.get('levels', []):
                    if level_name in neighbor_solution:
                        neighbor_solution[level_name][new_day_idx][new_slot_idx].append(lec_with_new_room)
                # --- نهاية كود توليد الجار ---
                neighbor_fitness, _ = calculate_fitness(neighbor_solution, all_lectures, days, slots, teachers, rooms_data, levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
                if potential_move not in tabu_list or neighbor_fitness > best_fitness:
                    best_neighbor_unplaced, best_neighbor_hard, _ = -best_neighbor_fitness[0], -best_neighbor_fitness[1], -best_neighbor_fitness[2]
                    neighbor_unplaced, neighbor_hard, _ = -neighbor_fitness[0], -neighbor_fitness[1], -neighbor_fitness[2]
                    is_better_neighbor = (neighbor_unplaced < best_neighbor_unplaced) or (neighbor_unplaced == best_neighbor_unplaced and neighbor_hard < best_neighbor_hard) or (neighbor_unplaced == best_neighbor_unplaced and neighbor_hard == best_neighbor_hard and neighbor_fitness > best_neighbor_fitness)
                    if is_better_neighbor:
                        best_neighbor_fitness, best_neighbor, move_to_make = neighbor_fitness, neighbor_solution, potential_move
        # ==================================================================================
        
        # ✨ --- نهاية المنطق الجديد والمحسن --- ✨

        # --- تحديث الحالة ---
        if best_neighbor is None:
            # لم يتم العثور على جار أفضل (حتى لو كان أسوأ من الحالي)، استمر في البحث
            continue

        current_solution = best_neighbor
        current_fitness = best_neighbor_fitness
        if move_to_make:
            tabu_list.append(move_to_make)
        
        # إذا كان الحل الحالي هو الأفضل على الإطلاق، قم بتحديثه
        if current_fitness > best_fitness:
            best_fitness = current_fitness
            best_solution = copy.deepcopy(current_solution)
            if progress_channel: progress_channel['best_solution_so_far'] = best_solution
            
            unplaced, hard, soft = -best_fitness[0], -best_fitness[1], -best_fitness[2]
            log_q.put(f"   - دورة {i+1}: تم العثور على حل أفضل. لياقة (نقص, صارم, مرن)=({unplaced}, {hard}, {soft})")
            
            # تحديث شريط التقدم بناءً على أفضل حل تم العثور عليه
            _, errors_for_best = calculate_fitness(best_solution, all_lectures, days, slots, teachers, rooms_data, levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
            progress_percentage = calculate_progress_percentage(errors_for_best)
            log_q.put(f"PROGRESS:{progress_percentage:.1f}")

        # ✨ --- بداية الجزء الجديد --- ✨
        if best_fitness == last_best_fitness:
            stagnation_counter += 1
        else:
            stagnation_counter = 0 # إعادة تصفير العداد عند حدوث تحسن
        last_best_fitness = best_fitness
        # ✨ --- نهاية الجزء الجديد --- ✨

    # --- الجزء الختامي ---
    log_q.put('انتهى البحث المحظور.')

    # حساب قائمة الأخطاء النهائية والتكلفة لأفضل حل تم التوصل إليه
    final_fitness, final_failures_list = calculate_fitness(
        best_solution, all_lectures, days, slots, teachers, rooms_data, levels, 
        identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, 
        lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, 
        day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, 
        specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs
    )
    
    # تحويل اللياقة النهائية (tuple) إلى تكلفة رقمية واحدة للحفاظ على التوافق
    unplaced, hard, soft = -final_fitness[0], -final_fitness[1], -final_fitness[2]
    final_cost = (unplaced * 1000) + (hard * 100) + soft

    # إرسال التقدم النهائي ورسالة الانتهاء
    final_progress = calculate_progress_percentage(final_failures_list)
    log_q.put(f"PROGRESS:{final_progress:.1f}")
    time.sleep(0.1)
    
    log_q.put(f'=== انتهت الخوارزمية نهائياً - أفضل تكلفة موزونة: {final_cost} ===')
    time.sleep(0.1)

    return best_solution, final_cost, final_failures_list


# =====================================================================
# START: LARGE NEIGHBORHOOD SEARCH (LNS) - MODIFIED
# =====================================================================
def run_large_neighborhood_search(log_q, all_lectures, days, slots, rooms_data, teachers, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, max_iterations, ruin_factor, prioritize_primary, scheduling_state, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities, initial_solution=None, max_sessions_per_day=None, consecutive_large_hall_rule="none", progress_channel=None, prefer_morning_slots=False, use_strict_hierarchy=False, non_sharing_teacher_pairs=[], mutation_hard_intensity=3, mutation_soft_probability=0.5, lns_stagnation_threshold=100):
    
    # ✨ 1. إضافة الدالة المساعدة لتحويل اللياقة إلى درجة رقمية
    def fitness_tuple_to_score(fitness_tuple):
        """تحول اللياقة الهرمية إلى درجة رقمية لمعيار القبول."""
        unplaced, hard, soft = -fitness_tuple[0], -fitness_tuple[1], -fitness_tuple[2]
        return (unplaced * 1000) + (hard * 100) + soft
        
    log_q.put('--- بدء خوارزمية البحث الجِوَاري الواسع (LNS) ---')
    
    # --- الخطوة 1: إنشاء حل أولي (لا تغيير هنا) ---
    log_q.put('   - جاري إنشاء حل أولي باستخدام الخوارزمية الطماعة...')
    primary_slots, reserve_slots = [], []
    day_indices_shuffled = list(range(len(days)))
    random.shuffle(day_indices_shuffled)
    for day_idx in day_indices_shuffled:
        for slot_idx in range(len(slots)):
            is_primary = any(rule.get('rule_type') == 'SPECIFIC_LARGE_HALL' for rule in rules_grid[day_idx][slot_idx])
            (primary_slots if is_primary else reserve_slots).append((day_idx, slot_idx))

    if not initial_solution:
        log_q.put("تحذير: لم يتم توفير حل مبدئي لـ LNS. سيتم البدء بجدول فارغ.")
        current_solution = {level: [[[] for _ in slots] for _ in days] for level in all_levels}
    else:
        log_q.put('   - LNS: الانطلاق من الحل المبدئي المحسّن.')
        current_solution = copy.deepcopy(initial_solution)
    
    # ✨ 2. حساب اللياقة الأولية بدلًا من التكلفة
    initial_fitness, _ = calculate_fitness(
        current_solution, all_lectures, days, slots, teachers, rooms_data, all_levels, 
        identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, 
        lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, 
        day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, 
        specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs
    )

    current_fitness = initial_fitness
    best_fitness_so_far = initial_fitness
    best_solution_so_far = copy.deepcopy(current_solution)
    
    # ✨ 3. تحديث رسالة السجل الأولية
    unplaced, hard, soft = -initial_fitness[0], -initial_fitness[1], -initial_fitness[2]
    log_q.put(f'   - اللياقة الأولية (نقص, صارم, مرن) = ({unplaced}, {hard}, {soft})')
    time.sleep(0)

    last_progress_report = 0
    progress_report_interval = max(50, max_iterations // 20)
    
    # ✨ --- الجزء الأول: تهيئة متغيرات كشف الركود --- ✨
    stagnation_counter = 0
    last_best_fitness = best_fitness_so_far
    stagnation_percentage = float(lns_stagnation_threshold) / 100.0
    STAGNATION_LIMIT = max(20, int(max_iterations * stagnation_percentage)) # حد الركود
    
    # --- الخطوة 2: حلقة LNS الرئيسية ---
    for i in range(max_iterations):

        # ✨ --- الجزء الثاني: التحقق من الركود وتطبيق الطفرة القوية --- ✨
        if stagnation_counter >= STAGNATION_LIMIT:
            log_q.put(f'   >>> ⚠️ تم كشف الركود لـ {STAGNATION_LIMIT} دورة. تطبيق طفرة قوية...')
            current_solution = mutate(
                best_solution_so_far, all_lectures, days, slots, rooms_data, teachers, all_levels, teacher_constraints, 
                special_constraints, identifiers_by_level, rules_grid, lectures_by_teacher_map, globally_unavailable_slots, 
                saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, constraint_severities, 
                consecutive_large_hall_rule, prefer_morning_slots, extra_teachers_on_hard_error=mutation_hard_intensity, soft_error_shake_probability=mutation_soft_probability, non_sharing_teacher_pairs=non_sharing_teacher_pairs
            )
            current_fitness, _ = calculate_fitness(current_solution, all_lectures, days, slots, teachers, rooms_data, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, 
                constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
            stagnation_counter = 0 # إعادة تصفير العداد

        # ✨✨ --- بداية الجزء الجديد الخاص بالبحث الجواري الواسع --- ✨✨
        if SCHEDULING_STATE.get('force_mutation'):
            intensity = SCHEDULING_STATE.get('mutation_intensity', 4)
            log_q.put(f'   >>> 🚀 تم تفعيل طفرة يدوية من قبل المستخدم بقوة {intensity}! <<<')
            
            # نفس منطق طفرة الركود بالضبط
            current_solution = mutate(
                best_solution_so_far, all_lectures, days, slots, rooms_data, teachers, all_levels, teacher_constraints, 
                special_constraints, identifiers_by_level, rules_grid, lectures_by_teacher_map, globally_unavailable_slots, 
                saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, constraint_severities, 
                consecutive_large_hall_rule, prefer_morning_slots,
                extra_teachers_on_hard_error=intensity,
                soft_error_shake_probability=mutation_soft_probability,
                non_sharing_teacher_pairs=non_sharing_teacher_pairs
            )
            
            current_fitness, _ = calculate_fitness(current_solution, all_lectures, days, slots, teachers, rooms_data, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
            
            # إعادة تعيين الإشارة والعدادات
            SCHEDULING_STATE['force_mutation'] = False 
            SCHEDULING_STATE.pop('mutation_intensity', None)
            stagnation_counter = 0
            
        # ✨✨ --- نهاية الجزء الجديد --- ✨✨
        
        if i % 10 == 0 and scheduling_state.get('should_stop'): 
                log_q.put(f'\n--- تم إيقاف LNS عند التكرار {i+1} ---')
                raise StopByUserException()
        
        if best_fitness_so_far == (0, 0, 0):
            log_q.put('   - تم العثور على حل مثالي! إنهاء البحث.')
            break

        if i - last_progress_report >= progress_report_interval:
            unplaced, hard, soft = -best_fitness_so_far[0], -best_fitness_so_far[1], -best_fitness_so_far[2]
            log_q.put(f'--- الدورة {i + 1}/{max_iterations} | أفضل لياقة (ن,ص,م) = ({unplaced}, {hard}, {soft}) ---')
            time.sleep(0.05)
            last_progress_report = i

        new_solution_candidate = copy.deepcopy(current_solution)
        
        # --- (منطق Ruin & Repair يبقى كما هو بدون تغيير) ---
        # ... 
        unique_teacher_names = list({t['name'] for t in teachers})
        if not unique_teacher_names: continue
        adaptive_ruin_factor = ruin_factor * (1 - (i / max_iterations) * 0.5)
        num_to_ruin = max(1, min(int(len(unique_teacher_names) * adaptive_ruin_factor), len(unique_teacher_names)))
        _, current_failures_list = calculate_fitness(current_solution, all_lectures, days, slots, teachers, rooms_data, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
        prof_conflict_weights = defaultdict(int)
        for failure in current_failures_list:
            teacher = failure.get('teacher_name')
            if teacher and teacher in unique_teacher_names:
                # إعطاء وزن ضخم للأخطاء الصارمة، ووزن صغير للمرنة
                if failure.get('penalty', 1) >= 100:
                    prof_conflict_weights[teacher] += 1000  # وزن كبير جداً للخطأ الصارم
                else:
                    prof_conflict_weights[teacher] += 10     # وزن صغير للخطأ المرن

        base_weight = 1 # وزن أساسي لكل أستاذ لضمان فرصة الاختيار
        teacher_weights = [base_weight + prof_conflict_weights.get(name, 0) for name in unique_teacher_names]
        professors_to_ruin = list(set(random.choices(unique_teacher_names, weights=teacher_weights, k=num_to_ruin))) if sum(prof_conflict_weights.values()) > 0 else random.sample(unique_teacher_names, num_to_ruin)
        lectures_to_reinsert = [lec for lec in all_lectures if lec.get('teacher_name') in professors_to_ruin]
        ids_to_remove = {lec.get('id') for lec in lectures_to_reinsert}
        for level_grid in new_solution_candidate.values():
            for day_slots in level_grid:
                for slot_lectures in day_slots:
                    slot_lectures[:] = [lec for lec in slot_lectures if lec.get('id') not in ids_to_remove]
        teacher_schedule_rebuild = {t['name']: set() for t in teachers}
        room_schedule_rebuild = {r['name']: set() for r in rooms_data}
        for grid in new_solution_candidate.values():
            for day_idx, day in enumerate(grid):
                for slot_idx, lectures in enumerate(day):
                    for lec in lectures:
                        teacher_schedule_rebuild.setdefault(lec['teacher_name'], set()).add((day_idx, slot_idx))
                        if lec.get('room'): room_schedule_rebuild.setdefault(lec['room'], set()).add((day_idx, slot_idx))
        lectures_to_reinsert_sorted = sorted(lectures_to_reinsert, key=lambda lec: calculate_lecture_difficulty(lec, lectures_by_teacher_map.get(lec.get('teacher_name'), []), special_constraints, teacher_constraints), reverse=True)
        for lecture in lectures_to_reinsert_sorted:
            find_slot_for_single_lecture(lecture, new_solution_candidate, teacher_schedule_rebuild, room_schedule_rebuild, days, slots, rules_grid, rooms_data, teacher_constraints, globally_unavailable_slots, special_constraints, primary_slots, reserve_slots, identifiers_by_level, prioritize_primary, saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots)
        # ...
        
        # ✨ 4. حساب لياقة الحل الجديد
        new_fitness, _ = calculate_fitness(
            new_solution_candidate, all_lectures, days, slots, teachers, rooms_data, all_levels,
            identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, 
            lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, 
            day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, 
            specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs
        )
        
        # ✨ 5. معيار القبول الهجين
        # استخراج عدد الأخطاء للمقارنة
        current_unplaced, current_hard, _ = -current_fitness[0], -current_fitness[1], -current_fitness[2]
        new_unplaced, new_hard, _ = -new_fitness[0], -new_fitness[1], -new_fitness[2]

        accept_move = (new_unplaced < current_unplaced) or \
                    (new_unplaced == current_unplaced and new_hard < current_hard)

        if not accept_move and new_unplaced == current_unplaced and new_hard == current_hard:
            if new_fitness > current_fitness:
                accept_move = True

        # إذا لم يتم قبول الحركة، نلجأ إلى منطق التلدين المحاكى كفرصة أخيرة
        if not accept_move:
            temperature = 1.0 - (i / max_iterations)
            if temperature > 0.1:
                current_score = fitness_tuple_to_score(current_fitness)
                new_score = fitness_tuple_to_score(new_fitness)
                if random.random() < math.exp(-(new_score - current_score) / temperature):
                    accept_move = True

        if accept_move:
            current_solution = new_solution_candidate
            current_fitness = new_fitness
            
            # ✨ 6. تحديث أفضل حل بناءً على اللياقة
            if current_fitness > best_fitness_so_far:
                best_fitness_so_far = current_fitness
                best_solution_so_far = copy.deepcopy(current_solution)
                if progress_channel: progress_channel['best_solution_so_far'] = best_solution_so_far
                
                unplaced, hard, soft = -best_fitness_so_far[0], -best_fitness_so_far[1], -best_fitness_so_far[2]
                log_q.put(f'   >>> إنجاز جديد! أخطاء (نقص, صارم, مرن)=({unplaced}, {hard}, {soft})')
                
                _, errors_for_best = calculate_fitness(best_solution_so_far, all_lectures, days, slots, teachers, rooms_data, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
                progress_percentage = calculate_progress_percentage(errors_for_best)
                log_q.put(f"PROGRESS:{progress_percentage:.1f}")

    # ✨ --- الجزء الثالث: تحديث عداد الركود --- ✨
        if best_fitness_so_far == last_best_fitness:
            stagnation_counter += 1
        else:
            stagnation_counter = 0
        last_best_fitness = best_fitness_so_far
    
    # --- الخطوة 3: التحقق النهائي وإرجاع النتيجة ---
    log_q.put(f'انتهت الخوارزمية بعد {max_iterations} تكرار.')

    # ✨ 7. حساب المخرجات النهائية بناءً على أفضل لياقة
    final_fitness, final_failures_list = calculate_fitness(
        best_solution_so_far, all_lectures, days, slots, teachers, rooms_data, all_levels,
        identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, 
        lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, 
        day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, 
        specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs
    )
    
    final_cost = fitness_tuple_to_score(final_fitness)

    final_progress = calculate_progress_percentage(final_failures_list)
    log_q.put(f"PROGRESS:{final_progress:.1f}")
    time.sleep(0.1)

    log_q.put(f'=== انتهت الخوارزمية نهائياً - أفضل تكلفة موزونة: {final_cost} ===')
    time.sleep(0.1)

    return best_solution_so_far, final_cost, final_failures_list

# =====================================================================
# END: LARGE NEIGHBORHOOD SEARCH (LNS)
# =====================================================================

# =====================================================================
# START: VARIABLE NEIGHBORHOOD SEARCH (VNS) - AGGRESSIVE ACCEPTANCE
# =====================================================================
def run_variable_neighborhood_search(
    log_q, all_lectures, days, slots, rooms_data, teachers, all_levels,
    identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type,
    lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs,
    day_to_idx, rules_grid, max_iterations, k_max, prioritize_primary,
    scheduling_state, last_slot_restrictions, level_specific_large_rooms,
    specific_small_room_assignments, constraint_severities, algorithm_settings, initial_solution=None, max_sessions_per_day=None, consecutive_large_hall_rule="none", progress_channel=None, prefer_morning_slots=False, use_strict_hierarchy=False, non_sharing_teacher_pairs=[], mutation_hard_intensity=3, mutation_soft_probability=0.5, vns_stagnation_threshold=50):

    log_q.put('--- بدء VNS (معيار القبول الصارم) ---')
    
    # --- المرحلة 1: الإعداد والبناء المبدئي (لا تغيير) ---
    primary_slots, reserve_slots = [], []
    day_indices_shuffled = list(range(len(days))); random.shuffle(day_indices_shuffled)
    for day_idx in day_indices_shuffled:
        for slot_idx in range(len(slots)):
            is_primary = any(rule.get('rule_type') == 'SPECIFIC_LARGE_HALL' for rule in rules_grid[day_idx][slot_idx])
            (primary_slots if is_primary else reserve_slots).append((day_idx, slot_idx))

    if not initial_solution:
        log_q.put("تحذير: لم يتم توفير حل مبدئي لـ VNS. سيتم البدء بجدول فارغ.")
        current_solution = {level: [[[] for _ in slots] for _ in days] for level in all_levels}
    else:
        log_q.put('   - VNS: الانطلاق من الحل المبدئي المحسّن.')
        current_solution = copy.deepcopy(initial_solution)

    initial_fitness, _ = calculate_fitness(current_solution, all_lectures, days, slots, teachers, rooms_data, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
    current_fitness, best_fitness_so_far = initial_fitness, initial_fitness
    best_solution_so_far = copy.deepcopy(current_solution)

    unplaced, hard, soft = -best_fitness_so_far[0], -best_fitness_so_far[1], -best_fitness_so_far[2]
    log_q.put(f'   - اكتمل البناء المبدئي. اللياقة (نقص, صارم, مرن) = ({unplaced}, {hard}, {soft})')
    
    unplaced_stagnation_counter, last_unplaced_count, STAGNATION_LIMIT = 0, float('inf'), 5 
    
    # ✨ --- الجزء الأول: تهيئة متغيرات كشف الركود --- ✨
    stagnation_counter = 0
    # ✨ [تعديل] تتبع آخر أفضل لياقة، وليس اللياقة الحالية
    last_best_fitness = best_fitness_so_far 
    stagnation_percentage = float(vns_stagnation_threshold) / 100.0
    STAGNATION_LIMIT = max(15, int(max_iterations * stagnation_percentage)) # حد الركود
    
    # --- المرحلة 2: حلقة VNS الرئيسية للتحسين ---
    for i in range(max_iterations):
        # ✨ [تعديل] الآن يتم تطبيق الطفرة على 'best_solution_so_far' وتحديث 'current_solution'
        if stagnation_counter >= STAGNATION_LIMIT:
            log_q.put(f'   >>> ⚠️ تم كشف الركود لـ {STAGNATION_LIMIT} دورة. تطبيق طفرة قوية...')
            current_solution = mutate(
                best_solution_so_far, all_lectures, days, slots, rooms_data, teachers, all_levels, teacher_constraints, 
                special_constraints, identifiers_by_level, rules_grid, lectures_by_teacher_map, globally_unavailable_slots, 
                saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, constraint_severities, 
                consecutive_large_hall_rule, prefer_morning_slots, extra_teachers_on_hard_error=mutation_hard_intensity, soft_error_shake_probability=mutation_soft_probability, non_sharing_teacher_pairs=non_sharing_teacher_pairs
            )
            # نقوم بإعادة تقييم الحل الجديد وتحديث اللياقة الحالية
            current_fitness, _ = calculate_fitness(current_solution, all_lectures, days, slots, teachers, rooms_data, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, 
                constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
            stagnation_counter = 0 # إعادة تصفير العداد

        if scheduling_state.get('should_stop'): raise StopByUserException()
        if SCHEDULING_STATE.get('force_mutation'):
            intensity = SCHEDULING_STATE.get('mutation_intensity', 4)
            log_q.put(f'   >>> 🚀 تم تفعيل طفرة يدوية من قبل المستخدم بقوة {intensity}! <<<')
            current_solution = mutate(
                best_solution_so_far, all_lectures, days, slots, rooms_data, teachers, all_levels, teacher_constraints, 
                special_constraints, identifiers_by_level, rules_grid, lectures_by_teacher_map, globally_unavailable_slots, 
                saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, constraint_severities, 
                consecutive_large_hall_rule, prefer_morning_slots,
                extra_teachers_on_hard_error=intensity,
                soft_error_shake_probability=mutation_soft_probability,
                non_sharing_teacher_pairs=non_sharing_teacher_pairs
            )
            current_fitness, _ = calculate_fitness(current_solution, all_lectures, days, slots, teachers, rooms_data, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
            SCHEDULING_STATE['force_mutation'] = False 
            SCHEDULING_STATE.pop('mutation_intensity', None)
            stagnation_counter = 0
            
        if best_fitness_so_far == (0, 0, 0): break
        
        if (i % 10 == 0):
            unplaced, hard, soft = -best_fitness_so_far[0], -best_fitness_so_far[1], -best_fitness_so_far[2]
            log_q.put(f'--- دورة التحسين {i + 1}/{max_iterations} | أفضل لياقة (ن,ص,م) = ({unplaced}, {hard}, {soft}) ---')
            time.sleep(0.01)

        _, current_failures = calculate_fitness(current_solution, all_lectures, days, slots, teachers, rooms_data, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)

        k = 1
        while k <= k_max:
            if scheduling_state.get('should_stop'): raise StopByUserException()
            shaken_solution = copy.deepcopy(current_solution)
            
           # --- بداية التعديل: اختيار استراتيجية الهز عشوائياً ---
            shake_strategy = random.choice(['lectures', 'lectures', 'teachers', 'days']) # نعطي فرصة أكبر لاستراتيجية المحاضرات
            
            lectures_to_reinsert = []
            if shake_strategy == 'lectures':
                lectures_to_reinsert = _shake_by_lectures(current_failures, all_lectures, k)
            elif shake_strategy == 'teachers':
                lectures_to_reinsert = _shake_by_teachers(lectures_by_teacher_map, k)
            elif shake_strategy == 'days':
                lectures_to_reinsert = _shake_by_days(current_solution, k, days)
            # --- نهاية التعديل ---
            if not lectures_to_reinsert:
                k += 1
                continue
            
            ids_to_remove = {l.get('id') for l in lectures_to_reinsert}
            for grid in shaken_solution.values():
                for day in grid:
                    for slot in day: slot[:] = [l for l in slot if l.get('id') not in ids_to_remove]
            temp_teacher_schedule_shake, temp_room_schedule_shake = defaultdict(set), defaultdict(set)
            for grid in shaken_solution.values():
                for d_idx, day in enumerate(grid):
                    for s_idx, lectures_in_slot in enumerate(day):
                        for lec in lectures_in_slot:
                            if lec.get('teacher_name'): temp_teacher_schedule_shake[lec['teacher_name']].add((d_idx, s_idx))
                            if lec.get('room'): temp_room_schedule_shake[lec.get('room')].add((d_idx, s_idx))
            for lecture in lectures_to_reinsert:
                find_slot_for_single_lecture(lecture, shaken_solution, temp_teacher_schedule_shake, temp_room_schedule_shake, days, slots, rules_grid, rooms_data, teacher_constraints, globally_unavailable_slots, special_constraints, primary_slots, reserve_slots, identifiers_by_level, prioritize_primary, saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots)

            vns_ls_iterations = int(algorithm_settings.get('vns_local_search_iterations', 0))
            solution_to_evaluate = shaken_solution
            if vns_ls_iterations > 0:
                improved_shaken_solution = run_vns_local_search(
                    shaken_solution, all_lectures, days, slots, rooms_data, teachers, all_levels, 
                    identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, 
                    lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, 
                    day_to_idx, rules_grid, prioritize_primary, level_specific_large_rooms, 
                    specific_small_room_assignments, constraint_severities, last_slot_restrictions, 
                    max_iterations=vns_ls_iterations, consecutive_large_hall_rule=consecutive_large_hall_rule, 
                    prefer_morning_slots=prefer_morning_slots, use_strict_hierarchy=use_strict_hierarchy,
                    max_sessions_per_day=max_sessions_per_day, non_sharing_teacher_pairs=non_sharing_teacher_pairs
                )
                solution_to_evaluate = improved_shaken_solution

            new_fitness, _ = calculate_fitness(solution_to_evaluate, all_lectures, days, slots, teachers, rooms_data, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)

            # --- ✨ بداية معيار القبول الهجين والمستقر ---
            accept_move = False
            if new_fitness > current_fitness:
                accept_move = True
            else:
                has_critical_errors = (-current_fitness[0] > 0) or (-current_fitness[1] > 0)
                temperature = 0.8 if has_critical_errors else 0.7

                def fitness_to_score(fit):
                    u, h, s = -fit[0], -fit[1], -fit[2]
                    return (u * 1000) + (h * 100) + s
                
                current_score = fitness_to_score(current_fitness)
                new_score = fitness_to_score(new_fitness)

                if new_score > current_score:
                    try:
                        acceptance_probability = math.exp(-(new_score - current_score) / temperature)
                        if random.random() < acceptance_probability:
                            accept_move = True
                    except OverflowError:
                        pass
            # --- نهاية معيار القبول الهجين والمستقر ---

            if accept_move:
                current_solution, current_fitness = solution_to_evaluate, new_fitness
                
                # ✨ تحديث أفضل حل بشكل منفصل
                if current_fitness > best_fitness_so_far:
                    best_fitness_so_far, best_solution_so_far = current_fitness, copy.deepcopy(current_solution)
                    if progress_channel: progress_channel['best_solution_so_far'] = best_solution_so_far
                    
                    unplaced_best, hard_best, soft_best = -best_fitness_so_far[0], -best_fitness_so_far[1], -best_fitness_so_far[2]
                    log_q.put(f'   >>> إنجاز جديد! أفضل لياقة (ن,ص,م) = ({unplaced_best}, {hard_best}, {soft_best})')
                    
                    _, errors_for_best = calculate_fitness(best_solution_so_far, all_lectures, days, slots, teachers, rooms_data, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
                    progress_percentage = calculate_progress_percentage(errors_for_best)
                    log_q.put(f"PROGRESS:{progress_percentage:.1f}")

                k = 1
            else:
                k += 1
        
        # ✨ تحديث عداد الركود بناءً على أفضل لياقة تم الوصول إليها
        if best_fitness_so_far == last_best_fitness:
            stagnation_counter += 1
        else:
            stagnation_counter = 0
        last_best_fitness = best_fitness_so_far
    
    # --- الفحص النهائي وإرجاع النتيجة (لا تغيير) ---
    log_q.put('انتهت خوارزمية VNS.')
    final_fitness, final_failures_list = calculate_fitness(best_solution_so_far, all_lectures, days, slots, teachers, rooms_data, all_levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy, max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
    unplaced, hard, soft = -final_fitness[0], -final_fitness[1], -final_fitness[2]
    final_cost = (unplaced * 1000) + (hard * 100) + soft
    final_progress = calculate_progress_percentage(final_failures_list)
    log_q.put(f"PROGRESS:{final_progress:.1f}"); time.sleep(0.1)
    log_q.put(f'=== انتهت الخوارزمية نهائياً - أفضل تكلفة موزونة: {final_cost} ==='); time.sleep(0.1)
    return best_solution_so_far, final_cost, final_failures_list

# =====================================================================
# END: VARIABLE NEIGHBORHOOD SEARCH (VNS)
# =====================================================================

# =====================================================================
# START: DYNAMIC MULTI-OBJECTIVE FITNESS CALCULATION
# =====================================================================
def calculate_fitness(schedule, all_lectures, days, slots, teachers, rooms_data, levels, identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities, 
                    # ✨✨ --- المعامل الجديد والمهم --- ✨✨
                    use_strict_hierarchy=False, 
                    max_sessions_per_day=None, consecutive_large_hall_rule="none", prefer_morning_slots=False, non_sharing_teacher_pairs=[]):
    """
    تحسب "جودة" الحل بإحدى طريقتين بناءً على المعامل use_strict_hierarchy:
    - False (الافتراضي): الطريقة الهرمية العادية.
    - True (الصارمة): يجب حل الأخطاء الصارمة أولاً بشكل كامل.
    """
    # 1. حساب قائمة الأخطاء الكاملة (هذا الجزء مشترك بين الطريقتين)
    errors_list = calculate_schedule_cost(
        schedule, days, slots, teachers, rooms_data, levels, identifiers_by_level, 
        special_constraints, teacher_constraints, distribution_rule_type, lectures_by_teacher_map, 
        globally_unavailable_slots, saturday_teachers, teacher_pairs, day_to_idx, rules_grid, 
        last_slot_restrictions, level_specific_large_rooms, specific_small_room_assignments, constraint_severities, 
        max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule, 
        prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs
    )
    
    # 2. حساب المواد الناقصة والأخطاء (هذا الجزء مشترك أيضاً)
    scheduled_ids = {lec.get('id') for grid in schedule.values() for day in grid for slot in day for lec in slot}
    unplaced_lectures = [lec for lec in all_lectures if lec.get('id') not in scheduled_ids and lec.get('teacher_name')]
    unplaced_count = len(unplaced_lectures)
    
    hard_errors_count = 0
    soft_errors_count = 0
    for error in errors_list:
        if error.get('penalty', 1) >= 100:
            hard_errors_count += 1
        else:
            soft_errors_count += 1

    # (اختياري) إضافة تفاصيل النقص إلى قائمة الأخطاء للعرض
    for lec in unplaced_lectures:
        errors_list.append({"course_name": lec.get('name'), "teacher_name": lec.get('teacher_name'), "reason": "المادة لم يتم جدولتها (نقص).", "penalty": 1000})

    # ✨✨ --- 3. المنطق الشرطي الذي يحدد كيفية حساب اللياقة النهائية --- ✨✨
    if use_strict_hierarchy:
        # --- المنطق الصارم (الذي اقترحته سابقًا) ---
        has_critical_errors = (unplaced_count > 0) or (hard_errors_count > 0)
        if has_critical_errors:
            # المرحلة الأولى: تجاهل الأخطاء المرنة تماماً
            fitness_tuple = (-unplaced_count, -hard_errors_count, 0)
        else:
            # المرحلة الثانية: تم حل كل الأخطاء الحرجة، ركز على المرنة
            fitness_tuple = (0, 0, -soft_errors_count)
    else:
        # --- المنطق الأصلي (الهرمية العادية) ---
        fitness_tuple = (-unplaced_count, -hard_errors_count, -soft_errors_count)

    return fitness_tuple, errors_list
# =====================================================================
# END: DYNAMIC FITNESS CALCULATION
# =====================================================================

def calculate_schedule_cost(
    schedule, days, slots, teachers, rooms_data, levels, 
    identifiers_by_level, special_constraints, teacher_constraints, 
    distribution_rule_type, lectures_by_teacher_map, globally_unavailable_slots, 
    saturday_teachers, teacher_pairs, day_to_idx, rules_grid, 
    last_slot_restrictions, level_specific_large_rooms, 
    specific_small_room_assignments, constraint_severities, # ✨ المعامل الجديد
    max_sessions_per_day=None, consecutive_large_hall_rule="none", prefer_morning_slots=False, non_sharing_teacher_pairs=[]
):
    """
    النسخة الكاملة والمصححة:
    - تحسب كل الأخطاء مع عقوبات ديناميكية.
    - تعيد المنطق التفصيلي لقيد تفضيل الفترات المبكرة.
    """
    conflicts_list = []
    all_lectures_map = {lec['id']: lec for lec in lectures_by_teacher_map.get('__all_lectures__', [])}

    # --- الخطوة 1: الكشف الفعال عن تعارضات الأساتذة والقاعات (صارمة دائماً) ---
    for day_idx, day_name in enumerate(days):
        for slot_idx, slot_name in enumerate(slots):
            lectures_in_this_slot = []
            for level in levels:
                if schedule.get(level) and day_idx < len(schedule[level]) and slot_idx < len(schedule[level][day_idx]):
                    lectures_in_this_slot.extend(schedule[level][day_idx][slot_idx])

            if not lectures_in_this_slot: continue

            lectures_by_id = defaultdict(list)
            for lec in lectures_in_this_slot: lectures_by_id[lec.get('id')].append(lec)

            teachers_in_slot_set, rooms_in_slot_set = set(), set()
            for lec_id, lecture_group in lectures_by_id.items():
                rep_lec = lecture_group[0] 
                teacher, room = rep_lec.get('teacher_name'), rep_lec.get('room')

                if teacher and teacher in teachers_in_slot_set:
                    clashing_lectures = [l for l in lectures_in_this_slot if l.get('teacher_name') == teacher]
                    conflicts_list.append({"course_name": rep_lec.get('name'), "teacher_name": teacher, "reason": f"تعارض الأستاذ في {day_name} {slot_name}", "penalty": 100, "involved_lectures": clashing_lectures})
                if teacher: teachers_in_slot_set.add(teacher)

                if room and room in rooms_in_slot_set:
                    clashing_lectures = [l for l in lectures_in_this_slot if l.get('room') == room]
                    conflicts_list.append({"course_name": rep_lec.get('name'), "teacher_name": "N/A", "reason": f"تعارض في القاعة {room} في {day_name} {slot_name}", "penalty": 100, "involved_lectures": clashing_lectures})
                if room: rooms_in_slot_set.add(room)

    # --- الخطوة 2: بناء الخرائط والتحقق الشامل من القيود الأخرى ---
    shared_lecture_placements = defaultdict(list)
    teacher_schedule_map = defaultdict(set)

    for level, day_grid in schedule.items():
        for day_idx, slot_list in enumerate(day_grid):
            for slot_idx, lectures in enumerate(slot_list):
                if not lectures: continue
                day_name, slot_name = days[day_idx], slots[slot_idx]

                # القيود التالية دائماً صارمة
                if (day_idx, slot_idx) in globally_unavailable_slots:
                    conflicts_list.append({"course_name": "فترة راحة", "reason": f"خرق فترة الراحة العامة في {day_name} {slot_name}", "penalty": 100, "involved_lectures": lectures})

                rules_for_slot = rules_grid[day_idx][slot_idx]
                if rules_for_slot:
                    for lec in lectures:
                        is_level_in_any_rule, allowed_room_types = False, []
                        for rule in rules_for_slot:
                            if level in rule.get('levels', []):
                                is_level_in_any_rule = True
                                rule_type = rule.get('rule_type')
                                if rule_type == 'ANY_HALL': allowed_room_types.extend(['كبيرة', 'صغيرة'])
                                elif rule_type == 'SMALL_HALLS_ONLY': allowed_room_types.append('صغيرة')
                                elif rule_type == 'SPECIFIC_LARGE_HALL': allowed_room_types.append('كبيرة')

                        if is_level_in_any_rule and lec.get('room_type') not in set(allowed_room_types):
                            conflicts_list.append({"course_name": lec.get('name'), "reason": f"قيد الفترة في {day_name} {slot_name} يخرق قاعدة نوع القاعة ({lec.get('room_type')})", "penalty": 100, "involved_lectures": [lec]})

                large_room_lectures = [lec for lec in lectures if lec.get('room_type') == 'كبيرة']
                if len(large_room_lectures) > 1 or (len(large_room_lectures) == 1 and len(lectures) > 1):
                    conflicts_list.append({"course_name": "عدة مواد", "teacher_name": level, "reason": f"تعارض قاعة كبيرة مع مادة أخرى في {day_name} {slot_name}", "penalty": 100, "involved_lectures": lectures})

                used_identifiers_this_slot = {}
                for lec in lectures:
                    teacher_schedule_map[lec.get('teacher_name')].add((day_idx, slot_idx))
                    original_lec = all_lectures_map.get(lec.get('id'))
                    if original_lec and len(original_lec.get('levels', [])) > 1:
                        shared_lecture_placements[lec.get('id')].append({'level': level, 'day_idx': day_idx, 'slot_idx': slot_idx, 'room': lec.get('room')})

                    if lec.get('room_type') == 'كبيرة' and (room := level_specific_large_rooms.get(level)) and lec.get('room') != room:
                        conflicts_list.append({"course_name": lec.get('name'), "reason": f"قيد قاعة المستوى في {day_name} {slot_name}: يجب أن تكون في '{room}' وليس '{lec.get('room')}'", "penalty": 100, "involved_lectures": [lec]})
                    if lec.get('room_type') == 'صغيرة' and (room := specific_small_room_assignments.get(f"{lec.get('name')} ({level})")) and lec.get('room') != room:
                        conflicts_list.append({"course_name": lec.get('name'), "reason": f"قيد القاعة الصغيرة في {day_name} {slot_name}: يجب أن تكون في '{room}' وليس '{lec.get('room')}'", "penalty": 100, "involved_lectures": [lec]})

                    identifier = get_contained_identifier(lec['name'], identifiers_by_level.get(level, []))
                    if identifier:
                        if identifier in used_identifiers_this_slot:
                            clashing_lectures = used_identifiers_this_slot[identifier] + [lec]
                            conflicts_list.append({"course_name": lec.get('name'), "teacher_name": level, "reason": f"تعارض معرفات ({identifier}) في {day_name} {slot_name}", "penalty": 100, "involved_lectures": clashing_lectures})
                        else:
                            used_identifiers_this_slot[identifier] = [lec]

    # --- الخطوة 3: التحقق من صحة توزيع المواد المشتركة (صارم دائماً) ---
    for lec_id, placements in shared_lecture_placements.items():
        original_lec = all_lectures_map.get(lec_id)
        if not original_lec: continue

        required_levels, placed_levels = set(original_lec.get('levels', [])), {p['level'] for p in placements}
        if required_levels != placed_levels:
            conflicts_list.append({"course_name": original_lec['name'], "reason": f"توزيع ناقص/زائد للمادة المشتركة.", "penalty": 100, "involved_lectures": [original_lec]})
        if len(placements) > 1 and len(set((p['day_idx'], p['slot_idx'], p['room']) for p in placements)) > 1:
            conflicts_list.append({"course_name": original_lec['name'], "reason": "توزيع غير متناسق للمادة المشتركة.", "penalty": 100, "involved_lectures": [original_lec]})

    penalty_consecutive = SEVERITY_PENALTIES.get(constraint_severities.get('consecutive_halls', 'low'), 1)
    
    # --- الخطوة 4: التحقق من قيد توالي القاعات الكبيرة (ديناميكي) ---
    if consecutive_large_hall_rule != 'none':
        penalty = 100 if constraint_severities.get('consecutive_halls') == 'hard' else penalty_consecutive
        for level, day_grid in schedule.items():
            for day_idx, slot_list in enumerate(day_grid):
                for slot_idx in range(1, len(slot_list)):
                    common_halls = {lec['room'] for lec in slot_list[slot_idx] if lec.get('room_type') == 'كبيرة'}.intersection({lec['room'] for lec in slot_list[slot_idx - 1] if lec.get('room_type') == 'كبيرة'})
                    for hall in common_halls:
                        if consecutive_large_hall_rule == 'all' or consecutive_large_hall_rule == hall:
                            involved = [l for l in slot_list[slot_idx] if l.get('room') == hall] + [l for l in slot_list[slot_idx - 1] if l.get('room') == hall]
                            conflicts_list.append({"course_name": f"قيد التوالي للمستوى {level}", "teacher_name": "N/A", "reason": f"حدث توالٍ غير مسموح به في القاعة الكبيرة '{hall}'.", "penalty": penalty, "involved_lectures": involved})

    # --- الخطوة 5: التحقق من قيود الأساتذة العامة (ديناميكي) ---
    # نفترض أن دالة `validate_teacher_constraints_in_solution` تم تعديلها هي الأخرى لتقبل `constraint_severities`
    validation_failures = validate_teacher_constraints_in_solution(teacher_schedule_map, special_constraints, teacher_constraints, lectures_by_teacher_map, distribution_rule_type, saturday_teachers, teacher_pairs, day_to_idx, last_slot_restrictions, len(slots), constraint_severities, max_sessions_per_day=max_sessions_per_day, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
    conflicts_list.extend(validation_failures) 

    penalty_morning = SEVERITY_PENALTIES.get(constraint_severities.get('prefer_morning', 'low'), 1)
    
    # --- الخطوة 6: تطبيق عقوبات تفضيل الفترات المبكرة (ديناميكي ومع المنطق الكامل) ---
    if prefer_morning_slots and len(slots) > 1:
        penalty = 100 if constraint_severities.get('prefer_morning') == 'hard' else penalty_morning
        room_schedule_map = defaultdict(set)
        for day_grid in schedule.values():
            for day_idx, day_slots in enumerate(day_grid):
                for slot_idx, lectures_in_slot in enumerate(day_slots):
                    for lec in lectures_in_slot:
                        if lec.get('room'): room_schedule_map[(day_idx, slot_idx)].add(lec.get('room'))

        # ✨ تم إرجاع هذا المنطق من النسخة الأصلية
        first_work_day_map = {
            t: min(d for d, s in slots)
            for t, slots in teacher_schedule_map.items() if slots
        }
        
        last_slot_index = len(slots) - 1
        earlier_slots_indices = range(last_slot_index)

        for level, day_grid in schedule.items():
            for day_idx, day_slots in enumerate(day_grid):
                lectures_in_last_slot = day_slots[last_slot_index]

                for lecture in lectures_in_last_slot:
                    teacher = lecture.get('teacher_name')
                    if not teacher: continue

                    missed_earlier_opportunity = False
                    for earlier_slot_idx in earlier_slots_indices:
                        # إذا كان الأستاذ يعمل بالفعل في هذه الفترة المبكرة، فهي ليست فرصة
                        if (day_idx, earlier_slot_idx) in teacher_schedule_map.get(teacher, set()):
                            continue

                        # ✨ تم إرجاع هذا المنطق التفصيلي من النسخة الأصلية
                        prof_constraints = special_constraints.get(teacher, {})
                        first_day = first_work_day_map.get(teacher)
                        is_first_day = (first_day is not None and day_idx == first_day)
                        
                        if is_first_day:
                            if prof_constraints.get('start_d1_s2') and earlier_slot_idx < 1:
                                continue # تخطى هذه الفترة لأنها تخالف قيد الأستاذ
                            if prof_constraints.get('start_d1_s3') and earlier_slot_idx < 2:
                                continue # تخطى هذه الفترة لأنها تخالف قيد الأستاذ

                        # إذا كانت هناك محاضرة في قاعة كبيرة في تلك الفترة، لا يمكن استخدامها
                        if any(lec.get('room_type') == 'كبيرة' for lec in schedule[level][day_idx][earlier_slot_idx]):
                            continue
                        
                        # تحقق مما إذا كانت هناك قاعة متاحة من نفس النوع المطلوب
                        room_type_needed = lecture.get('room_type')
                        all_rooms_of_type = {r['name'] for r in rooms_data if r.get('type') == room_type_needed}
                        occupied_rooms_in_earlier_slot = room_schedule_map.get((day_idx, earlier_slot_idx), set())

                        if all_rooms_of_type - occupied_rooms_in_earlier_slot:
                            missed_earlier_opportunity = True
                            break
                    
                    if missed_earlier_opportunity:
                        conflicts_list.append({
                            "course_name": "قيد ضغط الحصص",
                            "teacher_name": teacher,
                            "reason": f"توجد حصة في آخر فترة ({last_slot_index + 1}) مع وجود فرصة لوضعها في وقت أبكر.",
                            "penalty": penalty,
                            "involved_lectures": [lecture]
                        })

    # --- الخطوة 7: إزالة التكرارات ---
    unique_failures = {}
    for failure in conflicts_list:
        key = (failure.get('reason'), failure.get('teacher_name'), failure.get('course_name'))
        if key not in unique_failures:
            unique_failures[key] = failure

    return list(unique_failures.values())


# =====================================================================
# START: PROGRESS CALCULATION HELPER
# =====================================================================
def calculate_progress_percentage(failures_list):
    """
    تحسب نسبة التقدم بناءً على منطق صارم:
    - 0% إذا كان هناك أي خطأ صارم أو نقص في المواد.
    - تحسب النسبة بناءً على آخر 10 أخطاء مرنة فقط.
    """
    # 1. حساب التكلفة الصارمة (أي عقوبة قيمتها 100 أو أكثر)
    hard_cost = sum(f.get('penalty', 1) for f in failures_list if f.get('penalty', 1) >= 100)

    # 2. إذا كانت هناك أخطاء صارمة، فالتقدم هو صفر
    if hard_cost > 0:
        return 0.0
    else:
        # 3. إذا لم تكن هناك أخطاء صارمة، نحسب عدد الأخطاء المرنة
        soft_error_count = len([f for f in failures_list if f.get('penalty', 1) < 100])
        # 4. نستخدم المعادلة القديمة الصارمة مع عدد الأخطاء المرنة
        return max(0, (10 - soft_error_count) / 10 * 100)

# =====================================================================
# END: PROGRESS CALCULATION HELPER
# =====================================================================

# النسخة النهائية والشاملة للدالة
def calculate_slot_fitness(teacher_name, day_idx, slot_idx, teacher_schedule, special_constraints, prefer_morning_slots=False):
    """
    تحسب جودة الخانة مع مكافآت وعقوبات لكل القيود المرنة.
    """
    fitness = 100  # درجة أساسية
    teacher_slots = teacher_schedule.get(teacher_name, set())
    prof_constraints = special_constraints.get(teacher_name, {})

    # 1. مكافأة لوضع المحاضرات في نفس اليوم (للتجميع)
    slots_on_same_day = {s for d, s in teacher_slots if d == day_idx}
    if slots_on_same_day:
        fitness += 50
        is_adjacent = any(abs(slot_idx - existing_slot_idx) == 1 for existing_slot_idx in slots_on_same_day)
        if is_adjacent:
            fitness += 150

    # 2. مكافأة للأيام المتتالية (إذا طُلب ذلك)
    distribution_rule = prof_constraints.get('distribution_rule', 'غير محدد')
    if 'متتاليان' in distribution_rule or 'متتالية' in distribution_rule:
        worked_days = {d for d, s in teacher_slots}
        if worked_days:
            is_adjacent_day = any(abs(day_idx - worked_day) == 1 for worked_day in worked_days)
            if is_adjacent_day:
                fitness += 200

    # --- بداية الإضافة الجديدة: عقوبة على خرق أوقات البدء/الانتهاء (بشكل مرن) ---
    # 3. نطبق هذه العقوبة فقط في حال عدم تحديد الأيام يدوياً
    # (لأن الحالة اليدوية يتم فرضها كقيد صارم في دالة is_placement_valid)
    
    # عقوبة على البدء المبكر جداً
    if prof_constraints.get('start_d1_s2') and slot_idx < 1:
        fitness -= 100  # عقوبة لوضع محاضرة في الحصة الأولى
    if prof_constraints.get('start_d1_s3') and slot_idx < 2:
        fitness -= 100  # عقوبة إضافية لوضعها في الحصة الأولى أو الثانية

    # عقوبة على الإنهاء المتأخر جداً
    if prof_constraints.get('end_s3') and slot_idx > 2:
        fitness -= 100  # عقوبة لوضع محاضرة بعد الحصة الثالثة
    if prof_constraints.get('end_s4') and slot_idx > 3:
        fitness -= 100  # عقوبة إضافية لوضعها بعد الحصة الرابعة
    # --- نهاية الإضافة الجديدة ---
    
    # --- الإضافة الجديدة: مكافأة للفترات الصباحية ---
    # إذا كانت الحصة من الثلاثة الأوائل (0, 1, 2)
    if prefer_morning_slots and slot_idx <= 2:
        fitness += 25 # مكافأة كبيرة لتشجيع اختيار الفترات الصباحية
            
    return fitness

# ✨✨✨ النسخة الجديدة والمبسطة - استبدل الدالة بالكامل بهذه ✨✨✨
def is_placement_valid(lecture, day_idx, slot_idx, final_schedule, teacher_schedule, room_schedule, teacher_constraints, special_constraints, identifiers_by_level, rules_grid, globally_unavailable_slots, rooms_data, saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule):
    teacher = lecture.get('teacher_name')

    # --- 1. التحقق من القيود التي لا تتعلق بالقاعات ---
    if (day_idx, slot_idx) in globally_unavailable_slots or \
       (day_idx, slot_idx) in teacher_schedule.get(teacher, set()):
        return False, "Slot unavailable for teacher or general rest period"

    saturday_idx = day_to_idx.get('السبت', -1)
    if saturday_idx != -1 and saturday_teachers and day_idx == saturday_idx and teacher not in saturday_teachers:
        return False, "الأستاذ غير مسموح له بالعمل يوم السبت"

    prof_manual_days_indices = teacher_constraints.get(teacher, {}).get('allowed_days')
    prof_special_constraints = special_constraints.get(teacher, {})
    if prof_special_constraints.get('always_s2_to_s4'):
        if slot_idx < 1 or slot_idx > 3: return False, "Strict violation: always_s2_to_s4"
    else:
        if prof_manual_days_indices:
            if day_idx not in prof_manual_days_indices: return False, "Manual day constraint violation"
            first_manual_day_idx, last_manual_day_idx = min(prof_manual_days_indices), max(prof_manual_days_indices)
            if day_idx == first_manual_day_idx and ((prof_special_constraints.get('start_d1_s2') and slot_idx < 1) or (prof_special_constraints.get('start_d1_s3') and slot_idx < 2)): return False, "Manual start time violation"
            if day_idx == last_manual_day_idx and ((prof_special_constraints.get('end_s3') and slot_idx > 2) or (prof_special_constraints.get('end_s4') and slot_idx > 3)): return False, "Manual end time violation"
        else:
            teacher_slots = teacher_schedule.get(teacher, set())
            if not teacher_slots or day_idx < min(d for d, s in teacher_slots):
                if (prof_special_constraints.get('start_d1_s2') and slot_idx < 1) or (prof_special_constraints.get('start_d1_s3') and slot_idx < 2): return False, "Start time violation"

    # --- 2. استدعاء المساعد للتحقق من كل ما يتعلق بالقاعات والمستوى ---
    available_room = _find_valid_and_available_room(lecture, day_idx, slot_idx, final_schedule, room_schedule, rooms_data, rules_grid, identifiers_by_level, level_specific_large_rooms, specific_small_room_assignments)

    if not available_room:
        return False, "No valid and available room found"

    # --- 3. التحقق من قيد التوالي (آخر قيد) ---
    rule = consecutive_large_hall_rule
    if rule != 'none' and lecture.get('room_type') == 'كبيرة' and slot_idx > 0:
        for level in lecture.get('levels', []):
            previous_slot_lectures = final_schedule.get(level, [[]] * (slot_idx + 1))[day_idx][slot_idx - 1]
            if any(prev_lec.get('room') == available_room and (rule == 'all' or rule == available_room) for prev_lec in previous_slot_lectures):
                return False, f"Consecutive large hall violation for room {available_room}"

    return True, available_room

# ================== بداية الكود الجديد ==================
# هذه الدالة الجديدة ستحل محل دالتي التحقق من التوزيع القديمتين
# ================== بداية الكود الجديد المقترح ==================

def validate_teacher_constraints_in_solution(teacher_schedule, special_constraints, teacher_constraints, lectures_by_teacher_map, distribution_rule_type, saturday_teachers, teacher_pairs, day_to_idx, last_slot_restrictions, num_slots, constraint_severities, max_sessions_per_day=None, non_sharing_teacher_pairs=[]):
    """
    النسخة النهائية: تتحقق من كل قيود الأساتذة وتضيف قائمة المحاضرات المتورطة (`involved_lectures`) لكل خطأ.
    """

    failures = []

    # --- 1. التحقق من قيود الأيام اليدوية (صارم دائماً) ---
    for teacher_name, constraints in teacher_constraints.items():
        if 'allowed_days' in constraints:
            allowed_days_set = constraints['allowed_days']
            assigned_slots = teacher_schedule.get(teacher_name, set())
            for day_idx, _ in assigned_slots:
                if day_idx not in allowed_days_set:
                    failures.append({
                        "course_name": "قيد الأيام اليدوية", 
                        "teacher_name": teacher_name,
                        "reason": "الأستاذ يعمل في يوم غير مسموح به يدويًا.",
                        "penalty": 100, # ✨ هذا قيد صارم دائماً
                        "involved_lectures": lectures_by_teacher_map.get(teacher_name, [])
                    })
                    break 

    # --- 2. التحقق من أوقات البدء والانتهاء (صارمة دائماً) ---
    start_end_time_failures = validate_start_end_times(teacher_schedule, special_constraints, teacher_constraints)
    for failure in start_end_time_failures:
        teacher_name = failure.get('teacher_name')
        if teacher_name:
            failure["involved_lectures"] = lectures_by_teacher_map.get(teacher_name, [])
        failures.append(failure)

    # --- 3. التحقق من بقية القيود (الآن أصبحت ديناميكية) ---
    saturday_idx = day_to_idx.get('السبت', -1)
    if saturday_idx != -1 and saturday_teachers:
        # ✨ تحديد العقوبة بناءً على اختيار المستخدم
        penalty = SEVERITY_PENALTIES.get(constraint_severities.get('saturday_work', 'low'), 1)
        for teacher_name, slots in teacher_schedule.items():
            if teacher_name not in saturday_teachers and any(day == saturday_idx for day, _ in slots):
                failures.append({
                    "course_name": "قيد السبت", "teacher_name": teacher_name,
                    "reason": "الأستاذ لا يجب أن يعمل يوم السبت.", "penalty": penalty,
                    "involved_lectures": lectures_by_teacher_map.get(teacher_name, [])
                })

    if num_slots > 0 and last_slot_restrictions:
        penalty = SEVERITY_PENALTIES.get(constraint_severities.get('last_slot', 'low'), 1)
        for teacher_name, restriction in last_slot_restrictions.items():
            teacher_slots = teacher_schedule.get(teacher_name, set())
            if not teacher_slots: continue

            restricted_indices = []
            if restriction == 'last_1' and num_slots >= 1: restricted_indices.append(num_slots - 1)
            elif restriction == 'last_2' and num_slots >= 2: restricted_indices.extend([num_slots - 1, num_slots - 2])

            if any(slot_idx in restricted_indices for _, slot_idx in teacher_slots):
                failures.append({
                    "course_name": f"قيد آخر الحصص", "teacher_name": teacher_name,
                    "reason": f"الأستاذ لا يجب أن يعمل في آخر {len(restricted_indices)} حصص.", "penalty": penalty,
                    "involved_lectures": lectures_by_teacher_map.get(teacher_name, [])
                })

    if max_sessions_per_day:
        penalty = SEVERITY_PENALTIES.get(constraint_severities.get('max_sessions', 'low'), 1)
        for teacher_name, slots in teacher_schedule.items():
            sessions_per_day = defaultdict(int)
            for day_idx, _ in slots: sessions_per_day[day_idx] += 1

            for day_idx, count in sessions_per_day.items():
                if count > max_sessions_per_day:
                    failures.append({
                        "course_name": "قيد الحصص اليومية", "teacher_name": teacher_name,
                        "reason": f"تجاوز الحد الأقصى للحصص ({count} > {max_sessions_per_day}).", "penalty": penalty,
                        "involved_lectures": lectures_by_teacher_map.get(teacher_name, [])
                    })

    # الكود الجديد (الصحيح)
    if teacher_pairs or non_sharing_teacher_pairs:
        # ✨ نقوم بإنشاء القاموس هنا في البداية إذا كان أي من القيدين مستخدماً
        teacher_work_days = {t: {d for d, s in sl} for t, sl in teacher_schedule.items()}

        if teacher_pairs:
            penalty = SEVERITY_PENALTIES.get(constraint_severities.get('teacher_pairs', 'low'), 1)
            for t1, t2 in teacher_pairs:
                days1, days2 = teacher_work_days.get(t1, set()), teacher_work_days.get(t2, set())
                if days1 != days2:
                    involved = lectures_by_teacher_map.get(t1, []) + lectures_by_teacher_map.get(t2, [])
                    failures.append({
                        "course_name": "قيد الأزواج", "teacher_name": f"{t1} و {t2}",
                        "reason": "أيام عمل الأستاذين غير متطابقة.", "penalty": penalty,
                        "involved_lectures": involved
                    })

        if non_sharing_teacher_pairs:
            penalty = SEVERITY_PENALTIES.get(constraint_severities.get('non_sharing_days', 'hard'), 100)
            for t1, t2 in non_sharing_teacher_pairs:
                days1 = teacher_work_days.get(t1, set())
                days2 = teacher_work_days.get(t2, set())

                # التحقق مما إذا كان هناك تقاطع في أيام العمل
                if days1.intersection(days2):
                    involved = lectures_by_teacher_map.get(t1, []) + lectures_by_teacher_map.get(t2, [])
                    failures.append({
                        "course_name": "قيد عدم التشارك", "teacher_name": f"{t1} و {t2}",
                        "reason": "يجب ألا يعمل هذان الأستاذان في نفس الأيام.", "penalty": penalty,
                        "involved_lectures": involved
                    })
    
    # --- 4. التحقق من قيود التوزيع ---
    penalty = SEVERITY_PENALTIES.get(constraint_severities.get('distribution', 'low'), 1)
    for teacher_name, prof_constraints in special_constraints.items():
        if teacher_constraints.get(teacher_name, {}).get('allowed_days'): continue
        rule = prof_constraints.get('distribution_rule', 'غير محدد')
        if rule == 'غير محدد': continue

        assigned_slots = teacher_schedule.get(teacher_name, set())
        if not assigned_slots: continue

        day_indices = sorted(list({d for d, s in assigned_slots}))
        num_days = len(day_indices)
        target_days = 0
        if 'يومان' in rule or 'يومين' in rule: target_days = 2
        elif 'ثلاثة أيام' in rule or '3 أيام' in rule: target_days = 3
        if target_days == 0: continue

        involved_lectures = lectures_by_teacher_map.get(teacher_name, [])

        if distribution_rule_type == 'required' and num_days != target_days:
            failures.append({
                "course_name": "قيد التوزيع (صارم)", "teacher_name": teacher_name,
                "reason": f"يجب أن يعمل {target_days} أيام بالضبط (يعمل حالياً {num_days}).", "penalty": 100, # هذا يبقى صارم
                "involved_lectures": involved_lectures
            })
        elif distribution_rule_type == 'allowed' and num_days > target_days:
            failures.append({
                "course_name": "قيد التوزيع (مرن)", "teacher_name": teacher_name,
                "reason": f"يجب أن يعمل {target_days} أيام كحد أقصى (يعمل حالياً {num_days}).", "penalty": penalty,
                "involved_lectures": involved_lectures
            })

        if 'متتاليان' in rule or 'متتالية' in rule:
            if num_days > 1 and any(day_indices[i+1] - day_indices[i] != 1 for i in range(num_days - 1)):
                failures.append({
                    "course_name": "قيد التوزيع", "teacher_name": teacher_name,
                    "reason": "أيام عمل الأستاذ ليست متتالية كما هو مطلوب.", "penalty": penalty,
                    "involved_lectures": involved_lectures
                })

    return failures

# ✨✨✨ النسخة النهائية والصحيحة - استبدل الدالة بالكامل بهذه ✨✨✨
def validate_start_end_times(teacher_schedule, special_constraints, teacher_constraints):
    failures = []
    for teacher_name, prof_constraints in special_constraints.items():

        # --- الحالة الأولى: القيد الشامل (له الأولوية القصوى) ---
        if prof_constraints.get('always_s2_to_s4'):
            assigned_slots = teacher_schedule.get(teacher_name, set())
            if not assigned_slots: continue
            
            slots_by_day = defaultdict(list)
            for day, slot in assigned_slots: 
                slots_by_day[day].append(slot)
            
            for day, slots in slots_by_day.items():
                min_slot, max_slot = min(slots), max(slots)
                if min_slot < 1:
                    failures.append({"course_name": "قيد وقت البدء", "teacher_name": teacher_name, "reason": "قيد (كل الأيام): بدأ قبل الحصة الثانية.", "penalty": 100})
                if max_slot > 3:
                    failures.append({"course_name": "قيد وقت الإنهاء", "teacher_name": teacher_name, "reason": "قيد (كل الأيام): انتهى بعد الحصة الرابعة.", "penalty": 100})
            continue # ننتقل للأستاذ التالي لأن هذا القيد يلغي ما بعده

        # --- الحالة الثانية: لا يوجد قيد شامل، نتحقق من القيود الفردية ---
        has_start_end = any(k in prof_constraints for k in ['start_d1_s2', 'start_d1_s3', 'end_s3', 'end_s4'])
        if not has_start_end: continue

        assigned_slots = teacher_schedule.get(teacher_name, set())
        if not assigned_slots: continue
        
        day_indices = {d for d, s in assigned_slots}
        if not day_indices: continue
        
        first_day_worked, last_day_worked = min(day_indices), max(day_indices)
        
        prof_manual_days_indices = teacher_constraints.get(teacher_name, {}).get('allowed_days')

        if prof_manual_days_indices:
            # --- الاحتمال الأول: الأيام محددة يدويًا (قيود وعقوبات صارمة) ---
            min_slot_on_first_day = min(s for d, s in assigned_slots if d == first_day_worked)
            if prof_constraints.get('start_d1_s2') and min_slot_on_first_day < 1:
                failures.append({"course_name": "قيد البدء اليدوي", "teacher_name": teacher_name, "reason": "بدأ قبل الحصة الثانية في أول يوم عمل.", "penalty": 100})
            if prof_constraints.get('start_d1_s3') and min_slot_on_first_day < 2:
                failures.append({"course_name": "قيد البدء اليدوي", "teacher_name": teacher_name, "reason": "بدأ قبل الحصة الثالثة في أول يوم عمل.", "penalty": 100})
            
            max_slot_on_last_day = max(s for d, s in assigned_slots if d == last_day_worked)
            if prof_constraints.get('end_s3') and max_slot_on_last_day > 2:
                failures.append({"course_name": "قيد الإنهاء اليدوي", "teacher_name": teacher_name, "reason": "انتهى بعد الحصة الثالثة في آخر يوم عمل.", "penalty": 100})
            if prof_constraints.get('end_s4') and max_slot_on_last_day > 3:
                failures.append({"course_name": "قيد الإنهاء اليدوي", "teacher_name": teacher_name, "reason": "انتهى بعد الحصة الرابعة في آخر يوم عمل.", "penalty": 100})
        
        else:
            # --- الاحتمال الثاني: الأيام تلقائية (قيود وعقوبات مرنة) ---
            min_slot_on_first_day = min(s for d, s in assigned_slots if d == first_day_worked)
            if prof_constraints.get('start_d1_s2') and min_slot_on_first_day < 1:
                failures.append({"course_name": "قيد وقت البدء", "teacher_name": teacher_name, "reason": "بدأ قبل الحصة الثانية في أول يوم عمل له.", "penalty": 1})
            if prof_constraints.get('start_d1_s3') and min_slot_on_first_day < 2:
                failures.append({"course_name": "قيد وقت البدء", "teacher_name": teacher_name, "reason": "بدأ قبل الحصة الثالثة في أول يوم عمل له.", "penalty": 1})
            
            max_slot_on_last_day = max(s for d, s in assigned_slots if d == last_day_worked)
            if prof_constraints.get('end_s3') and max_slot_on_last_day > 2:
                failures.append({"course_name": "قيد وقت الإنهاء", "teacher_name": teacher_name, "reason": "انتهى بعد الحصة الثالثة في آخر يوم عمل له.", "penalty": 1})
            if prof_constraints.get('end_s4') and max_slot_on_last_day > 3:
                failures.append({"course_name": "قيد وقت الإنهاء", "teacher_name": teacher_name, "reason": "انتهى بعد الحصة الرابعة في آخر يوم عمل له.", "penalty": 1})
                
    return failures

# ================== نهاية الكود الجديد المقترح ==================

def get_contained_identifier(course_name, identifiers_for_level):
    """تبحث عن أول معرّف من القائمة موجود داخل اسم المادة"""
    if not identifiers_for_level:
        return None
    for identifier in identifiers_for_level:
        if identifier in course_name:
            return identifier
    return None

def mutate(
    schedule, all_lectures, days, slots, rooms_data, teachers, all_levels,
    teacher_constraints, special_constraints, identifiers_by_level, rules_grid, lectures_by_teacher_map,
    globally_unavailable_slots, saturday_teachers, day_to_idx, 
    level_specific_large_rooms, specific_small_room_assignments, constraint_severities, consecutive_large_hall_rule, 
    prefer_morning_slots,
    extra_teachers_on_hard_error,
    soft_error_shake_probability,
    stagnation_counter=0,
    mutation_intensity=1.0, 
    non_sharing_teacher_pairs=[]
    ):
    """
    تقوم بطفرة ذكية وموجهة (نسخة مدمجة):
    - شدة متكيفة (Adaptive Intensity) بناءً على الركود.
    - هزة مترابطة (Related Shake) لاستهداف ذكي.
    - إصلاح بالندم (Regret Repair) لإعادة بناء فعالة.
    """
    mutated_schedule = copy.deepcopy(schedule)
    teachers_to_shake = []

    # --- 1. تشخيص الأخطاء ---
    current_failures = calculate_schedule_cost(
        mutated_schedule, days, slots, teachers, rooms_data, all_levels,
        identifiers_by_level, special_constraints, teacher_constraints, 'allowed',
        lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, [],
        day_to_idx, rules_grid, {}, level_specific_large_rooms, 
        specific_small_room_assignments, constraint_severities, max_sessions_per_day=99, 
        consecutive_large_hall_rule=consecutive_large_hall_rule, prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs
    )

    scheduled_ids = {lec.get('id') for grid in mutated_schedule.values() for day in grid for slot in day for lec in slot}
    unplaced_lectures = [lec for lec in all_lectures if lec.get('id') not in scheduled_ids and lec.get('teacher_name')]
    
    # --- 2. تحديد الأساتذة المستهدفين وآلية الهزة ---
    adaptive_bonus = stagnation_counter // 10
    
    base_intensity = math.ceil(mutation_intensity * extra_teachers_on_hard_error) if mutation_intensity > 1.0 else extra_teachers_on_hard_error
    
    if unplaced_lectures:
        teacher_name = random.choice(unplaced_lectures).get('teacher_name')
        if teacher_name: teachers_to_shake.append(teacher_name)
    else:
        teachers_with_hard_errors = {err.get('teacher_name') for err in current_failures if err.get('teacher_name') and err.get('penalty', 1) >= 100}
        
        if teachers_with_hard_errors:
            main_teacher = random.choice(list(teachers_with_hard_errors))
            teachers_to_shake.append(main_teacher)
            
            final_intensity = base_intensity + adaptive_bonus
            
            teacher_work_days = defaultdict(set)
            for level_grid in mutated_schedule.values():
                for d, day_slots in enumerate(level_grid):
                    for lects in day_slots:
                        for l in lects:
                            if l.get('teacher_name'): teacher_work_days[l['teacher_name']].add(d)
            main_teacher_days = teacher_work_days.get(main_teacher, set())
            related_teachers = [t['name'] for t in teachers if t['name'] != main_teacher and main_teacher_days.intersection(teacher_work_days.get(t['name'], set()))]
            unrelated_teachers = [t['name'] for t in teachers if t['name'] != main_teacher and t['name'] not in related_teachers]
            num_extra = min(len(related_teachers) + len(unrelated_teachers), final_intensity)
            if num_extra > 0:
                num_from_related = min(len(related_teachers), num_extra)
                teachers_to_shake.extend(random.sample(related_teachers, num_from_related))
                num_remaining_to_pick = num_extra - num_from_related
                if num_remaining_to_pick > 0 and unrelated_teachers:
                    num_from_unrelated = min(len(unrelated_teachers), num_remaining_to_pick)
                    teachers_to_shake.extend(random.sample(unrelated_teachers, num_from_unrelated))

        elif any(f.get('teacher_name') for f in current_failures):
            teachers_with_soft_errors = {err.get('teacher_name') for err in current_failures if err.get('teacher_name') and err.get('penalty', 1) < 100}
            if teachers_with_soft_errors:
                main_teacher = random.choice(list(teachers_with_soft_errors))
                teachers_to_shake.append(main_teacher)
                
                # === ✨✨✨ التصحيح الذي تم إجراؤه هنا ✨✨✨ ===
                # استخدام math.ceil يضمن أن القوة الأساسية تكون 1 على الأقل إذا كانت النسبة أكبر من صفر
                base_intensity_soft = math.ceil(soft_error_shake_probability)
                
                final_intensity_soft = base_intensity_soft + adaptive_bonus
                
                other_teachers = [t['name'] for t in teachers if t['name'] != main_teacher]
                if other_teachers and final_intensity_soft > 0:
                    num_extra = min(len(other_teachers), final_intensity_soft)
                    teachers_to_shake.extend(random.sample(other_teachers, num_extra))
        elif teachers:
            num_to_shake = max(1, int(len(teachers) * 0.1 * mutation_intensity))
            selected_teachers = random.sample(teachers, num_to_shake)
            teachers_to_shake = [t['name'] for t in selected_teachers]

    # --- 3. تنفيذ التدمير والإصلاح الموجه بالندم ---
    if not teachers_to_shake: return mutated_schedule

    unique_teachers_to_shake = list(set(teachers_to_shake))
    lectures_to_reinsert = [lec for lec in all_lectures if lec.get('teacher_name') in unique_teachers_to_shake]
    if not lectures_to_reinsert: return mutated_schedule

    ids_to_remove = {lec['id'] for lec in lectures_to_reinsert}
    for level_grid in mutated_schedule.values():
        for day_slots in level_grid:
            for slot_lectures in day_slots:
                slot_lectures[:] = [lec for lec in slot_lectures if lec.get('id') not in ids_to_remove]

    teacher_schedule_rebuild = defaultdict(set)
    room_schedule_rebuild = defaultdict(set)
    for grid in mutated_schedule.values():
        for day_idx, day in enumerate(grid):
            for slot_idx, lectures in enumerate(day):
                for lec in lectures:
                    if lec.get('teacher_name'): teacher_schedule_rebuild[lec['teacher_name']].add((day_idx, slot_idx))
                    if lec.get('room'): room_schedule_rebuild[lec.get('room')].add((day_idx, slot_idx))

    all_possible_slots = [(d, s) for d in range(len(days)) for s in range(len(slots))]
    kwargs_for_regret = {
        "rooms_data": rooms_data, "teacher_constraints": teacher_constraints, "special_constraints": special_constraints,
        "identifiers_by_level": identifiers_by_level, "rules_grid": rules_grid, "globally_unavailable_slots": globally_unavailable_slots,
        "saturday_teachers": saturday_teachers, "day_to_idx": day_to_idx, "level_specific_large_rooms": level_specific_large_rooms,
        "specific_small_room_assignments": specific_small_room_assignments, "consecutive_large_hall_rule": consecutive_large_hall_rule
    }

    while lectures_to_reinsert:
        lecture_with_regret = []
        for lec in lectures_to_reinsert:
            regret_score = _calculate_lecture_regret(
                lec, mutated_schedule, teacher_schedule_rebuild, room_schedule_rebuild, all_possible_slots, **kwargs_for_regret
            )
            lecture_with_regret.append((lec, regret_score))
        
        lecture_with_regret.sort(key=lambda x: x[1])
        most_constrained_lecture = lecture_with_regret[0][0]

        find_slot_for_single_lecture(
            most_constrained_lecture, mutated_schedule, teacher_schedule_rebuild, room_schedule_rebuild, 
            days, slots, rules_grid, rooms_data, teacher_constraints, globally_unavailable_slots, 
            special_constraints, [], all_possible_slots, identifiers_by_level,
            True, saturday_teachers, day_to_idx, level_specific_large_rooms, 
            specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots
        )
        
        lectures_to_reinsert = [lec for lec in lectures_to_reinsert if lec['id'] != most_constrained_lecture['id']]
        
    return mutated_schedule

def _calculate_lecture_regret(lecture, temp_schedule, temp_teacher_schedule, temp_room_schedule, all_possible_slots, **kwargs):
    """
    تحسب "درجة الندم" لمحاضرة معينة عن طريق عد عدد الأماكن الصالحة المتاحة لها.
    """
    valid_placements = 0
    for day_idx, slot_idx in all_possible_slots:
        is_valid, _ = is_placement_valid(
            lecture, day_idx, slot_idx, temp_schedule, temp_teacher_schedule, temp_room_schedule, **kwargs
        )
        if is_valid:
            valid_placements += 1
    return valid_placements

def _shake_by_lectures(current_failures, all_lectures, k):
    """
    استراتيجية الهز الأصلية: تختار k محاضرات بناءً على الأخطاء والعشوائية.
    """
    hard_error_lectures = list({l['id']: l for f in current_failures if f.get('penalty', 0) >= 100 for l in f.get('involved_lectures', [])}.values())
    other_lectures = [l for l in all_lectures if l.get('teacher_name') and l['id'] not in {h['id'] for h in hard_error_lectures}]
    
    num_from_errors = min(len(hard_error_lectures), (k + 1) // 2) if hard_error_lectures else 0
    num_from_random = k - num_from_errors
    
    error_lecs_to_shake = random.sample(hard_error_lectures, num_from_errors) if num_from_errors > 0 else []
    random_lecs_to_shake = random.sample(other_lectures, min(num_from_random, len(other_lectures))) if num_from_random > 0 and other_lectures else []
    
    return error_lecs_to_shake + random_lecs_to_shake

def _shake_by_teachers(lectures_by_teacher_map, k):
    """
    استراتيجية هز جديدة: تختار أستاذ أو اثنين وتزيل كل محاضراتهم.
    """
    all_teachers = list(lectures_by_teacher_map.keys())
    if not all_teachers:
        return []
        
    num_teachers_to_shake = max(1, k // 4) # نهز أستاذ واحد لكل 4 درجات من k
    teachers_to_shake = random.sample(all_teachers, min(num_teachers_to_shake, len(all_teachers)))
    
    lectures_to_reinsert = []
    for teacher in teachers_to_shake:
        lectures_to_reinsert.extend(lectures_by_teacher_map.get(teacher, []))
    return lectures_to_reinsert

def _shake_by_days(current_solution, k, days):
    """
    استراتيجية هز جديدة: تختار يوماً عشوائياً وتزيل نسبة من محاضراته.
    """
    if not days:
        return []
    day_to_shake_idx = random.randrange(len(days))
    
    lectures_on_day = []
    for level_grid in current_solution.values():
        for slot_lectures in level_grid[day_to_shake_idx]:
            lectures_on_day.extend(slot_lectures)
            
    if not lectures_on_day:
        return []
        
    # نزيل نسبة من المحاضرات تعتمد على قوة k
    removal_fraction = (k / 10) * 0.25 # عند k=10 نزيل 25% من محاضرات اليوم
    num_to_remove = min(len(lectures_on_day), int(len(lectures_on_day) * removal_fraction))
    
    return random.sample(lectures_on_day, max(1, num_to_remove))

# =====================================================================
# START: VNS LOCAL SEARCH (IMPROVED WITH SWAP MOVE)
# =====================================================================
def run_vns_local_search(
    schedule_to_improve, all_lectures, days, slots, rooms_data, teachers, all_levels, 
    identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, 
    lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, 
    day_to_idx, rules_grid, prioritize_primary, level_specific_large_rooms, 
    specific_small_room_assignments, constraint_severities, last_slot_restrictions, max_iterations=1,
    consecutive_large_hall_rule="none", prefer_morning_slots=False, use_strict_hierarchy=False, max_sessions_per_day=None, non_sharing_teacher_pairs=[]
):
    """
    بحث محلي ذكي وموجه بالأولويات:
    1. يستهدف الأخطاء الصارمة أولاً.
    2. ثم يستهدف الأخطاء المرنة.
    3. ثم يقوم بالتبديل العشوائي للتحسينات الطفيفة.
    """
    improved_schedule = copy.deepcopy(schedule_to_improve)
    
    def _evaluate(schedule):
        return calculate_fitness(
            schedule, all_lectures, days, slots, teachers, rooms_data, all_levels, 
            identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type, 
            lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs, 
            day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms, 
            specific_small_room_assignments, constraint_severities=constraint_severities, use_strict_hierarchy=use_strict_hierarchy,
            max_sessions_per_day=max_sessions_per_day, consecutive_large_hall_rule=consecutive_large_hall_rule,
            prefer_morning_slots=prefer_morning_slots, non_sharing_teacher_pairs=non_sharing_teacher_pairs
        )

    current_fitness, _ = _evaluate(improved_schedule)

    for _ in range(max_iterations):
        temp_schedule = copy.deepcopy(improved_schedule)
        
        # --- بداية المنطق الجديد الموجه بالأولويات ---
        _, failures_list = _evaluate(temp_schedule)
        hard_errors = [f for f in failures_list if f.get('penalty', 0) >= 100]
        soft_errors = [f for f in failures_list if 0 < f.get('penalty', 0) < 100]

        target_error = None
        move_type = 'swap' # الافتراضي هو التبديل

        if hard_errors:
            # الأولوية القصوى: إصلاح الأخطاء الصارمة
            target_error = random.choice(hard_errors)
            move_type = 'repair'
        elif soft_errors:
            # الأولوية الثانية: إصلاح الأخطاء المرنة
            target_error = random.choice(soft_errors)
            move_type = 'repair'

        if move_type == 'repair':
            involved_teachers = set()
            teacher_name = target_error.get('teacher_name')
            if teacher_name and teacher_name != "N/A":
                if " و " in str(teacher_name): involved_teachers.update(str(teacher_name).split(' و '))
                else: involved_teachers.add(teacher_name)
            
            if not involved_teachers: continue

            lectures_to_reinsert = [lec for lec in all_lectures if lec.get('teacher_name') in involved_teachers]
            ids_to_remove = {lec['id'] for lec in lectures_to_reinsert}

            for level_grid in temp_schedule.values():
                for day_slots in level_grid:
                    for slot_lectures in day_slots:
                        slot_lectures[:] = [lec for lec in slot_lectures if lec.get('id') not in ids_to_remove]
            
            temp_teacher_schedule = defaultdict(set); temp_room_schedule = defaultdict(set)
            for grid in temp_schedule.values():
                for d, day in enumerate(grid):
                    for s, lectures in enumerate(day):
                        for lec in lectures:
                            if lec.get('teacher_name'): temp_teacher_schedule[lec['teacher_name']].add((d, s))
                            if lec.get('room'): temp_room_schedule[lec.get('room')].add((d, s))
            
            primary_slots, reserve_slots = [], []
            for day_idx in range(len(days)):
                for slot_idx in range(len(slots)):
                    (primary_slots if any(rule.get('rule_type') == 'SPECIFIC_LARGE_HALL' for rule in rules_grid[day_idx][slot_idx]) else reserve_slots).append((day_idx, slot_idx))

            for lecture in sorted(lectures_to_reinsert, key=lambda l: calculate_lecture_difficulty(l, lectures_by_teacher_map.get(l.get('teacher_name'), []), special_constraints, teacher_constraints), reverse=True):
                find_slot_for_single_lecture(lecture, temp_schedule, temp_teacher_schedule, temp_room_schedule, days, slots, rules_grid, rooms_data, teacher_constraints, globally_unavailable_slots, special_constraints, primary_slots, reserve_slots, identifiers_by_level, prioritize_primary, saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots)

        elif move_type == 'swap':
            # إذا لا توجد أخطاء، قم بتبديل عشوائي لتحسين الضغط
            all_placements = []
            for level, grid in temp_schedule.items():
                for d, day in enumerate(grid):
                    for s, lectures in enumerate(day):
                        if lectures:
                            all_placements.append({'lec': random.choice(lectures), 'day': d, 'slot': s, 'level': level})
            
            if len(all_placements) < 2: continue
            
            p1, p2 = random.sample(all_placements, 2)
            lec1, d1, s1 = p1['lec'], p1['day'], p1['slot']
            lec2, d2, s2 = p2['lec'], p2['day'], p2['slot']

            if lec1['id'] == lec2['id']: continue

            temp_schedule[p1['level']][d1][s1] = [l for l in temp_schedule[p1['level']][d1][s1] if l['id'] != lec1['id']]
            temp_schedule[p2['level']][d2][s2] = [l for l in temp_schedule[p2['level']][d2][s2] if l['id'] != lec2['id']]
            temp_schedule[p1['level']][d2][s2].append(lec1)
            temp_schedule[p2['level']][d1][s1].append(lec2)
        # --- نهاية المنطق الجديد ---

        new_fitness, _ = _evaluate(temp_schedule)

        if new_fitness > current_fitness:
            improved_schedule = temp_schedule
            current_fitness = new_fitness

    return improved_schedule
# =====================================================================
# END: VNS LOCAL SEARCH (IMPROVED WITH SWAP MOVE)
# =====================================================================

def find_slot_for_single_lecture(lecture, final_schedule, teacher_schedule, room_schedule,
                                 days, slots, rules_grid, rooms_data,
                                 teacher_constraints, globally_unavailable_slots, special_constraints,
                                 primary_slots, reserve_slots, identifiers_by_level, prioritize_primary,
                                 saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots=False):
    teacher = lecture.get('teacher_name')
    if not teacher: 
        return False, "المادة غير مسندة لأستاذ"
    
    best_placement = None
    is_large_room_course = lecture.get('room_type') == 'كبيرة'
    
    args_for_placement = (lecture, final_schedule, teacher_schedule, teacher_constraints, special_constraints, identifiers_by_level, rules_grid, globally_unavailable_slots, room_schedule, rooms_data, saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots)

    if is_large_room_course and prioritize_primary:
        best_placement = _find_best_greedy_placement_in_slots(primary_slots, *args_for_placement)
        if not best_placement:
            best_placement = _find_best_greedy_placement_in_slots(reserve_slots, *args_for_placement)
    else:
        slots_to_search = primary_slots + reserve_slots
        if not is_large_room_course: 
            random.shuffle(slots_to_search)
        best_placement = _find_best_greedy_placement_in_slots(slots_to_search, *args_for_placement)

    if best_placement:
        d_idx, s_idx, room = best_placement["day_idx"], best_placement["slot_idx"], best_placement["room"]
        details = {
            "id": lecture['id'], 
            "name": lecture['name'], 
            "teacher_name": teacher, 
            "room": room, 
            "room_type": lecture['room_type'],
            "levels": lecture.get('levels', []) # <-- ✨ الإضافة الضرورية هنا
        }
        
        # --- بداية التصحيح ---
        # استخدام حلقة للمرور على قائمة المستويات بدلاً من المفتاح المفرد
        levels_for_lecture = lecture.get('levels', [])
        for level_to_place_in in levels_for_lecture:
            if level_to_place_in in final_schedule:
                final_schedule[level_to_place_in][d_idx][s_idx].append(details)
        # --- نهاية التصحيح ---
            
        teacher_schedule.setdefault(teacher, set()).add((d_idx, s_idx))
        room_schedule.setdefault(room, set()).add((d_idx, s_idx))
        if not teacher_constraints.get(teacher, {}).get('allowed_days'):
            teacher_constraints.setdefault(teacher, {}).setdefault('assigned_days', set()).add(d_idx)
        return True, "تمت الجدولة بنجاح في أفضل مكان"
    
    return False, "لم يتم العثور على أي فترة زمنية متاحة تحقق كل القيود."


def _find_best_greedy_placement_in_slots(slots_to_search, lecture, final_schedule, teacher_schedule, teacher_constraints, special_constraints, identifiers_by_level, rules_grid, globally_unavailable_slots, room_schedule, rooms_data, saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots=False):
    best_placement = None
    max_fitness = -1

    for day_idx, slot_idx in slots_to_search:
        # تمرير المعلومات الجديدة للدالة النهائية
        is_valid, result_or_reason = is_placement_valid(
            lecture, day_idx, slot_idx, final_schedule, teacher_schedule,
            room_schedule, teacher_constraints, special_constraints,
            identifiers_by_level, rules_grid, globally_unavailable_slots, rooms_data,
            saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule
        )
        if not is_valid: continue
        
        available_room = result_or_reason
        current_fitness = calculate_slot_fitness(lecture.get('teacher_name'), day_idx, slot_idx, teacher_schedule, special_constraints, prefer_morning_slots=prefer_morning_slots)

        if current_fitness > max_fitness:
            max_fitness = current_fitness
            best_placement = {"day_idx": day_idx, "slot_idx": slot_idx, "room": available_room}
    return best_placement

# ✨✨ --- بداية الإضافة: دالة مساعدة جديدة للبحث عن قاعة صالحة --- ✨✨
def _find_valid_and_available_room(lecture, day_idx, slot_idx, final_schedule, room_schedule, rooms_data, rules_grid, identifiers_by_level, level_specific_large_rooms, specific_small_room_assignments):
    """
    تقوم هذه الدالة بالبحث عن قاعة شاغرة وصالحة لمحاضرة معينة في فترة محددة،
    مع الأخذ في الاعتبار كل القيود المعقدة (قواعد الفترة، تخصيص القاعات، إلخ).
    """
    levels_for_lecture = lecture.get('levels', [])
    lecture_room_type_needed = lecture.get('room_type')
    required_halls_from_all_levels = set()
    allowed_types_per_level_list = []

    for level in levels_for_lecture:
        # التحقق من التعارضات الفورية داخل المستوى (قاعة كبيرة ومعرفات)
        lectures_in_slot = final_schedule[level][day_idx][slot_idx]
        if lectures_in_slot and (lecture_room_type_needed == 'كبيرة' or any(l.get('room_type') == 'كبيرة' for l in lectures_in_slot)):
            return None # خطأ: تعارض قاعة كبيرة

        current_identifier = get_contained_identifier(lecture['name'], identifiers_by_level.get(level, []))
        if current_identifier:
            used_identifiers = {get_contained_identifier(l['name'], identifiers_by_level.get(level, [])) for l in lectures_in_slot}
            if current_identifier in used_identifiers:
                return None # خطأ: تعارض معرفات

        # تجميع متطلبات القاعات المحددة
        course_full_name = f"{lecture.get('name')} ({level})"
        if room := specific_small_room_assignments.get(course_full_name):
            required_halls_from_all_levels.add(room)
        if lecture_room_type_needed == 'كبيرة':
            if room := level_specific_large_rooms.get(level):
                required_halls_from_all_levels.add(room)

        # تجميع أنواع القاعات المسموحة حسب قواعد الفترة الزمنية
        rules_for_slot = rules_grid[day_idx][slot_idx]
        level_specific_rules = [r for r in rules_for_slot if level in r.get('levels', [])]
        if any(r.get('rule_type') == 'NO_HALLS_ALLOWED' for r in level_specific_rules):
            return None # خطأ: الفترة ممنوعة لهذا المستوى

        if not level_specific_rules:
            allowed_types_per_level_list.append({'كبيرة', 'صغيرة'})
        else:
            current_level_allowed_types = set()
            for rule in level_specific_rules:
                rule_type = rule.get('rule_type')
                if rule_type == 'ANY_HALL': current_level_allowed_types.update(['كبيرة', 'صغيرة'])
                elif rule_type == 'SMALL_HALLS_ONLY': current_level_allowed_types.add('صغيرة')
                elif rule_type == 'SPECIFIC_LARGE_HALL':
                    current_level_allowed_types.add('كبيرة')
                    if hall := rule.get('hall_name'): required_halls_from_all_levels.add(hall)
            allowed_types_per_level_list.append(current_level_allowed_types)

    # التحقق النهائي من القيود المجمعة
    if len(required_halls_from_all_levels) > 1:
        return None # خطأ: متطلبات قاعات متضاربة

    final_allowed_types = set.intersection(*allowed_types_per_level_list) if allowed_types_per_level_list else set()
    if lecture_room_type_needed not in final_allowed_types:
        return None # خطأ: نوع القاعة غير مسموح به

    # إيجاد قاعة متاحة تحقق كل الشروط
    final_specific_hall = required_halls_from_all_levels.pop() if required_halls_from_all_levels else None
    return find_available_room(day_idx, slot_idx, room_schedule, rooms_data, [lecture_room_type_needed], final_specific_hall)
# ✨✨ --- نهاية الإضافة --- ✨✨

def find_available_room(day_idx, slot_idx, room_schedule, rooms_data, allowed_room_types, specific_hall=None):
    if specific_hall:
        if (day_idx, slot_idx) not in room_schedule.get(specific_hall, set()):
            for room in rooms_data:
                if room.get('name') == specific_hall and room.get('type') in allowed_room_types:
                    return specific_hall
        return None
    potential_rooms = [room for room in rooms_data if room.get("type") in allowed_room_types]
    random.shuffle(potential_rooms)
    for room in potential_rooms:
        room_name = room.get('name')
        if (day_idx, slot_idx) not in room_schedule.get(room_name, set()):
            return room_name
    return None

def calculate_lecture_difficulty(lecture, all_lectures_for_teacher, special_constraints, manual_days):
    """
    تحسب درجة الصعوبة لمحاضرة معينة بناءً على عدة عوامل.
    كلما زادت النقاط، كانت المحاضرة أصعب وتحتاج لأولوية أعلى.
    """
    score = 0
    teacher_name = lecture.get('teacher_name')

    # 1. نقاط للأساتذة ذوي الأيام المحددة يدوياً (أعلى أولوية)
    if teacher_name in manual_days:
        score += 1000

    # 2. نقاط لنوع القاعة (المورد النادر)
    if lecture.get('room_type') == 'كبيرة':
        score += 100

    # 3. نقاط لعبء الأستاذ
    # الأستاذ الذي لديه محاضرات أكثر يحصل على نقاط أعلى
    score += len(all_lectures_for_teacher) * 5

    # 4. نقاط لنوع قاعدة التوزيع
    prof_constraints = special_constraints.get(teacher_name, {})
    distribution_rule = prof_constraints.get('distribution_rule', 'غير محدد')
    difficulty_order = {
        'يومان متتاليان': 50,
        'ثلاثة أيام متتالية': 50,
        'يومان منفصلان': 40,
        'ثلاثة ايام منفصلة': 40,
        'غير محدد': 0
    }
    score += difficulty_order.get(distribution_rule, 0)

    # 5. نقاط للقيود اليدوية الأخرى (البدء والإنهاء)
    if prof_constraints.get('start_d1_s2') or prof_constraints.get('start_d1_s3'):
        score += 15
    if prof_constraints.get('end_s3') or prof_constraints.get('end_s4'):
        score += 15

    return score

# ==============================================================================
# === خوارزميات البناء المبدئي (Greedy Algorithms) ===
# ==============================================================================

def _find_best_greedy_placement_in_slots(slots_to_search, lecture, final_schedule, teacher_schedule, teacher_constraints, special_constraints, identifiers_by_level, rules_grid, globally_unavailable_slots, room_schedule, rooms_data, saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots=False):
    best_placement = None
    max_fitness = -1

    for day_idx, slot_idx in slots_to_search:
        # استدعاء دالة التحقق من صحة المكان
        is_valid, result_or_reason = is_placement_valid(
            lecture, day_idx, slot_idx, final_schedule, teacher_schedule,
            room_schedule, teacher_constraints, special_constraints,
            identifiers_by_level, rules_grid, globally_unavailable_slots, rooms_data,
            saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule
        )
        if not is_valid: 
            continue
        
        available_room = result_or_reason
        current_fitness = calculate_slot_fitness(lecture.get('teacher_name'), day_idx, slot_idx, teacher_schedule, special_constraints, prefer_morning_slots=prefer_morning_slots)

        if current_fitness > max_fitness:
            max_fitness = current_fitness
            best_placement = {"day_idx": day_idx, "slot_idx": slot_idx, "room": available_room}
            
    return best_placement

def find_slot_for_single_lecture(lecture, final_schedule, teacher_schedule, room_schedule,
                                 days, slots, rules_grid, rooms_data,
                                 teacher_constraints, globally_unavailable_slots, special_constraints,
                                 primary_slots, reserve_slots, identifiers_by_level, prioritize_primary,
                                 saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots=False):
    teacher = lecture.get('teacher_name')
    if not teacher: 
        return False, "المادة غير مسندة لأستاذ"
    
    best_placement = None
    is_large_room_course = lecture.get('room_type') == 'كبيرة'
    
    args_for_placement = (lecture, final_schedule, teacher_schedule, teacher_constraints, special_constraints, identifiers_by_level, rules_grid, globally_unavailable_slots, room_schedule, rooms_data, saturday_teachers, day_to_idx, level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots)

    if is_large_room_course and prioritize_primary:
        best_placement = _find_best_greedy_placement_in_slots(primary_slots, *args_for_placement)
        if not best_placement:
            best_placement = _find_best_greedy_placement_in_slots(reserve_slots, *args_for_placement)
    else:
        slots_to_search = primary_slots + reserve_slots
        if not is_large_room_course: 
            random.shuffle(slots_to_search)
        best_placement = _find_best_greedy_placement_in_slots(slots_to_search, *args_for_placement)

    if best_placement:
        d_idx, s_idx, room = best_placement["day_idx"], best_placement["slot_idx"], best_placement["room"]
        details = {
            "id": lecture['id'], 
            "name": lecture['name'], 
            "teacher_name": teacher, 
            "room": room, 
            "room_type": lecture['room_type'],
            "levels": lecture.get('levels', [])
        }
        
        levels_for_lecture = lecture.get('levels', [])
        for level_to_place_in in levels_for_lecture:
            if level_to_place_in in final_schedule:
                final_schedule[level_to_place_in][d_idx][s_idx].append(details)
            
        teacher_schedule.setdefault(teacher, set()).add((d_idx, s_idx))
        room_schedule.setdefault(room, set()).add((d_idx, s_idx))
        if not teacher_constraints.get(teacher, {}).get('allowed_days'):
            teacher_constraints.setdefault(teacher, {}).setdefault('assigned_days', set()).add(d_idx)
            
        return True, "تمت الجدولة بنجاح في أفضل مكان"
    
    return False, "لم يتم العثور على أي فترة زمنية متاحة تحقق كل القيود."

def run_greedy_search_for_best_result(
    log_q, lectures_sorted, days, slots, rules_grid, rooms_data, teachers, all_levels,
    teacher_constraints, globally_unavailable_slots, special_constraints,
    primary_slots, reserve_slots, identifiers_by_level, prioritize_primary,
    saturday_teachers, day_to_idx, level_specific_large_rooms,
    specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots,
    lectures_by_teacher_map, distribution_rule_type, teacher_pairs,
    constraint_severities, non_sharing_teacher_pairs,
    base_initial_schedule=None
):
    """
    تقوم بتشغيل الخوارزمية الطماعة 30 مرة وتختار أفضل نتيجة من حيث عدد المواد الناقصة ثم عدد الأخطاء.
    """
    best_result = {
        "schedule": {level: [[[] for _ in slots] for _ in days] for level in all_levels},
        "failures": [],
        "unplaced_count": float('inf')
    }
    num_of_runs = 30
    
    for run in range(num_of_runs):
        current_schedule = copy.deepcopy(base_initial_schedule) if base_initial_schedule else {level: [[[] for _ in slots] for _ in days] for level in all_levels}
        current_teacher_schedule = {t['name']: set() for t in teachers}
        current_room_schedule = {r['name']: set() for r in rooms_data}
        
        for grid in current_schedule.values():
            for d_idx, day in enumerate(grid):
                for s_idx, lectures in enumerate(day):
                    for lec in lectures:
                        if lec.get('teacher_name'): current_teacher_schedule[lec['teacher_name']].add((d_idx, s_idx))
                        if lec.get('room'): current_room_schedule[lec.get('room')].add((d_idx, s_idx))

        current_failures = []
        current_unplaced_count = 0

        for lecture in lectures_sorted:
            is_already_placed = any(lec.get('id') == lecture['id'] for grid in current_schedule.values() for day in grid for slot in day for lec in slot)
            if is_already_placed:
                continue

            success, message = find_slot_for_single_lecture(
                lecture, current_schedule, current_teacher_schedule, current_room_schedule,
                days, slots, rules_grid, rooms_data,
                teacher_constraints, globally_unavailable_slots, special_constraints,
                primary_slots, reserve_slots, identifiers_by_level,
                prioritize_primary, saturday_teachers, day_to_idx, level_specific_large_rooms,
                specific_small_room_assignments, consecutive_large_hall_rule,
                prefer_morning_slots=prefer_morning_slots
            )
            if not success:
                current_unplaced_count += 1
                current_failures.append({
                    "course_name": lecture.get('name'), "teacher_name": lecture.get('teacher_name'),
                    "reason": message
                })

        greedy_validation_failures = validate_teacher_constraints_in_solution(
            current_teacher_schedule, special_constraints, teacher_constraints,
            lectures_by_teacher_map, distribution_rule_type, saturday_teachers,
            teacher_pairs, day_to_idx, {}, len(slots), constraint_severities,
            max_sessions_per_day=None, non_sharing_teacher_pairs=non_sharing_teacher_pairs
        )
        current_failures.extend(greedy_validation_failures)

        # قمنا بتهميش رسائل المتابعة للطماعة حتى لا تزعجك في الشاشة السوداء لأنها سريعة جداً
        # log_q.put(f"   - المحاولة الطماعة {run + 1}/{num_of_runs}: اكتملت مع {current_unplaced_count} مواد ناقصة.")
        
        if current_unplaced_count < best_result['unplaced_count'] or \
           (current_unplaced_count == best_result['unplaced_count'] and len(current_failures) < len(best_result['failures'])):
            best_result['unplaced_count'] = current_unplaced_count
            best_result['schedule'] = copy.deepcopy(current_schedule)
            best_result['failures'] = copy.deepcopy(current_failures)

    return best_result['schedule'], best_result['failures']

# ==============================================================================
# === خوارزميات التحسين والضغط (Refinement & Compaction) ===
# ==============================================================================

def _calculate_end_of_day_penalty(teacher_slots, num_slots):
    """
    تحسب درجة العقوبة بناءً على وجود حصص في الفترات الأخيرة.
    """
    if not teacher_slots or num_slots < 2:
        return 0
    
    last_slot_index = num_slots - 1
    second_last_slot_index = num_slots - 2
    
    penalty = 0
    for _, slot_idx in teacher_slots:
        if slot_idx == last_slot_index:
            penalty += 100  # عقوبة كبيرة للحصة الأخيرة
        elif slot_idx == second_last_slot_index:
            penalty += 1   # عقوبة صغيرة للحصة قبل الأخيرة
    return penalty

# ==============================================================================
# === خوارزميات التحسين والضغط (Refinement & Compaction) ===
# ==============================================================================

def _calculate_end_of_day_penalty(teacher_slots, num_slots):
    """
    تحسب درجة العقوبة بناءً على وجود حصص في الفترات الأخيرة.
    """
    if not teacher_slots or num_slots < 2:
        return 0
    
    last_slot_index = num_slots - 1
    second_last_slot_index = num_slots - 2
    
    penalty = 0
    for _, slot_idx in teacher_slots:
        if slot_idx == last_slot_index:
            penalty += 100  # عقوبة كبيرة للحصة الأخيرة
        elif slot_idx == second_last_slot_index:
            penalty += 1   # عقوبة صغيرة للحصة قبل الأخيرة
    return penalty

# ==============================================================================
# === ✨✨ النسخة النهائية والموصى بها (تجمع كل الإصلاحات) ✨✨ ===
# ==============================================================================

def refine_and_compact_schedule(
    initial_schedule, log_q, selected_teachers,
    all_lectures, days, slots, rooms_data, teachers, all_levels, 
    identifiers_by_level, special_constraints, teacher_constraints, distribution_rule_type,
    lectures_by_teacher_map, globally_unavailable_slots, saturday_teachers, teacher_pairs,
    day_to_idx, rules_grid, last_slot_restrictions, level_specific_large_rooms,
    specific_small_room_assignments, constraint_severities, max_sessions_per_day=None, 
    consecutive_large_hall_rule="none", prefer_morning_slots=False, non_sharing_teacher_pairs=None, 
    refinement_level='balanced'
):
    if non_sharing_teacher_pairs is None:
        non_sharing_teacher_pairs = []

    refined_schedule = copy.deepcopy(initial_schedule)
    refinement_log = []

    base_args = { "days": days, "slots": slots, "teachers": teachers, "rooms_data": rooms_data, "levels": all_levels, "identifiers_by_level": identifiers_by_level, "special_constraints": special_constraints, "teacher_constraints": teacher_constraints, "distribution_rule_type": distribution_rule_type, "lectures_by_teacher_map": lectures_by_teacher_map, "globally_unavailable_slots": globally_unavailable_slots, "saturday_teachers": saturday_teachers, "teacher_pairs": teacher_pairs, "day_to_idx": day_to_idx, "rules_grid": rules_grid, "last_slot_restrictions": last_slot_restrictions, "level_specific_large_rooms": level_specific_large_rooms, "specific_small_room_assignments": specific_small_room_assignments, "constraint_severities": constraint_severities, "max_sessions_per_day": max_sessions_per_day, "consecutive_large_hall_rule": consecutive_large_hall_rule }
    
    cost_args_violations = {**base_args, "prefer_morning_slots": False}
    cost_args_compaction = {**base_args, "prefer_morning_slots": True}

    initial_violations_failures = calculate_schedule_cost(refined_schedule, **cost_args_violations, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
    violation_cost = sum(f.get('penalty', 1) for f in initial_violations_failures)
    
    initial_total_failures = calculate_schedule_cost(refined_schedule, **cost_args_compaction, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
    compaction_cost = sum(f.get('penalty', 1) for f in initial_total_failures) - violation_cost

    moves_made = 0
    log_q.put(f"⏳ بدء التحسين. تكلفة القيود: {violation_cost} | تكلفة الضغط: {compaction_cost}")

    continue_main_loop = True
    max_passes = 30
    current_pass = 0

    while continue_main_loop and current_pass < max_passes:
        current_pass += 1
        continue_main_loop = False
        
        teacher_schedule_map = defaultdict(set)
        room_schedule_map = defaultdict(set)
        for level_grid in refined_schedule.values():
            for d_idx, day in enumerate(level_grid):
                for s_idx, lects in enumerate(day):
                    for l in lects:
                        if l.get('teacher_name'): teacher_schedule_map[l.get('teacher_name')].add((d_idx, s_idx))
                        if l.get('room'): room_schedule_map[l.get('room')].add((d_idx, s_idx))
        
        candidate_lectures = []
        last_slot_index = len(slots) - 1 if slots else -1

        if refinement_level == 'simple':
            for level, day_grid in refined_schedule.items():
                for day_idx, day_slots in enumerate(day_grid):
                    if last_slot_index >= 0:
                        for lecture in day_slots[last_slot_index]:
                            if lecture.get('teacher_name') in selected_teachers:
                                # ✨ استخدام str() لمنع تكرار نفس الحصة في القائمة
                                if not any(str(item['lec'].get('id')) == str(lecture.get('id')) for item in candidate_lectures):
                                    candidate_lectures.append({'lec': lecture, 'level': level, 'original_day': day_idx, 'original_slot': last_slot_index})
        else:
            for level, day_grid in refined_schedule.items():
                for day_idx, day_slots in enumerate(day_grid):
                    for slot_idx, lectures in enumerate(day_slots):
                        if slot_idx > 0:
                            for lecture in lectures:
                                if lecture.get('teacher_name') in selected_teachers:
                                    # ✨ استخدام str()
                                    if not any(str(item['lec'].get('id')) == str(lecture.get('id')) for item in candidate_lectures):
                                        candidate_lectures.append({'lec': lecture, 'level': level, 'original_day': day_idx, 'original_slot': slot_idx})
        
        if not candidate_lectures:
            break

        processed_teachers_deep = set()

        for item in sorted(candidate_lectures, key=lambda x: x['original_slot'], reverse=True):
            lecture = item['lec']
            teacher = lecture.get('teacher_name')
            original_day = item['original_day']
            original_slot = item['original_slot']

            if refinement_level == 'deep':
                if teacher in processed_teachers_deep: continue
                processed_teachers_deep.add(teacher)

                current_teacher_slots = teacher_schedule_map.get(teacher, set())
                teacher_work_days_indices = {d for d, s in current_teacher_slots}
                slots_to_search_deep = [(d, s) for d in teacher_work_days_indices for s in range(len(slots))]
                
                old_penalty = _calculate_end_of_day_penalty(current_teacher_slots, len(slots))

                lectures_for_teacher = lectures_by_teacher_map.get(teacher, [])
                if not lectures_for_teacher: continue
                
                temp_schedule_deep = copy.deepcopy(refined_schedule)
                # ✨ استخدام str() في المعرفات
                teacher_lec_ids = {str(l.get('id')) for l in lectures_for_teacher}
                for lvl_grid in temp_schedule_deep.values():
                    for day_slots in lvl_grid:
                        for slot_lectures in day_slots:
                            slot_lectures[:] = [l for l in slot_lectures if str(l.get('id')) not in teacher_lec_ids]

                temp_teacher_map = defaultdict(set)
                temp_room_map = defaultdict(set)
                for lvl_grid in temp_schedule_deep.values():
                    for d, day in enumerate(lvl_grid):
                        for s, lects in enumerate(day):
                            for l in lects:
                                if l.get('teacher_name'): temp_teacher_map[l.get('teacher_name')].add((d, s))
                                if l.get('room'): temp_room_map[l.get('room')].add((d, s))

                unplaced_in_rebuild = []
                for lec_to_rebuild in lectures_for_teacher:
                    success, _ = find_slot_for_single_lecture(
                        lec_to_rebuild, temp_schedule_deep, temp_teacher_map, temp_room_map,
                        days, slots, rules_grid, rooms_data, teacher_constraints, set(), special_constraints,
                        [], slots_to_search_deep, identifiers_by_level, False, saturday_teachers, day_to_idx,
                        level_specific_large_rooms, specific_small_room_assignments, consecutive_large_hall_rule, prefer_morning_slots=True
                    )
                    if not success: unplaced_in_rebuild.append(lec_to_rebuild)
                
                if unplaced_in_rebuild:
                    continue

                newly_built_teacher_slots = temp_teacher_map.get(teacher, set())
                new_penalty = _calculate_end_of_day_penalty(newly_built_teacher_slots, len(slots))
                
                new_violations_deep = calculate_schedule_cost(temp_schedule_deep, **cost_args_violations, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
                new_violation_cost_deep = sum(f.get('penalty', 1) for f in new_violations_deep)

                if new_penalty < old_penalty and new_violation_cost_deep <= violation_cost:
                    new_total_deep = calculate_schedule_cost(temp_schedule_deep, **cost_args_compaction, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
                    new_compaction_cost_deep = sum(f.get('penalty', 1) for f in new_total_deep) - new_violation_cost_deep
                    
                    log_message_summary = f"إعادة بناء ناجحة لجدول الأستاذ '{teacher}' (عقوبة نهاية اليوم: {old_penalty} -> {new_penalty})"
                    log_message_details = f"✅ تحسين عميق [ضغط: {compaction_cost} -> {new_compaction_cost_deep} | قيود: {violation_cost} -> {new_violation_cost_deep}]: {log_message_summary}"
                    
                    log_q.put(log_message_details)
                    refinement_log.append(f"  - {log_message_summary}")

                    refined_schedule = temp_schedule_deep
                    violation_cost = new_violation_cost_deep
                    compaction_cost = new_compaction_cost_deep
                    moves_made += 1
                    continue_main_loop = True
                    break

            else: 
                teacher_work_days = sorted(list({d for d, s in teacher_schedule_map.get(teacher, set())}))
                for target_day_idx in teacher_work_days:
                    for target_slot_idx in range(original_slot):
                        temp_schedule = copy.deepcopy(refined_schedule)
                        
                        levels_for_this_lecture = lecture.get('levels', [])
                        for level_name in levels_for_this_lecture:
                            if level_name in temp_schedule:
                                # ✨ استخدام str() هنا هو الحل السحري لتأكيد الحذف
                                temp_schedule[level_name][original_day][original_slot] = [l for l in temp_schedule[level_name][original_day][original_slot] if str(l.get('id')) != str(lecture.get('id'))]
                        
                        available_room = _find_valid_and_available_room(lecture, target_day_idx, target_slot_idx, temp_schedule, room_schedule_map, rooms_data, rules_grid, identifiers_by_level, level_specific_large_rooms, specific_small_room_assignments)

                        if not available_room: continue

                        lecture_clone = lecture.copy()
                        lecture_clone['room'] = available_room
                        for level_name in levels_for_this_lecture:
                            if level_name in temp_schedule:
                                temp_schedule[level_name][target_day_idx][target_slot_idx].append(lecture_clone)
                        
                        new_violations_failures = calculate_schedule_cost(temp_schedule, **cost_args_violations, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
                        new_violation_cost = sum(f.get('penalty', 1) for f in new_violations_failures)

                        if new_violation_cost > violation_cost: continue

                        new_total_failures = calculate_schedule_cost(temp_schedule, **cost_args_compaction, non_sharing_teacher_pairs=non_sharing_teacher_pairs)
                        new_compaction_cost = sum(f.get('penalty', 1) for f in new_total_failures) - new_violation_cost
                        
                        accept_move = False
                        if refinement_level == 'simple':
                            if new_violation_cost < violation_cost or (new_violation_cost == violation_cost and new_compaction_cost < compaction_cost):
                                accept_move = True
                        else: # 'balanced'
                            if new_violation_cost <= violation_cost and new_compaction_cost <= compaction_cost:
                                accept_move = True
                        
                        if accept_move:
                            log_message = f"  - نقل '{lecture['name']}' ({teacher}) من {days[original_day]} (الفترة {original_slot + 1}) إلى {days[target_day_idx]} (الفترة {target_slot_idx + 1})"
                            log_message_details = f"✅ تحسين [ضغط: {compaction_cost} -> {new_compaction_cost} | قيود: {violation_cost} -> {new_violation_cost}]: {log_message}"
                            
                            log_q.put(log_message_details)
                            refinement_log.append(log_message)
                            
                            refined_schedule = temp_schedule
                            violation_cost = new_violation_cost
                            compaction_cost = new_compaction_cost
                            moves_made += 1
                            continue_main_loop = True
                            break
                    
                    if continue_main_loop: break
                
                if continue_main_loop: break 

    summary_message = f"🎉 اكتمل التحسين. تكلفة القيود النهائية: {violation_cost}. تكلفة الضغط النهائية: {compaction_cost}. تم نقل {moves_made} محاضرات."
    log_q.put(summary_message)
    refinement_log.insert(0, summary_message)

    return refined_schedule, refinement_log