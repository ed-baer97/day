"""Корпус Shelly Plus Uni для Blender.

Запуск:
  blender --background --python build_case.py -- "папка_вывода"

Размеры в миллиметрах. 1 единица сцены = 1 мм.
Плата Plus Uni — 40 x 21 x 7 мм (сайт Shelly, PCB). Каретка справа:
плата вдавливается сверху, четыре язычка щёлкают за длинные края.
Короткие торцы открыты — оттуда выходят провода к клеммам.

LM2596 — 57 x 20 x 13 мм, у задней стенки. С Shelly приходит 12 В,
модуль отдаёт 5 В на клеммы датчика. Садится сверху, язычки держат
длинные края платы. Левый торец — выход, правый — вход.
"""

import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector


def out_dir():
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1]
    return os.path.dirname(os.path.abspath(__file__))


# --- размеры, мм ---
WALL = 2.8
FLOOR = 2.6
INNER = (124.0, 86.0, 30.0)  # x, y, z полости
ROUND = 3.5

# Плата: длина вдоль X (к клеммам), ширина вдоль Y, толщина текстолита.
PCB = (40.0, 21.0, 1.6)
SEAT = 9.0          # ложемент над полом: язычок длиннее и мягче гнётся
PLATE = 1.4
GAP = 0.35          # щель между краем платы и язычком
BITE = 0.70         # носик заходит на текстолит
LATCH_T = 1.2
LATCH_W = 5.0
LATCH_INSET = 8.0   # от короткого торца до язычка, там паяные провода
HOOK_CLEAR = 0.15   # зазор между верхом платы и полкой защёлки
HOOK_H = 0.80
RAMP_H = 1.05
STOP_T = 1.5
STOP_W = 4.2
END_GAP = 0.40

RAIL_T = 1.6

# Три клеммы: сигнал, 5 В, земля. Смещены к передней стенке,
# чтобы сзади встала каретка LM2596.
TERM = (20.0, 14.0)
FENCE_H = 4.0

# LM2596: длина вдоль X, ширина вдоль Y, высота с обвязкой.
BUCK = (57.0, 20.0, 1.6)
BUCK_H = 13.0
BUCK_SEAT = 8.5
BUCK_PLATE = 1.4
BUCK_GAP = 0.30
BUCK_BITE = 0.65
BUCK_LATCH_T = 1.10
BUCK_LATCH_W = 6.2
BUCK_INSET = 11.0
BUCK_TAB_FRONT = 1.35
BUCK_TAB_BACK = 0.85
BUCK_HOOK_CLEAR = 0.15
BUCK_HOOK_H = 0.75
BUCK_RAMP_H = 1.00
BUCK_END_GAP = 0.50
BUCK_STOP_T = 1.45
BUCK_STOP_W = 3.8
BUCK_WALL_GAP = 0.55
# Зазор между верхом клемм и передним язычком каретки.
BUCK_TERM_CLEAR = 4.6

# Пазы сверху стенок, крышка их закрывает.
HALL_SLOT = (8.5, 8.0)  # ширина, глубина от верхнего края
USB_SLOT = (6.5, 6.5)

LID_T = 2.8
BOSS_D = 8.0
BOSS_HOLE = 2.7
LID_HOLE = 3.4
MOUNT_HOLE = 4.5


def scene_mm():
    unit = bpy.context.scene.unit_settings
    unit.system = "METRIC"
    unit.scale_length = 0.001
    unit.length_unit = "MILLIMETERS"


def wipe():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.curves):
        for data in list(block):
            if data.users == 0:
                block.remove(data)


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def apply_scale(obj):
    activate(obj)
    with bpy.context.temp_override(active_object=obj, object=obj, selected_objects=[obj]):
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)


def cube(name, corner, size):
    """Куб по нижнему ближнему левому углу и габариту (x, y, z)."""
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = size
    apply_scale(obj)
    obj.location = (
        corner[0] + size[0] / 2,
        corner[1] + size[1] / 2,
        corner[2] + size[2] / 2,
    )
    return obj


def cyl(name, center_xy, z0, diameter, height, segments=48):
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=segments,
        radius=diameter / 2,
        depth=height,
        location=(center_xy[0], center_xy[1], z0 + height / 2),
    )
    obj = bpy.context.active_object
    obj.name = name
    return obj


def boolean(target, tool, operation):
    activate(target)
    mod = target.modifiers.new(name="bool", type="BOOLEAN")
    mod.operation = operation
    mod.solver = "EXACT"
    mod.object = tool
    with bpy.context.temp_override(
        active_object=target, object=target, selected_objects=[target]
    ):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(tool, do_unlink=True)
    return target


def bevel(obj, width, segments=3):
    activate(obj)
    mod = obj.modifiers.new(name="bevel", type="BEVEL")
    mod.width = width
    mod.segments = segments
    mod.affect = "EDGES"
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(50)
    with bpy.context.temp_override(active_object=obj, object=obj, selected_objects=[obj]):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    return obj


def outer_size():
    return (INNER[0] + 2 * WALL, INNER[1] + 2 * WALL, INNER[2] + FLOOR)


def box(name, x0, x1, y0, y1, z0, z1):
    xa, xb = (x0, x1) if x0 <= x1 else (x1, x0)
    ya, yb = (y0, y1) if y0 <= y1 else (y1, y0)
    za, zb = (z0, z1) if z0 <= z1 else (z1, z0)
    if min(xb - xa, yb - ya, zb - za) < 0.05:
        raise RuntimeError(f"пустой объём {name}")
    return cube(name, (xa, ya, za), (xb - xa, yb - ya, zb - za))


def profile_solid(name, x0, x1, yz):
    """Тело выдавливанием профиля (y, z) вдоль X. Нормали наружу."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new()
    v0 = [bm.verts.new((x0, y, z)) for y, z in yz]
    v1 = [bm.verts.new((x1, y, z)) for y, z in yz]
    bm.verts.ensure_lookup_table()
    n = len(yz)
    bm.faces.new(v0)
    bm.faces.new(list(reversed(v1)))
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((v0[i], v0[j], v1[j], v1[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return obj


def shelly_seat():
    """Левый нижний угол платы. Провода смотрят влево, на клеммы."""
    px = WALL + INNER[0] - 16.0 - PCB[0]
    py = WALL + (INNER[1] - PCB[1]) / 2
    pz = FLOOR + SEAT
    return px, py, pz


def _latch_ys(edge_y, side):
    """side = -1: защёлка с меньшего Y. Носик смотрит на плату."""
    y_in = edge_y + side * GAP
    y_out = y_in + side * LATCH_T
    y_nose = edge_y - side * BITE
    y_tip = edge_y + side * 0.20
    return y_in, y_out, y_nose, y_tip


def build_latch(name, x0, edge_y, side):
    """Язычок: полка ловит край платы, сверху скос, снаружи упор для ногтя."""
    y_in, y_out, y_nose, y_tip = _latch_ys(edge_y, side)
    z0 = FLOOR - 0.45
    z_hook0 = FLOOR + SEAT + PCB[2] + HOOK_CLEAR
    z_hook1 = z_hook0 + HOOK_H
    z_top = z_hook1 + RAMP_H
    z_tab = z_top - 2.0
    yz = [
        (y_in, z0),
        (y_in, z_hook0),
        (y_nose, z_hook0),
        (y_nose, z_hook1),
        (y_tip, z_top),
        (y_out + side * 2.0, z_top),
        (y_out + side * 0.45, z_tab),
        (y_out, z_tab),
        (y_out, z0),
    ]
    return profile_solid(name, x0, x0 + LATCH_W, yz)


def add_shelly_carriage(body):
    px, py, _pz = shelly_seat()
    x1 = px + PCB[0]
    y1 = py + PCB[1]
    z_plate = FLOOR + PLATE
    z_pcb_top = FLOOR + SEAT + PCB[2]

    plate = box(
        "carriage_plate",
        px - END_GAP - STOP_T,
        x1 + END_GAP + STOP_T,
        py - GAP - LATCH_T - 2.3,
        y1 + GAP + LATCH_T + 2.3,
        FLOOR - 0.45,
        z_plate,
    )
    parts = [plate]

    for y0 in (py + 0.9, y1 - 0.9 - 2.6):
        parts.append(box("seat_rib", px + 1.0, x1 - 1.0, y0, y0 + 2.6, z_plate - 0.25, FLOOR + SEAT))

    latch_x = (px + LATCH_INSET, x1 - LATCH_INSET - LATCH_W)
    windows = []
    for index, x0 in enumerate(latch_x):
        windows.append((x0 - 0.85, x0 + LATCH_W + 0.85))
        parts.append(build_latch(f"latch_s{index}", x0, py, -1))
        parts.append(build_latch(f"latch_n{index}", x0, y1, +1))

    def skirts(y_a, y_b):
        spans = [(px - END_GAP - STOP_T, x1 + END_GAP + STOP_T)]
        for a, b in windows:
            nxt = []
            for s0, s1 in spans:
                if b <= s0 or a >= s1:
                    nxt.append((s0, s1))
                    continue
                if s0 < a:
                    nxt.append((s0, a))
                if b < s1:
                    nxt.append((b, s1))
            spans = nxt
        for s0, s1 in spans:
            if s1 - s0 > 0.4:
                parts.append(box("skirt", s0, s1, y_a, y_b, z_plate - 0.25, FLOOR + SEAT))

    y_in_s, y_out_s, _, _ = _latch_ys(py, -1)
    y_in_n, y_out_n, _, _ = _latch_ys(y1, +1)
    skirts(y_out_s, y_in_s)
    skirts(y_in_n, y_out_n)

    for x0, y_edge, side in (
        (px - END_GAP - STOP_T, py, -1),
        (px - END_GAP - STOP_T, y1, +1),
        (x1 + END_GAP, py, -1),
        (x1 + END_GAP, y1, +1),
    ):
        _, y_out, _, _ = _latch_ys(y_edge, side)
        y_far = y_edge - side * STOP_W
        parts.append(
            box("end_stop", x0, x0 + STOP_T, y_out, y_far, z_plate - 0.25, z_pcb_top + 0.45)
        )

    for part in parts[1:]:
        boolean(plate, part, "UNION")
    plate.name = "Shelly_Carriage"
    boolean(body, plate, "UNION")
    return body


def build_shelly_marker():
    """Макет платы в коллекции Reference. В STL корпуса не входит."""
    px, py, pz = shelly_seat()
    lift = 0.04
    board = box("Shelly_PCB", px, px + PCB[0], py, py + PCB[1], pz + lift, pz + PCB[2] + lift)
    parts = box(
        "Shelly_parts",
        px + 1.4,
        px + PCB[0] - 1.4,
        py + 1.6,
        py + PCB[1] - 1.6,
        pz + PCB[2] + lift,
        pz + 7.0 + lift,
    )
    boolean(board, parts, "UNION")
    board.name = "Shelly_Plus_Uni"
    return to_reference(board)


def build_buck_marker():
    """Макет LM2596. В STL корпуса не входит."""
    x0, y0, z0 = buck_seat()
    lift = 0.04
    board = box(
        "LM2596_PCB",
        x0,
        x0 + BUCK[0],
        y0,
        y0 + BUCK[1],
        z0 + lift,
        z0 + BUCK[2] + lift,
    )
    parts = box(
        "LM2596_parts",
        x0 + 4.0,
        x0 + BUCK[0] - 4.0,
        y0 + 2.6,
        y0 + BUCK[1] - 2.6,
        z0 + BUCK[2] + lift,
        z0 + BUCK_H + lift,
    )
    boolean(board, parts, "UNION")
    board.name = "LM2596"
    return to_reference(board)


def buck_seat():
    """Левый нижний угол платы LM2596. Выход смотрит влево, на клеммы."""
    rear = BUCK_GAP + BUCK_LATCH_T + BUCK_TAB_BACK
    y1 = WALL + INNER[1] - BUCK_WALL_GAP - rear
    y0 = y1 - BUCK[1]
    x0 = WALL + 25.0
    return x0, y0, FLOOR + BUCK_SEAT


def buck_front_plastic():
    _x, y0, _z = buck_seat()
    return y0 - (BUCK_GAP + BUCK_LATCH_T + BUCK_TAB_FRONT)


def terminal_origin():
    """Левый нижний угол блока клемм. Сзади остаётся каретка преобразователя."""
    span = 3 * TERM[1] + 2 * 3.0
    tx = WALL + 18.0
    ty = buck_front_plastic() - BUCK_TERM_CLEAR - span
    return tx, ty, span


def _buck_ys(edge_y, side):
    y_in = edge_y + side * BUCK_GAP
    y_out = y_in + side * BUCK_LATCH_T
    y_nose = edge_y - side * BUCK_BITE
    y_tip = edge_y + side * 0.18
    return y_in, y_out, y_nose, y_tip


def build_buck_latch(name, x0, edge_y, side, tab):
    """Язычок по длинному краю LM2596. Носик на текстолит, сверху скос."""
    y_in, y_out, y_nose, y_tip = _buck_ys(edge_y, side)
    z0 = FLOOR - 0.40
    z_hook0 = FLOOR + BUCK_SEAT + BUCK[2] + BUCK_HOOK_CLEAR
    z_hook1 = z_hook0 + BUCK_HOOK_H
    z_top = z_hook1 + BUCK_RAMP_H
    z_tab = z_top - 1.55
    yz = [
        (y_in, z0),
        (y_in, z_hook0),
        (y_nose, z_hook0),
        (y_nose, z_hook1),
        (y_tip, z_top),
        (y_out + side * tab, z_top),
        (y_out + side * 0.32, z_tab),
        (y_out, z_tab),
        (y_out, z0),
    ]
    return profile_solid(name, x0, x0 + BUCK_LATCH_W, yz)


def add_buck_cradle(body):
    """Каретка у задней стенки. Плата вдавливается сверху, торцы открыты под провода."""
    x0, y0, _pz = buck_seat()
    x1 = x0 + BUCK[0]
    y1 = y0 + BUCK[1]
    z_plate = FLOOR + BUCK_PLATE
    z_pcb = FLOOR + BUCK_SEAT
    z_pcb_top = z_pcb + BUCK[2]
    front = buck_front_plastic()
    back = y1 + (BUCK_GAP + BUCK_LATCH_T + BUCK_TAB_BACK)

    # Полка чуть шире язычков и упоров, иначе торец совпадает с ними
    # и boolean оставляет щель.
    plate = box(
        "buck_plate",
        x0 - BUCK_END_GAP - BUCK_STOP_T - 0.45,
        x1 + BUCK_END_GAP + BUCK_STOP_T + 0.45,
        front - 0.40,
        back,
        FLOOR - 0.40,
        z_plate,
    )
    parts = [plate]

    for rib_y in (y0 + 2.4, y1 - 2.4 - 2.2):
        parts.append(
            box("buck_rib", x0 + 9.0, x1 - 9.0, rib_y, rib_y + 2.2, z_plate - 0.2, z_pcb)
        )

    latch_x = (x0 + BUCK_INSET, x1 - BUCK_INSET - BUCK_LATCH_W)
    windows = []
    for index, lx in enumerate(latch_x):
        windows.append((lx - 0.75, lx + BUCK_LATCH_W + 0.75))
        parts.append(build_buck_latch(f"buck_front_{index}", lx, y0, -1, BUCK_TAB_FRONT))
        parts.append(build_buck_latch(f"buck_back_{index}", lx, y1, +1, BUCK_TAB_BACK))

    def skirts(y_a, y_b):
        spans = [(x0 - BUCK_END_GAP - BUCK_STOP_T, x1 + BUCK_END_GAP + BUCK_STOP_T)]
        for a, b in windows:
            nxt = []
            for s0, s1 in spans:
                if b <= s0 or a >= s1:
                    nxt.append((s0, s1))
                    continue
                if s0 < a:
                    nxt.append((s0, a))
                if b < s1:
                    nxt.append((b, s1))
            spans = nxt
        for s0, s1 in spans:
            if s1 - s0 > 0.4:
                parts.append(box("buck_skirt", s0, s1, y_a, y_b, z_plate - 0.2, z_pcb))

    y_in_f, y_out_f, _, _ = _buck_ys(y0, -1)
    y_in_b, y_out_b, _, _ = _buck_ys(y1, +1)
    skirts(y_out_f, y_in_f)
    skirts(y_in_b, y_out_b)

    for sx, y_edge, side in (
        (x0 - BUCK_END_GAP - BUCK_STOP_T, y0, -1),
        (x0 - BUCK_END_GAP - BUCK_STOP_T, y1, +1),
        (x1 + BUCK_END_GAP, y0, -1),
        (x1 + BUCK_END_GAP, y1, +1),
    ):
        _, y_out, _, _ = _buck_ys(y_edge, side)
        y_far = y_edge - side * BUCK_STOP_W
        parts.append(
            box(
                "buck_stop",
                sx,
                sx + BUCK_STOP_T,
                y_out,
                y_far,
                z_plate - 0.2,
                z_pcb_top + 0.40,
            )
        )

    for part in parts[1:]:
        boolean(plate, part, "UNION")
    plate.name = "Buck_Cradle"
    boolean(body, plate, "UNION")
    return body


def to_reference(obj):
    col = bpy.data.collections.get("Reference")
    if col is None:
        col = bpy.data.collections.new("Reference")
        bpy.context.scene.collection.children.link(col)
    for owner in list(obj.users_collection):
        owner.objects.unlink(obj)
    col.objects.link(obj)
    return obj


def build_base():
    ox, oy, oz = outer_size()
    body = cube("Case_Base", (0, 0, 0), (ox, oy, oz))
    bevel(body, ROUND)

    cavity = cube(
        "cavity",
        (WALL, WALL, FLOOR),
        (INNER[0], INNER[1], INNER[2] + 2),
    )
    boolean(body, cavity, "DIFFERENCE")

    # Ушки крепления к стене. Заход 0.6 мм в пол, иначе булево
    # оставляет их отдельным телом.
    for hx in (-8.0, ox + 8.0):
        x0 = -16.0 if hx < 0 else ox - 0.6
        flange = cube("flange", (x0, oy / 2 - 12, 0), (16.6, 24, FLOOR))
        hole = cyl("mount", (hx, oy / 2), -1, MOUNT_HOLE, FLOOR + 2)
        boolean(flange, hole, "DIFFERENCE")
        boolean(body, flange, "UNION")

    # Боссы под саморезы M3. Отверстие глухое, пол не прорезается.
    margin = 9
    for x in (WALL + margin, ox - WALL - margin):
        for y in (WALL + margin, oy - WALL - margin):
            boss = cyl("boss", (x, y), FLOOR, BOSS_D, INNER[2])
            boolean(body, boss, "UNION")
            hole = cyl("boss_hole", (x, y), oz - 10, BOSS_HOLE, 12)
            boolean(body, hole, "DIFFERENCE")

    add_shelly_carriage(body)
    add_buck_cradle(body)

    # Три гнезда клемм слева, открыты вправо — к Shelly.
    # Блок прижат к передней стенке: над ним выход 5 В с LM2596.
    tx, ty, _span = terminal_origin()
    for i in range(3):
        y0 = ty + i * (TERM[1] + 3)
        fences = [
            (tx, y0, FLOOR - 0.35, TERM[0], RAIL_T, FENCE_H + 0.35),
            (tx, y0 + TERM[1] - RAIL_T, FLOOR - 0.35, TERM[0], RAIL_T, FENCE_H + 0.35),
            (tx, y0, FLOOR - 0.35, RAIL_T, TERM[1], FENCE_H + 0.35),
        ]
        for j, spec in enumerate(fences):
            fence = cube(f"term_{i}_{j}", spec[:3], spec[3:])
            boolean(body, fence, "UNION")

    # Паз кабеля датчика — левая стенка.
    hall = cube(
        "hall_slot",
        (-1, oy / 2 - HALL_SLOT[0] / 2, oz - HALL_SLOT[1]),
        (WALL + 2, HALL_SLOT[0], HALL_SLOT[1] + 2),
    )
    boolean(body, hall, "DIFFERENCE")

    # Паз кабеля 5 В — правая стенка.
    usb = cube(
        "usb_slot",
        (ox - WALL - 1, oy / 2 - USB_SLOT[0] / 2, oz - USB_SLOT[1]),
        (WALL + 2, USB_SLOT[0], USB_SLOT[1] + 2),
    )
    boolean(body, usb, "DIFFERENCE")

    body.name = "Case_Base"
    return body


def add_text(name, words, size, location):
    bpy.ops.object.text_add(location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.body = words
    obj.data.size = size
    obj.data.extrude = 0.6
    obj.data.align_x = "CENTER"
    obj.data.align_y = "CENTER"
    font_path = r"C:\Windows\Fonts\arial.ttf"
    if os.path.exists(font_path):
        obj.data.font = bpy.data.fonts.load(font_path)
    activate(obj)
    with bpy.context.temp_override(active_object=obj, object=obj, selected_objects=[obj]):
        bpy.ops.object.convert(target="MESH")
    return obj


def build_lid(base_height_offset):
    ox, oy, _oz = outer_size()
    # Крышка лежит рядом с основанием, чтобы оба объекта были видны.
    y_shift = oy + 16
    lid = cube("Case_Lid", (0, y_shift, 0), (ox, oy, LID_T))
    bevel(lid, ROUND)

    margin = 9
    for x in (WALL + margin, ox - WALL - margin):
        for y in (WALL + margin + y_shift, oy - WALL - margin + y_shift):
            hole = cyl("lid_hole", (x, y), -1, LID_HOLE, LID_T + 2)
            boolean(lid, hole, "DIFFERENCE")

    hall = add_text("label_hall", "HALL", 6, (22, y_shift + oy / 2, LID_T))
    volts = add_text("label_5v", "5V", 6, (ox - 22, y_shift + oy / 2, LID_T))
    boolean(lid, hall, "UNION")
    boolean(lid, volts, "UNION")
    lid.name = "Case_Lid"
    return lid


def plastic(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF")
    if principled:
        principled.inputs["Base Color"].default_value = color
        principled.inputs["Roughness"].default_value = 0.45
    return mat


def frame_camera(objects):
    cam = bpy.data.objects.get("Camera")
    if cam is None:
        bpy.ops.object.camera_add()
        cam = bpy.context.active_object
    points = []
    for obj in objects:
        for corner in obj.bound_box:
            points.append(obj.matrix_world @ Vector(corner))
    center = sum(points, Vector()) / len(points)
    cam.location = center + Vector((180, -220, 140))
    cam.rotation_euler = (math.radians(62), 0, math.radians(38))
    bpy.context.scene.camera = cam


def export_stl(filepath, obj):
    activate(obj)
    try:
        bpy.ops.wm.stl_export(filepath=filepath, export_selected_objects=True)
    except Exception:
        bpy.ops.export_mesh.stl(filepath=filepath, use_selection=True)


def boundary_edges(obj):
    mesh = bmesh.new()
    mesh.from_mesh(obj.data)
    count = sum(1 for edge in mesh.edges if edge.is_boundary)
    mesh.free()
    return count


def check_layout():
    """Каретка, клеммы и Shelly не наезжают друг на друга и остаются в полости."""
    bx, by, bz = buck_seat()
    sx, sy, _sz = shelly_seat()
    tx, ty, span = terminal_origin()
    front = buck_front_plastic()
    back = by + BUCK[1] + BUCK_GAP + BUCK_LATCH_T + BUCK_TAB_BACK
    shelly_top = sy + PCB[1] + GAP + LATCH_T + 2.3
    cavity_x1 = WALL + INNER[0]
    cavity_y1 = WALL + INNER[1]
    cavity_z1 = FLOOR + INNER[2]

    if not (WALL + 4 < bx and bx + BUCK[0] < cavity_x1 - 4):
        raise RuntimeError("LM2596 не помещается по X")
    if not (WALL + 4 < by and back < cavity_y1 - 0.2):
        raise RuntimeError("LM2596 не помещается по Y")
    if bz + BUCK_H > cavity_z1 - 6:
        raise RuntimeError("LM2596 упирается в крышку")
    if front < shelly_top + 2.0:
        raise RuntimeError("каретка LM2596 пересекает каретку Shelly")
    if ty < WALL + 4 or ty + span > front - (BUCK_TERM_CLEAR - 0.05):
        raise RuntimeError("клеммы пересекают стенку или LM2596")
    if not (bx < tx + TERM[0] and bx + BUCK[0] > sx):
        raise RuntimeError("торцы LM2596 не смотрят на клеммы и Shelly")


def main():
    folder = out_dir()
    os.makedirs(folder, exist_ok=True)
    scene_mm()
    wipe()

    check_layout()

    base = build_base()
    lid = build_lid(0)
    marker = build_shelly_marker()
    buck = build_buck_marker()
    base.data.materials.append(plastic("PETG_base", (0.75, 0.78, 0.80, 1)))
    lid.data.materials.append(plastic("PETG_lid", (0.82, 0.84, 0.86, 1)))
    marker.data.materials.append(plastic("FR4", (0.07, 0.22, 0.12, 1)))
    buck.data.materials.append(plastic("LM2596_blue", (0.08, 0.25, 0.62, 1)))

    for obj in (base, lid, marker, buck):
        for poly in obj.data.polygons:
            poly.use_smooth = False

    px, py, pz = shelly_seat()
    bx, by, bz = buck_seat()
    tx, ty, span = terminal_origin()
    print(
        "SEAT",
        f"x {px:.2f}..{px + PCB[0]:.2f}",
        f"y {py:.2f}..{py + PCB[1]:.2f}",
        f"z {pz:.2f}..{pz + PCB[2]:.2f}",
    )
    print(
        "BUCK",
        f"x {bx:.2f}..{bx + BUCK[0]:.2f}",
        f"y {by:.2f}..{by + BUCK[1]:.2f}",
        f"z {bz:.2f}..{bz + BUCK_H:.2f}",
        f"top_clear {FLOOR + INNER[2] - (bz + BUCK_H):.2f}",
    )
    print(
        "TERMS",
        f"x {tx:.2f}..{tx + TERM[0]:.2f}",
        f"y {ty:.2f}..{ty + span:.2f}",
    )
    print("BOUNDARY", boundary_edges(base), boundary_edges(lid))

    frame_camera((base, lid, marker, buck))

    blend_path = os.path.join(folder, "shelly_plus_uni_case.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    export_stl(os.path.join(folder, "case_base.stl"), base)
    export_stl(os.path.join(folder, "case_lid.stl"), lid)
    print("SAVED", blend_path)


if __name__ == "__main__":
    main()
