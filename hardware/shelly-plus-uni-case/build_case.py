"""Корпус Shelly Plus Uni для Blender.

Запуск:
  blender --background --python build_case.py -- "папка_вывода"

Размеры в миллиметрах. 1 единица сцены = 1 мм.
Плата Plus Uni — 40 x 21 x 7 мм. LM2596 — 57 x 20 x 13 мм.
Обе каретки стоят в центре полости, длинной стороной вдоль X,
между ними канал под провода. Плата Shelly плотно вставляется
между стойками, без язычков. На левой и правой стенках жабры: вход снизу,
в полость щель уходит вверх под козырёк, сверху пыль не сыпется.
У входа и выхода кабеля змейка: провод закладывается зигзагом,
рывок держит корпус, а не разъёмы.

Дно толще стенки. На горизонтальную DIN-рейку щитка корпус сажается
отдельной пластиной: четыре винта М3 снизу, длинная сторона вертикально,
паз 5 В сверху, датчик снизу. На пластине жёсткий крючок сверху и язычок снизу.
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
FLOOR = 4.5
# Корень защёлок датчика и LM2596 утоплен в пол, снизу остаётся стенка.
SEAT_ROOT = 1.5
INNER = (124.0, 86.0, 30.0)  # x, y, z полости
ROUND = 3.5

# Плата: длина вдоль X (к клеммам), ширина вдоль Y, толщина текстолита.
PCB = (40.0, 21.0, 1.6)
SEAT = 9.0          # ложемент над полом: язычок длиннее и мягче гнётся
PLATE = 1.4
GAP = 0.35          # щель между краем платы и язычком
BITE = 0.35         # только кромка текстолита, мимо деталей
SHELLY_GAP = 0.90   # запас вокруг платы для старых язычков LM2596-хелперов
SHELLY_FIT = -0.28  # натяг на сторону, ещё плотнее
PINCH = 0.20        # поясок ещё внутрь по толщине текстолита
POST_T = 3.4        # стойка снаружи кромки
POST_ABOVE = 1.1    # чуть выше текстолита, без высокой стенки
LEAD = 0.90         # скос на короткой стенке
PAD_IN = 3.2        # полка под краем платы
LATCH_T = 3.4
LATCH_W = 7.2
COUPON_T = 2.0      # тонкая подложка отдельной посадки
SEAT_PLATE = 2.0    # толщина площадки под стойками, не весь пол корпуса
LATCH_INSET = 1.2   # защёлка в углу, не над компонентами
SHELLY_PAD = 3.0    # полка только под углом платы
HOOK_CLEAR = 0.15   # зазор между верхом платы и полкой защёлки
HOOK_H = 1.55
RAMP_H = 1.20
STOP_T = 1.5
STOP_W = 4.2
END_GAP = 0.40

# Зазор между каретками Shelly и LM2596 — туда уходят провода.
PAIR_GAP = 6.0

# LM2596: длина вдоль X, ширина вдоль Y, высота с обвязкой.
BUCK = (57.0, 20.0, 1.6)
BUCK_H = 13.0
BUCK_SEAT = 8.5
BUCK_PLATE = 1.4
BUCK_GAP = 0.30
BUCK_BITE = 0.65
BUCK_LATCH_T = 2.00
BUCK_LATCH_W = 8.0
BUCK_INSET = 11.0
BUCK_TAB_FRONT = 1.35
BUCK_TAB_BACK = 0.35
BUCK_HOOK_CLEAR = 0.15
BUCK_HOOK_H = 1.00
BUCK_RAMP_H = 1.00
BUCK_END_GAP = 0.50
BUCK_STOP_T = 1.45
BUCK_STOP_W = 3.8

# Пазы сверху стенок, крышка их закрывает.
HALL_SLOT = (8.5, 8.0)  # ширина, глубина от верхнего края
USB_SLOT = (6.5, 6.5)

# Жабры на торцевых стенках. Карман открыт вниз, щель в полость — под крышей.
GILL_COUNT = 4
GILL_INNER_W = 12.0
GILL_WALL = 1.2
GILL_GAP = 2.2
GILL_DEPTH = 4.6
GILL_H = 7.2
GILL_ROOF = 1.2
GILL_SLOT_H = 2.0
GILL_ROWS = (8.2, 16.9)

# Змейка у пазов кабеля. Три ребра, щели по очереди слева и справа.
SNAKE_T = 3.2
SNAKE_PITCH = 8.2
SNAKE_COUNT = 3
SNAKE_GAP = 5.5
SNAKE_SPAN = 16.0
SNAKE_INSET = 4.2
SNAKE_LIP = 1.1

LID_T = 2.8
# Паз шире бортика: 0.4 мм на сторону, чтобы крышка входила после печати.
RIM_DROP = 1.05
LIP_FENCE = 2.2       # от наружной грани до паза
GROOVE_W = 2.6
GROOVE_D = 2.8
LIP_BANK = 1.5        # внутренняя стенка паза
LID_SKIRT = 1.6
LID_PLAY = 0.50
LID_SKIRT_H = 2.1
BOSS_D = 8.0
BOSS_HOLE = 2.7
LID_HOLE = 3.4
MOUNT_HOLE = 4.5

# Отдельная пластина на горизонтальную DIN-рейку щитка (TH35×7.5).
# Рейка вдоль Y. В щите X — вертикаль: больший X сверху.
# Пластина прижимается к дну снаружи, рейка ложится на её внешнюю грань.
BRACKET_T = 5.5
SCREW_D = 2.7         # глухое отверстие в дне под саморез М3
SCREW_CLEAR = 3.4     # сквозное отверстие в пластине
SCREW_DEPTH = 3.2     # не прорезает пол: остаётся 1.3 мм
DIN_W = 35.0
DIN_LIP = 1.0
DIN_EDGE = 0.55       # спинка паза снаружи от кромки, с запасом на допуск рейки
DIN_TOOTH = 1.85      # носик заходит под кромку
DIN_SEAT = 1.70       # полка под кромкой: кромка 1 мм, запас 0.7 мм
MOUTH = 2.90         # скос ниже полки, по нему кромка заходит в паз
MOUTH_OPEN = 1.20     # низ скоса шире рейки, снаружи от кромки
CLIP_LEN = 29.0
CLIP_Z0 = -14.0       # короткое плечо: не торчит далеко от пластины
HOOK_Z0 = -8.5        # жёсткий крючок короче язычка
CLIP_IN = 0.7         # заход в толщу пластины, чтобы булево слило тела
HOOK_BACK = 6.2
TOWER_W = 5.0
TOWER_INSET = 0.50    # башни не на торце и не в теле язычка
SPRING_T = 2.6
SPRING_W = 16.0
BAR_H = 4.0           # перемычка у корня язычка
BAR_EXTRA = 2.2       # утолщение перемычки снаружи
BACKSTOP_GAP = 2.8    # ход язычка больше захода носика
BACKSTOP_T = 3.4


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


def profile_solid_y(name, y0, y1, xz):
    """Тело выдавливанием профиля (x, z) вдоль Y. Нормали наружу."""
    mesh = bpy.data.meshes.new(name)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new()
    v0 = [bm.verts.new((x, y0, z)) for x, z in xz]
    v1 = [bm.verts.new((x, y1, z)) for x, z in xz]
    bm.verts.ensure_lookup_table()
    n = len(xz)
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


def _cavity_center():
    return WALL + INNER[0] / 2, WALL + INNER[1] / 2


def _shelly_over():
    """Выступ каретки Shelly за край платы по Y."""
    return SHELLY_FIT + POST_T + 1.6


def _shelly_end_over():
    """Выступ каретки за короткий край напротив шлейфа."""
    return SHELLY_FIT + POST_T + 1.2


def _buck_front_over():
    return BUCK_GAP + BUCK_LATCH_T + BUCK_TAB_FRONT + 0.40


def _buck_back_over():
    return BUCK_GAP + BUCK_LATCH_T + BUCK_TAB_BACK


def shelly_seat():
    """Левый нижний угол платы. Каретка — передняя половина пары в центре."""
    cx, cy = _cavity_center()
    shelly_span = PCB[1] + 2 * _shelly_over()
    buck_span = BUCK[1] + _buck_front_over() + _buck_back_over()
    y_south = cy - (shelly_span + PAIR_GAP + buck_span) / 2
    py = y_south + _shelly_over()
    px = cx - PCB[0] / 2
    return px, py, FLOOR + SEAT


def _latch_ys(edge_y, side):
    """side = -1: защёлка с меньшего Y. Носик смотрит на плату."""
    y_in = edge_y + side * SHELLY_GAP
    y_out = y_in + side * LATCH_T
    y_nose = edge_y - side * BITE
    y_tip = edge_y + side * 0.20
    return y_in, y_out, y_nose, y_tip


def _rooted_latch(y_in, y_out, y_nose, y_tip, side, tab, z_hook0, z_hook1, z_top, z_tab):
    """Язычок с широкой пяткой внутри пола. Выше пола толщина прежняя, он гнётся."""
    z_neck = FLOOR + 0.4
    y_in_foot = y_in - side * 1.6
    y_out_foot = y_out + side * 1.1
    return [
        (y_in_foot, SEAT_ROOT),
        (y_in, z_neck),
        (y_in, z_hook0),
        (y_nose, z_hook0),
        (y_nose, z_hook1),
        (y_tip, z_top),
        (y_out + side * tab, z_top),
        (y_out + side * min(0.45, tab * 0.55), z_tab),
        (y_out, z_tab),
        (y_out, z_neck),
        (y_out_foot, SEAT_ROOT),
    ]


def build_latch(name, x0, edge_y, side, width=None):
    """Язычок: полка ловит край платы, сверху скос, снаружи упор для ногтя."""
    if width is None:
        width = LATCH_W
    y_in, y_out, y_nose, y_tip = _latch_ys(edge_y, side)
    z_hook0 = FLOOR + SEAT + PCB[2] + HOOK_CLEAR
    z_hook1 = z_hook0 + HOOK_H
    z_top = z_hook1 + RAMP_H
    z_tab = z_top - 2.0
    return profile_solid(
        name,
        x0,
        x0 + width,
        _rooted_latch(y_in, y_out, y_nose, y_tip, side, 2.6, z_hook0, z_hook1, z_top, z_tab),
    )


def _shelly_legs(px, py):
    """Две пары стоек симметрично на длинных краях, плюс упор напротив шлейфа."""
    y1 = py + PCB[1]
    width = LATCH_W
    wire = px + 16.0 - width
    header = px + PCB[0] - 7.0 - width
    return (
        {"axis": "y", "x": wire, "w": width, "edge": py, "side": -1},
        {"axis": "y", "x": header, "w": width, "edge": py, "side": -1},
        {"axis": "y", "x": wire, "w": width, "edge": y1, "side": 1},
        {"axis": "y", "x": header, "w": width, "edge": y1, "side": 1},
        {"axis": "x", "y": py + 1.5, "w": 10.0, "edge": px + PCB[0], "side": 1},
    )


def _post_profile(inner, pinch, outer, pad, lead, z_pcb, z_fr4, z_top):
    """Полка, натяг по кромке, поясок на толщине FR4, короткий скос сверху."""
    return [
        (pad, SEAT_ROOT),
        (pad, z_pcb),
        (inner, z_pcb),
        (pinch, z_pcb + 0.25),
        (pinch, z_fr4),
        (lead, z_top),
        (outer, z_top),
        (outer, SEAT_ROOT),
    ]


def _post_faces(edge, side, pad_in):
    inner = edge + side * SHELLY_FIT
    pinch = inner - side * PINCH
    outer = inner + side * POST_T
    pad = edge - side * pad_in
    lead = inner + side * LEAD
    z_pcb = FLOOR + SEAT
    z_fr4 = z_pcb + PCB[2]
    z_top = z_fr4 + POST_ABOVE
    return inner, pinch, outer, pad, lead, z_pcb, z_fr4, z_top


def _shelly_edge_post(name, x0, width, edge_y, side):
    """Стойка на длинном крае: натяг по кромке, без язычка сверху."""
    return profile_solid(
        name,
        x0,
        x0 + width,
        _post_profile(*_post_faces(edge_y, side, PAD_IN)),
    )


def _shelly_end_post(name, y0, width, edge_x, side):
    """Стойка на коротком крае напротив шлейфа."""
    return profile_solid_y(
        name,
        y0,
        y0 + width,
        _post_profile(*_post_faces(edge_x, side, 1.2)),
    )


def make_shelly_carriage(px, py):
    """Каретка: пять стоек, плата вставляется плотно сверху."""
    x1 = px + PCB[0]
    y1 = py + PCB[1]
    z_plate = SEAT_ROOT + SEAT_PLATE
    over = _shelly_over()
    end = _shelly_end_over()

    plate = box(
        "carriage_plate",
        px - 1.2,
        x1 + end,
        py - over,
        y1 + over,
        SEAT_ROOT,
        z_plate,
    )
    parts = [plate]

    for index, leg in enumerate(_shelly_legs(px, py)):
        if leg["axis"] == "y":
            parts.append(
                _shelly_edge_post(f"post_{index}", leg["x"], leg["w"], leg["edge"], leg["side"])
            )
        else:
            parts.append(
                _shelly_end_post(f"post_{index}", leg["y"], leg["w"], leg["edge"], leg["side"])
            )

    for part in parts[1:]:
        boolean(plate, part, "UNION")
    plate.name = "Shelly_Carriage"
    return plate


def add_shelly_carriage(body):
    px, py, _pz = shelly_seat()
    boolean(body, make_shelly_carriage(px, py), "UNION")
    return body


def build_shelly_coupon():
    """Только маленькая посадка Shelly. Большую плиту под всё дно не делаем."""
    ox, _oy, _oz = outer_size()
    over = _shelly_over()
    pad_x = 1.2
    pad_x_end = _shelly_end_over()
    px = pad_x
    py = over
    x0 = 0.0
    x1 = pad_x + PCB[0] + pad_x_end
    y0 = 0.0
    y1 = over + PCB[1] + over
    slab = box("Shelly_Seat_Test", x0, x1, y0, y1, 0.0, COUPON_T)
    boolean(slab, make_shelly_carriage(px, py), "UNION")
    slab.location.x = ox + 20
    activate(slab)
    with bpy.context.temp_override(active_object=slab, object=slab, selected_objects=[slab]):
        bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    slab.name = "Shelly_Seat_Test"
    return slab


def build_shelly_marker():
    """Макет платы по фото: провода с минус X, гребёнка с плюс X, конденсатор на плюс Y."""
    px, py, pz = shelly_seat()
    x1 = px + PCB[0]
    y1 = py + PCB[1]
    lift = 0.04
    board = box("Shelly_PCB", px, x1, py, y1, pz + lift, pz + PCB[2] + lift)
    pieces = [
        box("shelly_header", x1 - 7.0, x1 - 1.2, py + 1.2, y1 - 1.2, pz + PCB[2] + lift, pz + 7.2),
        box("shelly_cap", px + 16.0, px + 22.0, y1 - 6.5, y1 - 0.6, pz + PCB[2] + lift, pz + 7.0),
        box("shelly_conn", px + 22.4, px + 29.0, y1 - 5.5, y1 - 0.8, pz + PCB[2] + lift, pz + 6.2),
        box("shelly_chip", px + 14.0, px + 24.0, py + 6.0, py + 14.0, pz + PCB[2] + lift, pz + 3.2),
    ]
    for piece in pieces:
        boolean(board, piece, "UNION")
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
    """Левый нижний угол платы LM2596. Стоит позади Shelly, оба по центру."""
    cx, _cy = _cavity_center()
    _px, py, _pz = shelly_seat()
    shelly_north = py + PCB[1] + _shelly_over()
    y0 = shelly_north + PAIR_GAP + _buck_front_over()
    x0 = cx - BUCK[0] / 2
    return x0, y0, FLOOR + BUCK_SEAT


def buck_front_plastic():
    _x, y0, _z = buck_seat()
    return y0 - (BUCK_GAP + BUCK_LATCH_T + BUCK_TAB_FRONT)


def _buck_ys(edge_y, side):
    y_in = edge_y + side * BUCK_GAP
    y_out = y_in + side * BUCK_LATCH_T
    y_nose = edge_y - side * BUCK_BITE
    y_tip = edge_y + side * 0.18
    return y_in, y_out, y_nose, y_tip


def build_buck_latch(name, x0, edge_y, side, tab):
    """Язычок по длинному краю LM2596. Носик на текстолит, пятка внутри пола."""
    y_in, y_out, y_nose, y_tip = _buck_ys(edge_y, side)
    z_hook0 = FLOOR + BUCK_SEAT + BUCK[2] + BUCK_HOOK_CLEAR
    z_hook1 = z_hook0 + BUCK_HOOK_H
    z_top = z_hook1 + BUCK_RAMP_H
    z_tab = z_top - 1.55
    return profile_solid(
        name,
        x0,
        x0 + BUCK_LATCH_W,
        _rooted_latch(y_in, y_out, y_nose, y_tip, side, tab, z_hook0, z_hook1, z_top, z_tab),
    )


def add_buck_cradle(body):
    """Каретка позади Shelly. Плата вдавливается сверху, торцы открыты под провода."""
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
        SEAT_ROOT,
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
                parts.append(box("buck_skirt", s0, s1, y_a, y_b, SEAT_ROOT, z_pcb))

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
                SEAT_ROOT,
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


def din_rail_xs():
    """Кромки горизонтальной планки. Меньший X — низ корпуса в щите."""
    ox, _oy, _oz = outer_size()
    center = ox / 2
    return center - DIN_W / 2, center + DIN_W / 2


def din_clip_ys(length):
    """Две защёлки вдоль горизонтальной планки."""
    gap = (length - 2 * CLIP_LEN) / 3
    return (gap, 2 * gap + CLIP_LEN)


def bracket_screw_xy():
    """Четыре винта по углам пластины, мимо крючков и рейки."""
    ox, oy, _oz = outer_size()
    return (
        (36.0, 12.0),
        (36.0, oy - 12.0),
        (ox - 36.0, 12.0),
        (ox - 36.0, oy - 12.0),
    )


def _on_bracket(z):
    """Z от лица рейки переводит на внешнюю грань пластины."""
    return z - BRACKET_T


def _seat_z():
    """Полка, которая держит кромку. Кромка занимает z от 0 до -DIN_LIP."""
    return -DIN_SEAT


def _mouth_z():
    return _seat_z() - MOUTH


def _fixed_profile(rail_top):
    """Жёсткий крючок: паз над полкой и скос, по которому кромка в него входит."""
    x_wall = rail_top + DIN_EDGE
    x_outer = x_wall + HOOK_BACK
    x_tip = rail_top - DIN_TOOTH
    x_open = rail_top + MOUTH_OPEN
    z_seat = _on_bracket(_seat_z())
    z_mouth = _on_bracket(_mouth_z())
    return [
        (x_outer, _on_bracket(CLIP_IN)),
        (x_wall, _on_bracket(CLIP_IN)),
        (x_wall, z_seat),
        (x_tip, z_seat),
        (x_open, z_mouth),
        (x_wall, z_mouth),
        (x_wall, _on_bracket(HOOK_Z0)),
        (x_outer, _on_bracket(HOOK_Z0)),
    ]


def _spring_profile(rail_bottom):
    """Язычок. Верх — только носик, в дно он не врастает и может отойти наружу."""
    x_wall = rail_bottom - DIN_EDGE
    x_outer = x_wall - SPRING_T
    x_tip = rail_bottom + DIN_TOOTH
    x_open = rail_bottom - MOUTH_OPEN
    z_seat = _on_bracket(_seat_z())
    z_mouth = _on_bracket(_mouth_z())
    z_root = _on_bracket(CLIP_Z0 + 1.25)
    return [
        (x_outer, z_seat),
        (x_wall, z_seat),
        (x_tip, z_seat),
        (x_open, z_mouth),
        (x_wall, z_mouth),
        (x_wall, z_root),
        (x_outer, z_root),
    ]


def _din_fixed_hook(y0, rail_top):
    """Жёсткий крючок сверху: им корпус цепляют за верхнюю кромку планки."""
    return profile_solid_y(
        "din_fixed",
        y0,
        y0 + CLIP_LEN,
        _fixed_profile(rail_top),
    )


def _din_spring(y0, rail_bottom):
    """Язычок снизу. Носик не приварен к дну, гнётся от нижней перемычки."""
    x_wall = rail_bottom - DIN_EDGE
    x_outer = x_wall - SPRING_T
    finger = profile_solid_y(
        "din_finger",
        y0 + (CLIP_LEN - SPRING_W) / 2,
        y0 + (CLIP_LEN + SPRING_W) / 2,
        _spring_profile(rail_bottom),
    )
    bar = box(
        "din_bar",
        x_outer - BAR_EXTRA,
        x_wall + 0.15,
        y0,
        y0 + CLIP_LEN,
        _on_bracket(CLIP_Z0),
        _on_bracket(CLIP_Z0 + BAR_H),
    )
    boolean(bar, finger, "UNION")
    # Башни в зазоре между торцом планки и язычком, иначе булево оставляет шов.
    inset = TOWER_INSET
    for side in (inset, CLIP_LEN - TOWER_W - inset):
        tower = box(
            "din_tower",
            x_outer,
            x_wall,
            y0 + side,
            y0 + side + TOWER_W,
            _on_bracket(CLIP_Z0 + 0.5),
            _on_bracket(CLIP_IN),
        )
        boolean(bar, tower, "UNION")
    return bar


def _din_backstop(y0, rail_bottom):
    x1 = rail_bottom - DIN_EDGE - SPRING_T - BACKSTOP_GAP
    return box(
        "din_stop",
        x1 - BACKSTOP_T,
        x1,
        y0,
        y0 + CLIP_LEN,
        _on_bracket(CLIP_Z0),
        _on_bracket(CLIP_IN),
    )


def bracket_plate_bounds():
    """Пластина накрывает крючки и четыре винта, не выходя за дно."""
    ox, oy, _oz = outer_size()
    xs = [p[0] for p in bracket_screw_xy()]
    ys = [p[1] for p in bracket_screw_xy()]
    rail_bottom, rail_top = din_rail_xs()
    spring_out = rail_bottom - DIN_EDGE - SPRING_T - BACKSTOP_GAP - BACKSTOP_T
    fixed_out = rail_top + DIN_EDGE + HOOK_BACK
    clip_ys = din_clip_ys(oy)
    x0 = min(min(xs) - 7.0, spring_out - 1.6)
    x1 = max(max(xs) + 7.0, fixed_out + 1.6)
    y0 = min(min(ys) - 6.0, min(clip_ys) - 2.0)
    y1 = max(max(ys) + 6.0, max(clip_ys) + CLIP_LEN + 2.0)
    if x0 < 1 or y0 < 1 or x1 > ox - 1 or y1 > oy - 1:
        raise RuntimeError("пластина DIN не помещается на дно")
    return x0, x1, y0, y1


def build_bracket():
    """Отдельная деталь: пластина с защёлками. Прижимается к дну снаружи."""
    x0, x1, y0, y1 = bracket_plate_bounds()
    plate = box("bracket_plate", x0, x1, y0, y1, -BRACKET_T, 0.0)
    _ox, oy, _oz = outer_size()
    rail_bottom, rail_top = din_rail_xs()
    for cy in din_clip_ys(oy):
        boolean(plate, _din_fixed_hook(cy, rail_top), "UNION")
        boolean(plate, _din_spring(cy, rail_bottom), "UNION")
        boolean(plate, _din_backstop(cy, rail_bottom), "UNION")
    for x, y in bracket_screw_xy():
        hole = cyl("bracket_hole", (x, y), -BRACKET_T - 0.4, SCREW_CLEAR, BRACKET_T + 0.8)
        boolean(plate, hole, "DIFFERENCE")
    plate.name = "DIN_Bracket"
    return plate


def add_bracket_seats(body):
    """Глухие отверстия под саморезы пластины. В полость не выходят."""
    for x, y in bracket_screw_xy():
        hole = cyl("bracket_screw", (x, y), -0.3, SCREW_D, SCREW_DEPTH + 0.3)
        boolean(body, hole, "DIFFERENCE")
    return body


def build_din_marker():
    """Макет горизонтальной планки. В STL не входит."""
    _ox, oy, _oz = outer_size()
    rail_bottom, rail_top = din_rail_xs()
    lip = DIN_LIP
    flange = 4.6
    face = -BRACKET_T
    z_in = face - (7.5 - lip)
    xz = [
        (rail_bottom, face - 0.04),
        (rail_top, face - 0.04),
        (rail_top, face - lip),
        (rail_top - flange, face - lip),
        (rail_top - flange, z_in),
        (rail_bottom + flange, z_in),
        (rail_bottom + flange, face - lip),
        (rail_bottom, face - lip),
    ]
    rail = profile_solid_y("DIN_rail", -18.0, oy + 18.0, xz)
    rail.name = "DIN_TH35"
    return to_reference(rail)


def gill_origins(length):
    pocket = GILL_INNER_W + 2 * GILL_WALL
    span = GILL_COUNT * pocket + (GILL_COUNT - 1) * GILL_GAP
    y0 = (length - span) / 2
    pitch = pocket + GILL_GAP
    return tuple(y0 + i * pitch for i in range(GILL_COUNT))


def _add_gill(body, outer_x, inward, y0, z0):
    """Карман снаружи стенки. inward = +1, если полость в сторону +X.

    Козырёк и губа — один профиль. Щёки чуть выступают, чтобы не совпасть
    с его торцом: иначе boolean оставляет дыру.
    """
    z1 = z0 + GILL_H
    x_cheek = outer_x - inward * GILL_DEPTH
    x_lip = outer_x - inward * (GILL_DEPTH - 0.35)
    x_lip_in = x_lip + inward * GILL_WALL
    x_near = outer_x + inward * 0.6
    z_lip = z0 + 0.25
    z_roof = z1 - GILL_ROOF
    y_a = y0 + GILL_WALL
    y_b = y_a + GILL_INNER_W
    hood = profile_solid_y(
        "gill_hood",
        y_a - 0.45,
        y_b + 0.45,
        [
            (x_near, z1 - 0.2),
            (x_lip, z1 - 0.2),
            (x_lip, z_lip),
            (x_lip_in, z_lip),
            (x_lip_in, z_roof),
            (x_near, z_roof),
        ],
    )
    for y_side in (y0, y_b):
        boolean(
            hood,
            box("gill_cheek", x_cheek, x_near, y_side, y_side + GILL_WALL, z0, z1),
            "UNION",
        )
    boolean(body, hood, "UNION")
    boolean(
        body,
        box(
            "gill_slot",
            outer_x - inward * 1.2,
            outer_x + inward * (WALL + 0.7),
            y_a,
            y_b,
            z_roof - 0.25 - GILL_SLOT_H,
            z_roof - 0.25,
        ),
        "DIFFERENCE",
    )
    return body


def snake_top():
    """Верх рёбер в плоскости закрытой крышки: провод через них не перекинуть."""
    _ox, _oy, oz = outer_size()
    return oz - RIM_DROP


def snake_fingers():
    """Рёбра змейки: (x0, y0, длина по Y) у левого и правого ввода."""
    ox, oy, _oz = outer_size()
    cy = oy / 2
    length = SNAKE_SPAN - SNAKE_GAP
    fingers = []
    for side in (-1, 1):
        wall = WALL if side < 0 else ox - WALL
        for index in range(SNAKE_COUNT):
            along = SNAKE_INSET + index * SNAKE_PITCH
            x0 = wall + along if side < 0 else wall - along - SNAKE_T
            if index % 2 == 0:
                y0 = cy - SNAKE_SPAN / 2
            else:
                y0 = cy + SNAKE_SPAN / 2 - length
            fingers.append((x0, y0, length))
    return tuple(fingers)


def add_strain_relief(body):
    """Змейка у пазов. Провод закладывается сверху, щели чередуются."""
    for x0, y0, finger_len in snake_fingers():
        fin = box("snake_fin", x0, x0 + SNAKE_T, y0, y0 + finger_len, SEAT_ROOT, snake_top())
        boolean(body, fin, "UNION")
        gap_on_plus = y0 + finger_len / 2 < outer_size()[1] / 2
        if gap_on_plus:
            lip_y0, lip_y1 = y0 + finger_len - 0.3, y0 + finger_len + SNAKE_LIP
        else:
            lip_y0, lip_y1 = y0 - SNAKE_LIP, y0 + 0.3
        lip = box(
            "snake_lip",
            x0 - 0.2,
            x0 + SNAKE_T + 0.2,
            lip_y0,
            lip_y1,
            snake_top() - 1.6,
            snake_top(),
        )
        boolean(body, lip, "UNION")
    return body


def add_gills(body):
    """Жабры слева и справа. Воздух заходит снизу и поднимается в щель."""
    ox, oy, _oz = outer_size()
    for y0 in gill_origins(oy):
        for z0 in GILL_ROWS:
            _add_gill(body, 0.0, +1, y0, z0)
            _add_gill(body, ox, -1, y0, z0)
    return body


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
            boss = cyl("boss", (x, y), FLOOR, BOSS_D, INNER[2] - RIM_DROP - 0.2)
            boolean(body, boss, "UNION")
            hole = cyl("boss_hole", (x, y), oz - 10, BOSS_HOLE, 12)
            boolean(body, hole, "DIFFERENCE")

    add_shelly_carriage(body)
    add_buck_cradle(body)

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

    add_strain_relief(body)
    add_bracket_seats(body)
    add_gills(body)
    add_lid_groove(body)

    body.name = "Case_Base"
    return body


def add_lid_groove(body):
    """Внутренний борт с пазом. Скругление стенки его не съедает."""
    ox, oy, oz = outer_size()
    z_rim = oz - RIM_DROP
    shave = cube(
        "rim_shave",
        (-0.4, -0.4, z_rim),
        (ox + 0.8, oy + 0.8, RIM_DROP + 2),
    )
    boolean(body, shave, "DIFFERENCE")

    reach = LIP_FENCE + GROOVE_W + LIP_BANK
    z0 = z_rim - GROOVE_D - 0.8
    # Борт выше обода, потом срез. Иначе верх совпадает с уже готовой гранью и рвётся.
    bands = (
        (WALL - 0.7, reach, WALL - 0.7, oy - WALL + 0.7),
        (ox - reach, ox - WALL + 0.7, WALL - 0.7, oy - WALL + 0.7),
        (WALL - 0.7, ox - WALL + 0.7, WALL - 0.7, reach),
        (WALL - 0.7, ox - WALL + 0.7, oy - reach, oy - WALL + 0.7),
    )
    for xa, xb, ya, yb in bands:
        boolean(body, box("lid_bank", xa, xb, ya, yb, z0, z_rim + 0.5), "UNION")
    boolean(
        body,
        cube("rim_shave2", (-0.4, -0.4, z_rim), (ox + 0.8, oy + 0.8, 2)),
        "DIFFERENCE",
    )

    z_cut = z_rim - GROOVE_D
    slots = (
        (LIP_FENCE, LIP_FENCE + GROOVE_W, LIP_FENCE, oy - LIP_FENCE),
        (ox - LIP_FENCE - GROOVE_W, ox - LIP_FENCE, LIP_FENCE, oy - LIP_FENCE),
        (LIP_FENCE, ox - LIP_FENCE, LIP_FENCE, LIP_FENCE + GROOVE_W),
        (LIP_FENCE, ox - LIP_FENCE, oy - LIP_FENCE - GROOVE_W, oy - LIP_FENCE),
    )
    for xa, xb, ya, yb in slots:
        boolean(body, box("lid_slot", xa, xb, ya, yb, z_cut, z_rim + 2), "DIFFERENCE")

    # Паз не должен закрыть выходы кабеля.
    hall_y = oy / 2 - HALL_SLOT[0] / 2
    boolean(
        body,
        box("hall_reopen", -1, reach + 1.5, hall_y, hall_y + HALL_SLOT[0], oz - HALL_SLOT[1], oz + 2),
        "DIFFERENCE",
    )
    usb_y = oy / 2 - USB_SLOT[0] / 2
    boolean(
        body,
        box("usb_reopen", ox - reach - 1.5, ox + 1, usb_y, usb_y + USB_SLOT[0], oz - USB_SLOT[1], oz + 2),
        "DIFFERENCE",
    )
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


def add_lid_skirt(lid, y_shift):
    """Бортик снизу крышки входит в паз. Над выходами кабеля бортик вырезан."""
    ox, oy, _oz = outer_size()
    x0 = LIP_FENCE + LID_PLAY
    x1 = ox - LIP_FENCE - LID_PLAY
    y0 = y_shift + LIP_FENCE + LID_PLAY
    y1 = y_shift + oy - LIP_FENCE - LID_PLAY
    z0 = -LID_SKIRT_H
    z1 = 0.7
    bars = (
        (x0, x0 + LID_SKIRT, y0, y1),
        (x1 - LID_SKIRT, x1, y0, y1),
        (x0, x1, y0, y0 + LID_SKIRT),
        (x0, x1, y1 - LID_SKIRT, y1),
    )
    for xa, xb, ya, yb in bars:
        boolean(lid, box("lid_skirt", xa, xb, ya, yb, z0, z1), "UNION")
    notches = (
        (x0 - 0.4, x0 + LID_SKIRT + 0.4, HALL_SLOT[0] + 3.5),
        (x1 - LID_SKIRT - 0.4, x1 + 0.4, USB_SLOT[0] + 3.5),
    )
    for xa, xb, width in notches:
        yc = y_shift + oy / 2
        boolean(
            lid,
            box("lid_notch", xa, xb, yc - width / 2, yc + width / 2, z0 - 0.3, z1),
            "DIFFERENCE",
        )
    return lid


def build_lid(base_height_offset):
    ox, oy, _oz = outer_size()
    # Крышка лежит рядом с основанием, чтобы оба объекта были видны.
    y_shift = oy + 16
    lid = cube("Case_Lid", (0, y_shift, 0), (ox, oy, LID_T))
    bevel(lid, 1.1)
    add_lid_skirt(lid, y_shift)

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
    """Каретки в центре полости и не задевают друг друга."""
    bx, by, bz = buck_seat()
    sx, sy, _sz = shelly_seat()
    front = buck_front_plastic() - 0.40
    back = by + BUCK[1] + _buck_back_over()
    shelly_north = sy + PCB[1] + _shelly_over()
    shelly_south = sy - _shelly_over()
    cavity_x0 = WALL
    cavity_x1 = WALL + INNER[0]
    cavity_y1 = WALL + INNER[1]
    cavity_z1 = FLOOR + INNER[2]

    if not (cavity_x0 + 4 < bx and bx + BUCK[0] < cavity_x1 - 4):
        raise RuntimeError("LM2596 не помещается по X")
    if not (cavity_x0 + 4 < sx and sx + PCB[0] < cavity_x1 - 4):
        raise RuntimeError("Shelly не помещается по X")
    if not (WALL + 4 < shelly_south and back < cavity_y1 - 2):
        raise RuntimeError("каретки не помещаются по Y")
    if bz + BUCK_H > cavity_z1 - 6:
        raise RuntimeError("LM2596 упирается в крышку")
    if front < shelly_north + 4:
        raise RuntimeError("каретка LM2596 пересекает каретку Shelly")
    ox, oy, _oz = outer_size()
    rail_bottom, rail_top = din_rail_xs()
    spring_out = rail_bottom - DIN_EDGE - SPRING_T - BACKSTOP_GAP - BACKSTOP_T
    fixed_out = rail_top + DIN_EDGE + HOOK_BACK
    if spring_out < 1 or fixed_out > ox - 1:
        raise RuntimeError("защёлка DIN вылезает за габарит дна")
    for y0 in din_clip_ys(oy):
        if y0 < 4 or y0 + CLIP_LEN > oy - 4:
            raise RuntimeError("защёлка DIN вылезает за торец дна")
    if SCREW_DEPTH > FLOOR - 1.0:
        raise RuntimeError("винт пластины прорезает дно")
    if GROOVE_W + 0.05 < LID_SKIRT + 2 * LID_PLAY:
        raise RuntimeError("бортик крышки не входит в паз")
    if GROOVE_D - LID_SKIRT_H < 0.4:
        raise RuntimeError("бортик крышки упирается в дно паза")
    if LIP_FENCE + GROOVE_W + LIP_BANK > WALL + 9 - BOSS_D / 2 - 1.2:
        raise RuntimeError("паз крышки задевает босс")
    _ox, oy, oz = outer_size()
    gill_top = max(GILL_ROWS) + GILL_H
    if gill_top > oz - RIM_DROP - GROOVE_D - 1.0:
        raise RuntimeError("жабры врезаются в паз крышки")
    if min(GILL_ROWS) < FLOOR + 2:
        raise RuntimeError("жабры врезаются в дно")
    if abs(snake_top() - (oz - RIM_DROP)) > 0.05:
        raise RuntimeError("змейка не доходит до крышки")
    if snake_top() > oz - RIM_DROP + 0.05:
        raise RuntimeError("змейка не даёт крышке сесть")
    buck_x0 = bx - BUCK_END_GAP - BUCK_STOP_T - 0.5
    buck_x1 = bx + BUCK[0] + BUCK_END_GAP + BUCK_STOP_T + 0.5
    for x0, _y0, _length in snake_fingers():
        x1 = x0 + SNAKE_T
        if x1 > buck_x0 and x0 < buck_x1:
            raise RuntimeError("змейка пересекает каретку")
        if x0 < 4.5 or x1 > ox - 4.5:
            raise RuntimeError("змейка пересекает щель жабры")
    if max(gill_origins(oy)) + 2 * GILL_WALL + GILL_INNER_W > oy - 4:
        raise RuntimeError("жабры вылезают за стенку")
    px0, px1, py0, py1 = bracket_plate_bounds()
    for x, y in bracket_screw_xy():
        if not (px0 + 3 < x < px1 - 3 and py0 + 3 < y < py1 - 3):
            raise RuntimeError("винт пластины вышел за её край")
        if spring_out - 1 < x < fixed_out + 1 and min(din_clip_ys(oy)) - 1 < y < max(din_clip_ys(oy)) + CLIP_LEN + 1:
            raise RuntimeError("винт попадает в защёлку")
    # Кромка 1 мм должна входить в паз и оставаться за носиком.
    if not (DIN_LIP + 0.35 < DIN_SEAT < DIN_LIP + 1.1):
        raise RuntimeError("паз DIN не держит кромку")
    if DIN_TOOTH < 1.5:
        raise RuntimeError("носик DIN слишком короткий")
    if MOUTH < DIN_EDGE + DIN_TOOTH:
        raise RuntimeError("скос DIN круче 45° и не напечатается")
    if BACKSTOP_GAP < DIN_TOOTH + 0.4:
        raise RuntimeError("язычку DIN некуда отогнуться")
    free = _seat_z() - (CLIP_Z0 + BAR_H)
    if free < 7.5:
        raise RuntimeError("язычок DIN слишком короткий и жёсткий")
    if HOOK_Z0 > _mouth_z() - 2.5:
        raise RuntimeError("крючок DIN короче паза")
    margin = (CLIP_LEN - SPRING_W) / 2
    if TOWER_W + 2 * TOWER_INSET > margin - 0.3:
        raise RuntimeError("башни DIN пересекают язычок")


def main():
    folder = out_dir()
    os.makedirs(folder, exist_ok=True)
    scene_mm()
    wipe()

    check_layout()

    base = build_base()
    lid = build_lid(0)
    bracket = build_bracket()
    coupon = build_shelly_coupon()
    marker = build_shelly_marker()
    buck = build_buck_marker()
    rail = build_din_marker()
    base.data.materials.append(plastic("PETG_base", (0.75, 0.78, 0.80, 1)))
    lid.data.materials.append(plastic("PETG_lid", (0.82, 0.84, 0.86, 1)))
    bracket.data.materials.append(plastic("PETG_bracket", (0.55, 0.62, 0.58, 1)))
    coupon.data.materials.append(plastic("PETG_coupon", (0.72, 0.74, 0.70, 1)))
    marker.data.materials.append(plastic("FR4", (0.07, 0.22, 0.12, 1)))
    buck.data.materials.append(plastic("LM2596_blue", (0.08, 0.25, 0.62, 1)))
    rail.data.materials.append(plastic("DIN_zinc", (0.62, 0.64, 0.66, 1)))

    for obj in (base, lid, bracket, coupon, marker, buck, rail):
        for poly in obj.data.polygons:
            poly.use_smooth = False

    px, py, pz = shelly_seat()
    bx, by, bz = buck_seat()
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
        "DIN",
        f"x {din_rail_xs()[0]:.2f}..{din_rail_xs()[1]:.2f}",
        f"floor {FLOOR:.1f}",
        "clips",
        " ".join(f"{y:.1f}" for y in din_clip_ys(outer_size()[1])),
    )
    print("BOUNDARY", boundary_edges(base), boundary_edges(lid), boundary_edges(bracket), boundary_edges(coupon))

    frame_camera((base, lid, bracket, coupon, marker, buck, rail))

    blend_path = os.path.join(folder, "shelly_plus_uni_case.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    export_stl(os.path.join(folder, "case_base.stl"), base)
    export_stl(os.path.join(folder, "case_lid.stl"), lid)
    export_stl(os.path.join(folder, "din_bracket.stl"), bracket)
    export_stl(os.path.join(folder, "shelly_seat_test.stl"), coupon)
    print("SAVED", blend_path)


if __name__ == "__main__":
    main()
