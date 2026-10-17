"""G12-B 对象级差异审计：修改前后统一快照，判定越权与假成功。

复用既有链路，不建并行系统：

- 快照：``figpact.session.FigureSession``（``_styles`` 注册表语义属性 +
  ``drawn_shapes`` 显示几何 + ``_capture_science`` 科学指纹）；
- 扰动执行：``figpact.effects.probe_value``（有界非零扰动）；
- 几何增量：``figpact.session.shape_delta``（含该比较适用容差）；
- 角色语义：``figpact.roles``（允许集、几何家族）；
- 写入链：``figpact.final_size.apply_final_size``（YAML 定点补丁 +
  ``source_writes`` journal + 写后复测）。

判定（G12-B）：

```
ActualChanges        ⊆  AllowedChanges          （无越权，否则拒绝提交）
RequiredTargetsEffectivelyChanged               （目标确实变了；防假成功）
```

三类变化（合法位移不当副作用）：语义属性变更 / 允许的派生几何变化 /
受保护科学内容（科学指纹由 ``_compare_science`` 判定，这里只搬结论）。
"""
from __future__ import annotations

import copy
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Optional

import yaml

from figpact import roles
from figpact.session import FigureSession, drawn_shapes

AUDIT_SCHEMA = 'figpact.change-audit/1'

_STYLE_NUMERIC_TOL = 1e-9


class ChangeAuditError(RuntimeError):
    """审计前置失败（快照不可比、参数无归属等）：拒绝给出结论。"""


#: 对象级审计只看语义属性（G12-B 三类变化的第一类）：字号/线宽/文本内容。
#: color/alpha/markersize/visible/renderer_dpi 是“每次重建必然重排的身份噪音”
#: （容器、占位符、空标题每次都在），进快照只会把“对象在场”等同于“对象变了”。
_SEMANTIC_PROPS = (('fontsize', 'get_fontsize'), ('linewidth', 'get_linewidth'),
                   ('text', 'get_text'))


def _style_entry(fig, art):
    from figpact.session import _json_native
    entry = {}
    for prop, getter in _SEMANTIC_PROPS:
        fn = getattr(art, getter, None)
        if not callable(fn):
            if prop == 'fontsize':
                # Legend 本体无 get_fontsize：行文本字号即其语义字号（通用口径）。
                try:
                    import matplotlib.legend as _leg
                    if isinstance(art, _leg.Legend):
                        texts = list(art.get_texts())
                        if texts:
                            entry[prop] = _json_native(float(texts[0].get_fontsize()))
                except Exception:
                    pass
            continue
        try:
            value = fn()
        except Exception:
            continue
        if isinstance(value, str) and len(value) > 60:
            value = value[:60]
        entry[prop] = _json_native(value)
    if art is fig or art is fig.patch:
        try:
            entry['renderer_dpi'] = float(fig.dpi)
        except Exception:
            pass
    return entry


def _stable_key(fig, reg, art, taken: set) -> str:
    gid = art.get_gid() if hasattr(art, 'get_gid') else None
    try:
        if gid and reg.all().get(gid) is art:
            return gid
    except Exception:
        pass
    try:
        axes = list(fig.axes)
    except Exception:
        axes = []
    try:
        import matplotlib.lines as _lines
        import matplotlib.text as _text
        if isinstance(art, _text.Text):
            for ax_idx, ax in enumerate(axes):
                try:
                    if art is ax.xaxis.label:
                        return f'unregistered.{ax_idx}.xlabel'
                    if art is ax.yaxis.label:
                        return f'unregistered.{ax_idx}.ylabel'
                    if art in (ax.title, getattr(ax, '_left_title', None),
                               getattr(ax, '_right_title', None)):
                        return f'unregistered.{ax_idx}.title'
                except Exception:
                    pass
            # 刻度标签：同轴同文本即同一身份（扰动前后稳定，不数遍历位置）。
            try:
                from figpact import roles as _r
                if _r.classify_artist(art, fig) == 'ticklabels':
                    content = str(art.get_text() or '')
                    axis_name = 't'
                    for ax_idx, ax in enumerate(axes):
                        try:
                            xticks = list(ax.xaxis.get_major_ticks()) + list(ax.xaxis.get_minor_ticks())
                            yticks = list(ax.yaxis.get_major_ticks()) + list(ax.yaxis.get_minor_ticks())
                            if art in [t.label1 for t in xticks] + [t.label2 for t in xticks]:
                                axis_name = 'x'
                                break
                            if art in [t.label1 for t in yticks] + [t.label2 for t in yticks]:
                                axis_name = 'y'
                                break
                        except Exception:
                            pass
                    n = sum(1 for o in taken if o.startswith(f'unregistered.tick.{axis_name}.{content}.'))
                    return f'unregistered.tick.{axis_name}.{content}.{n}'
            except Exception:
                pass
            # 图例行文本：同图例同行文本即同一身份（通用身份，不给具体 Artist
            # 写分支：身份经 roles.classify_artist 判 legend_text，键按图例行序）。
            try:
                from figpact import roles as _r
                if _r.classify_artist(art, fig) == 'legend_text':
                    for ax_idx, ax in enumerate(axes):
                        try:
                            leg = ax.get_legend()
                            texts = list(leg.get_texts()) if leg is not None else []
                        except Exception:
                            texts = []
                        if art in texts:
                            return f'unregistered.{ax_idx}.legend_text.{texts.index(art)}'
            except Exception:
                pass
            # 图例行柄：图例的装饰线，不是数据曲线（扰动跟着图例字号联动，不算越权）。
            for ax_idx, ax in enumerate(axes):
                try:
                    legend = ax.get_legend()
                    handles = list(legend.legend_handles) if legend is not None and hasattr(legend, 'legend_handles') else []
                except Exception:
                    handles = []
                if art in handles:
                    return f'unregistered.{ax_idx}.legend_handle.{handles.index(art)}'
    except Exception:
        pass
    base = f'unregistered.{type(art).__name__}'
    i = 0
    while f'{base}.{i}' in taken:
        i += 1
    return f'{base}.{i}'


def style_snapshot(session: FigureSession, fig, reg) -> dict:
    """全部可见 Artist 的语义属性快照（注册 gid；未注册用稳定键）。

    G11B/G12-B 的关键修正：科学指纹不变 ≠ 非目标不变。只拍注册表会漏掉
    未注册的轴标签/刻度（demo/FTIR 的 tick 从未注册），扰动前后恒空快照
    会把“没量到”当成“没变化”。未注册键如实标记，不冒充注册身份。
    """
    out = {}
    taken: set = set()
    try:
        registered = {id(a): gid for gid, a in reg.all().items()}
    except Exception:
        registered = {}
    try:
        artists = list(fig.findobj())
    except Exception:
        artists = []
    for art in artists:
        if not hasattr(art, 'get_visible'):
            continue
        try:
            if not art.get_visible():
                continue
        except Exception:
            continue
        key = registered.get(id(art))
        if key is None:
            key = _stable_key(fig, reg, art, taken)
        taken.add(key)
        entry = _style_entry(fig, art)
        if entry:
            out[key] = entry
    for gid, art in (reg.all().items() if hasattr(reg, 'all') else {}.items()):
        if gid not in out:
            entry = _style_entry(fig, art)
            if entry:
                out[gid] = entry
    return out


def geometry_snapshot(fig, reg) -> dict:
    """全图显示几何快照（含画布/面板容器边界）。"""
    with redirect_stdout(io.StringIO()):
        return drawn_shapes(fig, reg, include_frames=True)


def capture_snapshot(session: FigureSession) -> dict:
    """基线快照：全量 styles + shapes + science + **受保护视图**（与扰动后同一口径）。

    不得直接复用 ``session._baseline`` 的注册表窄快照：窄快照里没有未注册
    的轴标签/刻度，与扰动后的全量快照一比，全是“新增”，全是误报。
    基线同样走一次真实重建（原 YAML），两次快照同一口径才可比。
    """
    with redirect_stdout(io.StringIO()):
        fig, reg = session.build_from_yaml(str(session.config))
    try:
        with redirect_stdout(io.StringIO()):
            shapes = geometry_snapshot(fig, reg)
        styles = style_snapshot(session, fig, reg)
        science = session._capture_science(fig, reg)
        view = _view_snapshot(fig)
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)
    return {'styles': styles, 'shapes': shapes, 'science': science,
            'view': view, 'gids': sorted(reg.all())}


def _view_snapshot(fig) -> dict:
    """受保护的科学视图状态：坐标范围、scale、是否反向（逐 Axes）。"""
    out = {}
    for i, ax in enumerate(getattr(fig, 'axes', []) or []):
        try:
            out[f'axes{i}'] = {
                'xlim': [float(v) for v in ax.get_xlim()],
                'ylim': [float(v) for v in ax.get_ylim()],
                'xscale': str(ax.get_xscale()),
                'yscale': str(ax.get_yscale()),
                'x_inverted': bool(ax.xaxis_inverted()),
                'y_inverted': bool(ax.yaxis_inverted()),
            }
        except Exception:
            continue
    return out


def audit_pair(before: dict, after: dict, allowed: dict) -> dict:
    """两次快照的差异审计：Actual ⊆ Allowed，且目标确实变了。

    ``allowed``: ``{'styles': {gid: {props}}, 'shapes': {shape_key: ...},
    'exempt': [{'gid/key':..., 'by':..., 'reason':...}]}``。
    豁免只认显式条目（谁、依据、范围），且只豁免几何位移，不豁免科学内容。
    """
    style_changes = _style_diff(before.get('styles') or {}, after.get('styles') or {})
    geom_changes, geom_added, geom_removed = _geometry_diff(
        before.get('shapes') or {}, after.get('shapes') or {})
    allowed_styles = allowed.get('styles') or {}
    allowed_shapes = allowed.get('shapes') or {}
    exempt_keys = {(e.get('gid') or e.get('key')) for e in (allowed.get('exempt') or [])}

    unauthorized = []
    for gid, props in sorted(style_changes.items()):
        allow_props = set((allowed_styles.get(gid) or ()))
        for prop, (vb, va) in sorted(props.items()):
            if prop in allow_props:
                continue
            if gid in exempt_keys:
                continue
            unauthorized.append({'gid': gid, 'property': prop,
                                 'before': vb, 'after': va,
                                 'class': 'semantic'})
    for key, delta in sorted(geom_changes.items()):
        if key in allowed_shapes or key.split(':', 1)[-1] in exempt_keys:
            continue
        gid = key.split(':', 1)[1] if key.startswith('gid:') else key
        if gid in exempt_keys:
            continue
        unauthorized.append({'gid': gid, 'property': f'shape:{key}',
                             'before': None, 'after': None,
                             'class': 'derived-geometry', 'delta': delta})
    for key in sorted(geom_added):
        unauthorized.append({'gid': key.split(':', 1)[-1], 'property': f'shape:{key}',
                             'before': 'absent', 'after': 'present',
                             'class': 'structure-added'})
    for key in sorted(geom_removed):
        unauthorized.append({'gid': key.split(':', 1)[-1], 'property': f'shape:{key}',
                             'before': 'present', 'after': 'absent',
                             'class': 'structure-removed'})

    # 缺失证据必须 fail-closed：任一侧没有 view 快照时，**不得**解释为"没有变化"。
    if 'view' not in before or 'view' not in after:
        unauthorized.append({'gid': '', 'property': 'view',
                             'before': before.get('view'), 'after': after.get('view'),
                             'class': 'AUDIT_INCOMPLETE'})

    # 受保护的**科学视图**：坐标范围、scale、反向。未经显式授权（allowed['view']）
    # 的变化一律判越权——数据坐标窗口不属于"排版可动"的范畴。
    vb, va = before.get('view') or {}, after.get('view') or {}
    for key in sorted(set(vb) | set(va)):
        if key in set(allowed.get('view') or ()):
            continue
        if vb.get(key) != va.get(key):
            unauthorized.append({'gid': key, 'property': 'view',
                                 'before': vb.get(key), 'after': va.get(key),
                                 'class': 'protected-view'})

    required = allowed.get('required_targets') or []
    required_changed = {}
    for target in required:
        gid = target.get('gid')
        prop = target.get('property')
        change = (style_changes.get(gid) or {}).get(prop)
        required_changed[f'{gid}.{prop}'] = (
            list(change) if change is not None else None)

    actual = {'styles': style_changes,
              'geometry': geom_changes,
              'added': geom_added, 'removed': geom_removed}
    derived = [u for u in unauthorized if u.get('class') == 'derived-geometry']
    hard = [u for u in unauthorized if u.get('class') != 'derived-geometry']
    return {'schema': AUDIT_SCHEMA,
            'actual_changes': actual,
            'unauthorized': hard,
            'derived_geometry': derived,
            'within_allowed': not hard,
            'required_targets_effectively_changed': required_changed,
            'all_required_changed': all(v is not None for v in required_changed.values()),
            'exempt': list(allowed.get('exempt') or [])}


def verify_param(script: Any, config: Any, scope: str, param: str,
                 probe: Optional[float] = None,
                 width_mm: Optional[float] = None) -> dict:
    """单参数对象级审计：真实临时 YAML 扰动 + 真实整图重建。

    允许集 = 该参数所属角色的（声明对象 × 允许属性）＋ 该角色的几何家族；
    家族外几何位移记 ``recorded-layout-coupling``（量化留痕，不否决）——
    但**未声明对象的语义属性变化一律否决**。科学指纹变化一律否决。
    """
    from figpact import effects

    script_p, config_p = Path(str(script)), Path(str(config))
    role = roles.role_of_param(param)  # 无归属/受保护：直接拒绝
    entry = roles.ROLE_REGISTRY[role]
    session = FigureSession(str(script_p), str(config_p), scope)
    try:
        base_cfg = copy.deepcopy(session._base_config)
        if width_mm is None:
            width_mm = float(base_cfg.get('canvas_w_mm', 42.0))
        try:
            current = base_cfg[param]
        except KeyError:
            raise ChangeAuditError(f'配置里没有参数 {param!r}（悬空绑定，不得猜）')
        if isinstance(current, bool) or not isinstance(current, (int, float)):
            raise ChangeAuditError(f'参数 {param!r} 非有限数字：{current!r}')
        record_bounds = {'min': None, 'max': None}
        try:
            from figpact.final_size import _import_script as _imp
            scalars = getattr(_imp(script_p), 'SCALARS', {}) or {}
            spec = scalars.get(param)
            if isinstance(spec, tuple) and len(spec) == 3:
                record_bounds = {'min': spec[1], 'max': spec[2]}
        except Exception:
            pass
        probe = float(probe) if probe is not None else effects.probe_value(
            record_bounds, float(current))
        if probe is None or probe == float(current):
            raise ChangeAuditError(
                f'参数 {param!r} 给不出非零有界扰动（当前 {current}）')
        pert = copy.deepcopy(base_cfg)
        pert[param] = probe
        tmp = tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False,
                                          encoding='utf8')
        try:
            yaml.safe_dump(pert, tmp, sort_keys=False, allow_unicode=True)
            tmp.close()
            base = capture_snapshot(session)
            with redirect_stdout(io.StringIO()):
                fig, reg = session.build_from_yaml(tmp.name)
            try:
                with redirect_stdout(io.StringIO()):
                    after_shapes = geometry_snapshot(fig, reg)
                after_styles = style_snapshot(session, fig, reg)
                after_science = session._capture_science(fig, reg)
                after_view = _view_snapshot(fig)
            finally:
                import matplotlib.pyplot as plt
                plt.close(fig)
            after = {'styles': after_styles, 'shapes': after_shapes,
                     'science': after_science,
                     'view': after_view,
                     'gids': sorted(reg.all())}
        finally:
            try:
                Path(tmp.name).unlink()
            except OSError:
                pass

        declared_gids = {gid for gid in base['gids']
                         if param in reg.params_of(gid)} if hasattr(reg, 'params_of') else set()
        # 未注册但字号命中同一参数的 tick/轴标签：归属按“身份 + 同值”语义补齐。
        # 身份经 roles.classify_artist 判定（错类拒绝）；同值指该 Artist 的属性值
        # 恰好等于被扰动参数的当前值（与 plate._measure_code_artist_effs 同口径）。
        # 两条同时成立才归因：只同值不同身份（如 legend 撞衫）不得归因。
        declared_gids |= _attribute_unregistered(
            session, base, role, param, float(current))
        allowed_styles = {gid: set(entry.get('properties') or ())
                          for gid in declared_gids}
        # 图例行柄是图例的装饰线（Line2D 却非数据曲线）：随图例/曲线参数联动
        # 是预期耦合，不算越权。允许集按身份补齐，不按字号猜。见
        # _legend_handle_allowlist（verify_param 与 init_contract.verify 共用）。
        if role in ('curve.linewidth', 'legend'):
            for key in (after.get('styles') or {}):
                if '.legend_handle.' in str(key):
                    allowed_styles.setdefault(key, {'linewidth'})
            allowed_styles.update(_legend_handle_allowlist(session, after.get('styles') or {}))
        family = roles.GEOMETRY_FAMILY.get(role, ())
        fam_keys = {k for k in after['shapes']
                    if any(f in k for f in family)} | \
                   {k for k in base['shapes']
                    if any(f in k for f in family)}
        allowed = {'styles': allowed_styles,
                   'shapes': {k: 'geometry-family' for k in fam_keys},
                   'required_targets': [{'gid': g, 'property': p}
                                         for g in sorted(declared_gids)
                                         for p in (entry.get('properties') or ())]}
        result = audit_pair(base, after, allowed)
        # 家族外几何位移：量化留痕，不否决（合法位移不当副作用）。
        result['side_effects'] = [
            {'gid': u['gid'], 'delta': u.get('delta'),
             'disposition': 'recorded-layout-coupling'} for u in result.get('derived_geometry', [])]
        hard = list(result['unauthorized'])
        # 目标有效性：声明对象上至少有一个允许属性真的变了（防假成功）。
        target_hit = any(
            gid in (result['actual_changes']['styles'] or {})
            for gid in declared_gids)
        result['target_effectively_changed'] = bool(target_hit)
        # 科学指纹：只搬 _compare_science 结论，不自创口径。
        sci_ok, sci_notes = session._compare_science(base['science'], after['science'])
        result['science_unchanged'] = sci_ok
        result['science_notes'] = list(map(str, sci_notes or []))
        if sci_ok is False:
            result['status'] = 'SCIENCE_VIOLATION'
        elif hard:
            result['status'] = 'EFFECT_MISMATCH'
        elif not target_hit:
            result['status'] = 'NO_EFFECT'
        else:
            result['status'] = 'EFFECT_OK'
        result.update({'role': role, 'param': param, 'scope': scope,
                       'perturbation': {'from': float(current), 'to': float(probe),
                                        'nonzero': True},
                       'declared_objects': sorted(declared_gids)})
        return result
    finally:
        session.close()


def _attribute_unregistered(session, base, role, param, current: float) -> set:
    import matplotlib.pyplot as plt
    entry = roles.ROLE_REGISTRY[role]
    kinds = set(entry.get('artist_kinds') or ())
    prop = (entry.get('properties') or [None])[0]
    out: set = set()
    fig, reg = None, None
    try:
        with redirect_stdout(io.StringIO()):
            fig, reg = session.build_from_yaml(str(session.config))
        try:
            artists = list(fig.findobj())
        except Exception:
            artists = []
        artists = [a for a in artists if hasattr(a, 'get_visible')]
        try:
            registered_ids = {id(a) for a in reg.all().values()}
        except Exception:
            registered_ids = set()
        for art in artists:
            try:
                if not art.get_visible() or id(art) in registered_ids:
                    continue
            except Exception:
                continue
            # 身份与同值两条同时成立才归因（未注册 tick/轴标签补齐）。
            try:
                kind = roles.classify_artist(art, fig)
            except Exception:
                continue
            try:
                if prop == 'fontsize':
                    if kind == 'legend':
                        # Legend 本体无 get_fontsize：语义是行文本字号，取其
                        # 首行文本 nominal（通用口径，无专用分支）。
                        try:
                            texts = list(art.get_texts())
                        except Exception:
                            continue
                        if not texts:
                            continue
                        value = float(texts[0].get_fontsize())
                    else:
                        value = float(art.get_fontsize())
                elif prop == 'linewidth':
                    value = float(art.get_linewidth())
                else:
                    continue
            except Exception:
                continue
            if abs(value - current) > _STYLE_NUMERIC_TOL:
                continue
            key = _stable_key(fig, reg, art, set())
            out.add(key)
    finally:
        if fig is not None:
            try:
                plt.close(fig)
            except Exception:
                pass
    return out


def _legend_handle_allowlist(session, after_styles: Optional[dict] = None) -> dict:
    """图例行柄允许集（通用身份）：快照里行柄身份的键 -> linewidth。

    行柄是图例的装饰线（Line2D 却非数据曲线），随图例/曲线参数联动是预期
    耦合。稳定键按 findobj 遍历序编号，另起一套 taken 会错位：直接复用扰动
    后快照里"与基线同值行柄同键"的键——行柄 lw 恒等于曲线 lw（装饰线跟随），
    故扰动前后行柄键集合一致；在 after 快照里按"Line2D 且 lw==曲线值"认行柄
    会误伤数据曲线，这里按"非 ax.lines 且在 legend_handles 里"的身份认。
    """
    out: dict = {}
    if not after_styles:
        return out
    try:
        import matplotlib.pyplot as _plt
        import matplotlib.lines as _lines
        _fig2, _reg2 = None, None
        with redirect_stdout(io.StringIO()):
            _fig2, _reg2 = session.build_from_yaml(str(session.config))
        try:
            _handles = set()
            for _ax in (_fig2.axes or []):
                try:
                    _leg = _ax.get_legend()
                    _hh = list(_leg.legend_handles) if _leg is not None and hasattr(_leg, 'legend_handles') else []
                except Exception:
                    _hh = []
                _handles |= {id(h) for h in _hh}
            _taken: set = set()
            for _art in _fig2.findobj():
                if not hasattr(_art, 'get_visible'):
                    continue
                try:
                    if not _art.get_visible():
                        continue
                except Exception:
                    continue
                _key = _stable_key(_fig2, _reg2, _art, _taken)
                _taken.add(_key)
                if isinstance(_art, _lines.Line2D) and id(_art) in _handles and _key in after_styles:
                    out.setdefault(_key, {'linewidth'})
        finally:
            try:
                _plt.close(_fig2)
            except Exception:
                pass
    except Exception:
        pass
    return out


def _style_diff(before: dict, after: dict) -> dict:
    out = {}
    for gid in sorted(set(before) | set(after)):
        b, a = before.get(gid) or {}, after.get(gid) or {}
        props = {}
        for prop in sorted(set(b) | set(a)):
            vb, va = b.get(prop), a.get(prop)
            if isinstance(vb, float) and isinstance(va, float):
                if abs(vb - va) <= _STYLE_NUMERIC_TOL:
                    continue
            elif vb == va:
                continue
            props[prop] = [vb, va]
        if props:
            out[gid] = props
    return out


def _geometry_diff(before: dict, after: dict):
    from figpact.session import shape_delta
    changed, added, removed = {}, [], []
    for key in sorted(set(before) - set(after)):
        removed.append(key)
    for key in sorted(set(after) - set(before)):
        added.append(key)
    for key in sorted(set(before) & set(after)):
        delta = shape_delta(before[key], after[key])
        if max(abs(delta['dx_mm']), abs(delta['dy_mm']),
               abs(delta['dw_mm']), abs(delta['dh_mm'])) > delta['tol_mm']:
            changed[key] = {k: (round(v, 4) if isinstance(v, float) else v)
                            for k, v in delta.items()}
    return changed, added, removed
