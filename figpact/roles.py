"""G12-A 角色注册表：角色语义的唯一权威来源。

契约发现（``figpact.init_contract``）、比较器/统一（``figpact.plate``）、Apply
（经由 plate 调用 ``figpact.final_size``）、QA/GUI/Agent 只引用这里，
不得各自解释角色含义。

核心语义（冻结）：

- ``axis.title`` = 历史语义 = **坐标轴标签**（``xlabel``/``ylabel``），
  **不是** :meth:`Axes.set_title` 的产物（``Axes.title``）。
  ``Axes.title`` 另立保留角色 ``axes.title``（只读，不可统一）。
- 旧契约里的 artist 家族名（``xlabel``/``ylabel``/``title``/``ticklabels``/
  ``curve``）经 :func:`resolve_legacy` 兼容解析：``xlabel``/``ylabel`` 回到
  ``axis.title`` 无歧义；``title`` 配给 ``axis.title`` 是**错配，拒绝**。
"""
from __future__ import annotations

import matplotlib.axes
import matplotlib.collections
import matplotlib.figure
import matplotlib.legend
import matplotlib.lines
import matplotlib.patches
import matplotlib.text

REGISTRY_SCHEMA = 'figpact.role-registry/1'


class RoleBindingError(ValueError):
    """错误的 role -> Artist 配对（拒绝，不猜）。"""


#: 角色注册表正文：每个角色至少 role_id / artist_kinds / properties /
#: measurement / capability / aliases（G12-A 逐条写明）。
ROLE_REGISTRY: dict[str, dict] = {
    'axis.title': {
        'role_id': 'axis.title',
        'definition': '坐标轴标签：x 轴名（xlabel）与 y 轴名（ylabel）文本；'
                      '不是 Axes.set_title 的标题（那是 axes.title）。',
        'artist_kinds': ('xlabel', 'ylabel'),
        'artist_classes': (matplotlib.text.Text,),
        'identity': 'artist is ax.xaxis.label or ax.yaxis.label（.axes 为 None，不靠归属猜）',
        'properties': ('fontsize',),
        'measurement': "control-glyph 'Ag' per nominal size, same-figure draw；"
                       'effective_pt = nominal_pt x measured k（均匀缩放文本精确成立）',
        'capability': {'measure': True, 'edit': True, 'verify': True},
        'unify': True,
        'unify_note': '可在统一最终宽度下跨图统一（目标即 nominal pt，k 由画布保证≈1）。',
        'params': ('axis_font_pt',),
        'geometry_family': ('xlabel_envelope', 'ylabel_envelope'),
        'aliases': ('axis.label', 'axis.label.x', 'axis.label.y'),
        'reserved': False,
    },
    'axis.tick': {
        'role_id': 'axis.tick',
        'definition': '刻度数字：坐标轴主/次刻度标签文本（含 label1/label2）。',
        'artist_kinds': ('ticklabels',),
        'artist_classes': (matplotlib.text.Text,),
        'identity': 'artist 在某根轴的 major/minor tick label 集合里',
        'properties': ('fontsize',),
        'measurement': "control-glyph 'Ag' per nominal size, same-figure draw；"
                       'effective_pt = nominal_pt x measured k',
        'capability': {'measure': True, 'edit': True, 'verify': True},
        'unify': True,
        'unify_note': '可在统一最终宽度下跨图统一；无 EDITABLE 绑定时只比较（E✗），不得硬写。',
        'params': ('tick_font_pt',),
        'geometry_family': ('xtick_', 'ytick_'),
        'aliases': (),
        'reserved': False,
    },
    'curve.linewidth': {
        'role_id': 'curve.linewidth',
        'definition': '数据曲线描边宽度：Line2D 折线（科学内容本身受指纹保护，只许改观感）。',
        'artist_kinds': ('curve',),
        'artist_classes': (matplotlib.lines.Line2D,),
        'identity': 'isinstance Line2D（集合 Collection 不是曲线，拒绝）',
        'properties': ('linewidth',),
        'measurement': 'artist linewidth x measured k（点线宽，不做字形估计）',
        'capability': {'measure': True, 'edit': True, 'verify': True},
        'unify': True,
        'unify_note': '可在统一最终宽度下跨图统一；只影响观感，不参与布局。',
        'params': ('line_width',),
        'geometry_family': ('polyline',),
        'aliases': (),
        'reserved': False,
    },
    'panel.label': {
        'role_id': 'panel.label',
        'definition': '面板标签（a/b/c 这类面板字母）：只有**面板字母文本**可以绑定——'
                      '契约显式以 role: panel.label 声明，或文本本身为字母且位于轴外/角位置。'
                      '**峰/官能团等标注字体（peak_font_pt、label_font_pt）不属于本角色**，'
                      '标注是 annotation，不是面板标签；无法判定则 unresolved。',
        'artist_kinds': ('text',),
        'artist_classes': (matplotlib.text.Text,),
        'identity': '面板字母 Text（显式声明 role 或字母+轴外/角位置）；'
                    '标注文本与无判据的任意 Text 不得归属（unresolved）',
        'properties': ('fontsize',),
        'measurement': "control-glyph 'Ag' per nominal size, same-figure draw；"
                       'effective_pt = nominal_pt x measured k',
        'capability': {'measure': True, 'edit': False, 'verify': True},
        'unify': False,
        'unify_note': '只比较不强制统一：密度逐图不同，强制统一会破坏布局。',
        'params': (),
        'declaration_required': True,
        'geometry_family': ('text_envelope',),
        'aliases': ('peak.label',),
        'reserved': False,
    },
    'legend': {
        'role_id': 'legend',
        'definition': '图例：Legend 容器与其行文本（字号与列数/锚点联动，不自动缩谱线）。',
        'artist_kinds': ('legend', 'legend_text'),
        'artist_classes': (matplotlib.legend.Legend, matplotlib.text.Text),
        'identity': 'Legend 本体或 legend.get_texts() 的行文本',
        'properties': ('fontsize',),
        'measurement': "control-glyph 'Ag' per nominal size, same-figure draw；"
                       'effective_pt = nominal_pt x measured k（Legend 本体无 get_fontsize，'
                       '以其行文本 nominal 计）',
        'capability': {'measure': True, 'edit': False, 'verify': True},
        'unify': False,
        'unify_note': '只比较不强制统一：密度逐图不同，强制统一会破坏布局。',
        'params': ('legend_font_pt',),
        'declaration_required': False,
        'geometry_family': ('legend',),
        'aliases': ('legend.label', 'legend.title'),
        'reserved': False,
    },
    'scalebar': {
        'role_id': 'scalebar',
        'definition': '比例尺（仅显微图；携带标定，改动即破坏定量含义）。',
        'artist_kinds': (),
        'artist_classes': (),
        'identity': '本仓库 plot 图无此角色；compare 只报告（C✗），永不写回',
        'properties': (),
        'measurement': '未测量：无源码绑定、无固定 pt 上下文，compare 只报告',
        'capability': {'measure': False, 'edit': False, 'verify': False},
        'unify': False,
        'unify_note': '受保护：显微图标定，plot 图恒为 n/a；SVG/PNG 无源码入口。',
        'params': (),
        'geometry_family': (),
        'aliases': (),
        'reserved': False,
    },
    'axes.title': {
        'role_id': 'axes.title',
        'definition': 'Axes 标题：ax.set_title / ax.title / loc 标题文本。'
                      '保留角色：只读解释旧绑定，不得编辑、不得统一。',
        'artist_kinds': ('title',),
        'artist_classes': (matplotlib.text.Text,),
        'identity': 'artist is ax.title / ax._left_title / ax._right_title',
        'properties': ('fontsize',),
        'measurement': '同文本测量口径；仅用于把错配点名，不参与统一',
        'capability': {'measure': True, 'edit': False, 'verify': False},
        'unify': False,
        'unify_note': '保留角色：旧契约把 set_title 记成 axis.title 是错配，'
                      '本次不迁移契约文件，但新验证一律拒绝该配对。',
        'params': (),
        'geometry_family': ('title_envelope',),
        'aliases': (),
        'reserved': True,
    },
}

#: 固定比较表行序（= 旧 COMPARE_ROLES / DENOMINATOR_ROLES，不增不减）。
COMPARE_ROLES = ('axis.title', 'axis.tick', 'curve.linewidth',
                 'panel.label', 'legend', 'scalebar')

#: 角色 -> YAML 源码参数（空 = 受保护，无旋钮）。
ROLE_TO_PARAMS: dict[str, tuple] = {
    'axis.title': ('axis_font_pt',),
    'axis.tick': ('tick_font_pt',),
    'curve.linewidth': ('line_width',),
    # 面板字母没有对应参数族：标注字体不属于本角色（见 roles.ROLES['panel.label']）。
    'panel.label': (),
    'legend': ('legend_font_pt',),
    'scalebar': (),
}

#: 可扰动验证的单参数 -> 角色（v0.3：**撤出** peak_font_pt / label_font_pt——
#: 它们控制的是标注（annotation），不是面板标签；错误配对必须被拒绝）。
VERIFIABLE_PARAM_ROLE = {
    'axis_font_pt': 'axis.title',
    'tick_font_pt': 'axis.tick',
    'line_width': 'curve.linewidth',
    'legend_font_pt': 'legend',
}
#: YAML 里属于角色但发现入口覆盖不到的键 -> 角色（系统化 unresolved，不猜）。
#: v0.2 起三键皆有合法调用族，此表恒空（保留空表：语义仍在，不得删键重建系统）。
ROLE_PARAM_FALLBACK = {
}

#: 样式扰动可接受的几何家族：角色 -> drawn_shapes kind 关键字。
#: legend 家族 'legend' 覆盖 legend_envelope（Legend 框）与 legend_handle
#: 装饰线键；panel.label 家族 'text_envelope' 覆盖面板文本包络（通用机制，
#: 不给具体 Artist 写分支：匹配只看 drawn_shapes kind 关键字）。
GEOMETRY_FAMILY = {
    'axis.title': ('xlabel_envelope', 'ylabel_envelope'),
    'axis.tick': ('xtick_', 'ytick_'),
    'curve.linewidth': ('polyline',),
    'panel.label': ('text_envelope',),
    'legend': ('legend', 'legend_handle'),
}

def registry_snapshot() -> dict:
    """JSON-safe 注册表快照（回执用）：类对象只留类名，不留 type 本身。"""
    out = {}
    for rid, entry in ROLE_REGISTRY.items():
        snap = dict(entry)
        snap['artist_classes'] = [c.__name__ for c in (entry.get('artist_classes') or ())]
        snap['properties'] = list(entry.get('properties') or ())
        snap['artist_kinds'] = list(entry.get('artist_kinds') or ())
        snap['params'] = list(entry.get('params') or ())
        snap['geometry_family'] = list(entry.get('geometry_family') or ())
        snap['aliases'] = list(entry.get('aliases') or ())
        snap['capability'] = dict(entry.get('capability') or {})
        if 'declaration_required' in entry:
            snap['declaration_required'] = bool(entry['declaration_required'])
        out[rid] = snap
    return out


_ALIAS_TO_ROLE: dict[str, str] = {}
for _rid, _entry in ROLE_REGISTRY.items():
    _ALIAS_TO_ROLE[_rid] = _rid
    for _alias in _entry.get('aliases') or ():
        _ALIAS_TO_ROLE[_alias] = _rid


def resolve(role_id: str) -> str:
    """角色名/别名 -> 规范 role_id；未知直接拒绝。"""
    key = str(role_id or '').strip()
    if key in _ALIAS_TO_ROLE:
        return _ALIAS_TO_ROLE[key]
    raise RoleBindingError(f'未知角色 {role_id!r}；注册表只认 '
                           f'{sorted(ROLE_REGISTRY)} 与别名 {sorted(set(_ALIAS_TO_ROLE) - set(ROLE_REGISTRY))}')


def role_of_param(param: str) -> str:
    """YAML 参数键 -> 所属角色；无归属（受保护/未知）直接拒绝。"""
    for role, params in ROLE_TO_PARAMS.items():
        if param in params:
            return role
    raise RoleBindingError(f'参数 {param!r} 不属于任何角色的允许编辑集（受保护或未知，不得猜）')


def resolve_legacy(role_id: str, artist_kind: str) -> str:
    """旧契约（role + artist 家族名）-> 规范 role_id；错配拒绝。

    ``xlabel``/``ylabel`` -> ``axis.title``；``ticklabels`` -> ``axis.tick``；
    ``curve`` -> ``curve.linewidth``。``title``（Axes.title）配给
    ``axis.title`` 是错配（正主是保留角色 ``axes.title``），拒绝。
    """
    canonical = resolve(role_id)
    entry = ROLE_REGISTRY[canonical]
    kind = str(artist_kind or '').strip()
    if kind in entry.get('artist_kinds', ()):
        return canonical
    hint = ''
    if canonical == 'axis.title' and kind == 'title':
        hint = '（Axes.title 的正主是保留角色 axes.title，只读、不可统一）'
    raise RoleBindingError(
        f'错配拒绝：role {canonical!r} 不允许绑定 artist kind {kind!r}{hint}；'
        f'该角色只认 {list(entry.get("artist_kinds", ()))}（定义：{entry.get("definition")}）')


def classify_artist(artist, fig=None) -> str:
    """按图元本身判语义家族（旧契约的 kind 词表；新图元诚实落到 artist）。

    有 fig 时按身份精确分类（轴标签/标题/刻度/图例/曲线）；无 fig 时只按类名
    粗分（Text 统称 text，不冒充 xlabel）。
    """
    if fig is not None:
        try:
            axes = list(fig.axes)
        except Exception:
            axes = []
        for ax in axes:
            try:
                if artist is ax.xaxis.label:
                    return 'xlabel'
                if artist is ax.yaxis.label:
                    return 'ylabel'
                if artist in (ax.title, getattr(ax, '_left_title', None),
                              getattr(ax, '_right_title', None)):
                    return 'title'
            except Exception:
                pass
            try:
                ticks = list(ax.xaxis.get_major_ticks()) + list(ax.xaxis.get_minor_ticks()) \
                    + list(ax.yaxis.get_major_ticks()) + list(ax.yaxis.get_minor_ticks())
            except Exception:
                ticks = []
            for tick in ticks:
                try:
                    if artist in (tick.label1, tick.label2):
                        return 'ticklabels'
                except Exception:
                    continue
            try:
                legend = ax.get_legend()
                if legend is not None:
                    if artist is legend:
                        return 'legend'
                    if artist in list(legend.get_texts()):
                        return 'legend_text'
            except Exception:
                pass
            try:
                if artist in list(ax.lines):
                    return 'curve'
            except Exception:
                pass
    if isinstance(artist, matplotlib.lines.Line2D):
        return 'curve'
    if isinstance(artist, matplotlib.legend.Legend):
        return 'legend'
    if isinstance(artist, matplotlib.text.Text):
        return 'text'
    if isinstance(artist, matplotlib.axes.Axes):
        return 'panel'
    if isinstance(artist, matplotlib.figure.Figure):
        return 'figure'
    if isinstance(artist, matplotlib.collections.Collection):
        return 'collection'
    if isinstance(artist, matplotlib.patches.Patch):
        return 'shape'
    return 'artist'


def is_panel_label_position(artist, fig) -> bool:
    """轴外/角位置判定（panel.label 可判定规则之二）：通用几何判据。"""
    if fig is None:
        return False
    try:
        fig.canvas.draw_without_rendering()
    except Exception:
        try:
            fig.canvas.draw()
        except Exception:
            return False
    try:
        renderer = fig.canvas.get_renderer()
    except Exception:
        return False
    try:
        _bb = artist.get_window_extent(renderer)
        cx, cy = (_bb.x0 + _bb.x1) / 2.0, (_bb.y0 + _bb.y1) / 2.0
    except Exception:
        return False
    try:
        axes = list(fig.axes)
    except Exception:
        return False
    for ax in axes:
        try:
            box = ax.get_window_extent(renderer)
        except Exception:
            continue
        x0, y0 = box.x0, box.y0
        w, h = box.width, box.height
        if w <= 0 or h <= 0:
            continue
        inside = (x0 <= cx <= x0 + w and y0 <= cy <= y0 + h)
        if not inside:
            return True
        fx = (cx - x0) / w
        fy = (cy - y0) / h
        if (fx <= 0.15 or fx >= 0.85) and (fy <= 0.15 or fy >= 0.85):
            return True
    return False

def is_declared_panel_label(artist, fig=None, reg=None) -> bool:
    """panel.label 可判定规则：契约显式声明 或 轴外/角位置。"""
    entry = ROLE_REGISTRY.get('panel.label') or {}
    want = set(entry.get('params') or ())
    try:
        gid = artist.get_gid() if hasattr(artist, 'get_gid') else None
    except Exception:
        gid = None
    if gid and reg is not None and hasattr(reg, 'params_of'):
        try:
            if want & set(reg.params_of(gid)):
                return True
        except Exception:
            pass
    return bool(is_panel_label_position(artist, fig))

def check_binding(role_id: str, artist, fig=None, reg=None) -> dict:
    """role -> Artist 对象配对检查；错配抛 RoleBindingError，正确返回证据。

    有 fig 做身份级核对（xlabel/标题/刻度按身份区分，不因字号数值相同就认）；
    无 fig 只做类级核对（错类照样拒绝）。
    panel.label 另有可判定门：契约显式声明（reg.params_of 含本角色字体键）
    或轴外/角位置（is_panel_label_position）；两者皆无 → 拒绝（调用方记
    unresolved，不得强行归属）。
    """
    canonical = resolve(role_id)
    entry = ROLE_REGISTRY[canonical]
    if entry.get('reserved'):
        raise RoleBindingError(
            f'错配拒绝：{canonical!r} 是保留角色（{entry.get("definition")}），'
            f'不得作为编辑绑定')
    if canonical == 'panel.label' and entry.get('declaration_required'):
        if not is_declared_panel_label(artist, fig, reg):
            raise RoleBindingError(
                f'错配拒绝：role {canonical!r} 只认契约显式声明或轴外/角位置的面板文本；'
                f'无判据的任意 Text 不得归属（unresolved）')
    # legend：Legend 本体无 get_fontsize，绑定语义是"行文本字号"；本体只认
    # Legend 类（下述类检查），行文本只认 legend.get_texts() 成员（下述身份核
    # 对经 classify_artist 判 legend_text）。无专用分支，无额外放行。
    classes = entry.get('artist_classes') or ()
    if classes and not isinstance(artist, classes):
        raise RoleBindingError(
            f'错配拒绝：role {canonical!r} 只认 '
            f'{[c.__name__ for c in classes]}，得到 {type(artist).__name__}')
    kind = classify_artist(artist, fig)
    if fig is not None and kind not in (entry.get('artist_kinds') or ()):
        hint = ''
        if canonical == 'axis.title' and kind == 'title':
            hint = '（这是 Axes.title，正主是保留角色 axes.title）'
        detail = {'role': canonical, 'artist_kind': kind,
                  'artist_type': type(artist).__name__}
        try:
            detail['gid'] = artist.get_gid()
        except Exception:
            pass
        try:
            text = artist.get_text() if hasattr(artist, 'get_text') else None
            if isinstance(text, str):
                detail['text'] = text[:40]
        except Exception:
            pass
        raise RoleBindingError(
            f'错配拒绝：role {canonical!r} 不认 artist kind {kind!r}{hint}；'
            f'证据 {detail}')
    return {'role': canonical, 'artist_kind': kind,
            'verified': fig is not None, 'reserved': False}
