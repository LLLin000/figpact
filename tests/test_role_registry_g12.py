"""G12 角色注册表 + 对象级差异审计测试。

- 注册表唯一性：错配拒绝（axis.title x tick / Axes.title / curve x Text；
  set_title 旧契约家族经 resolve_legacy 判为错配，保留角色 axes.title 只读）；
  旧契约 xlabel/ylabel/ticklabels/curve 兼容无歧义。
- 修改有效性：verify_param 非零扰动确实改变声明目标；无效修改（无归属参数）
  报 ChangeAuditError，不得通过。
- 副作用检测/定位/阻断：audit_pair 对非目标未授权变化点名 gid+属性+前后值；
  init_contract.verify 把越权记入 failure 并判 failed。
- FTIR 反例只做来源断言（k 与名义值口径），不得升 E✓ 由 compare 语义保证
  （covered in e2e：tick 在 FTIR layout contract 非 EDITABLE）。
"""
import pytest

from figpact import change_audit, roles


def test_registry_rejects_wrong_pairings():
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots()
    try:
        ax.set_xlabel('x', fontsize=8)
        ax.set_title('t', fontsize=8)
        tick = ax.xaxis.get_major_ticks()[0].label1
        fig.canvas.draw()
        # 正确配对放行
        assert roles.check_binding('axis.title', ax.xaxis.label, fig)['verified'] is True
        # 错配拒绝：tick 配给 axis.title（数值相同也不认）
        with pytest.raises(roles.RoleBindingError):
            roles.check_binding('axis.title', tick, fig)
        # 错配拒绝：Axes.title 配给 axis.title（正主是保留角色 axes.title）
        with pytest.raises(roles.RoleBindingError):
            roles.check_binding('axis.title', ax.title, fig)
        # 保留角色只读：任何绑定都拒绝
        with pytest.raises(roles.RoleBindingError):
            roles.check_binding('axes.title', ax.title, fig)
        # 错类拒绝：Text 配给 curve.linewidth
        with pytest.raises(roles.RoleBindingError):
            roles.check_binding('curve.linewidth', ax.xaxis.label, fig)
    finally:
        plt.close(fig)


def test_legacy_contract_kinds_resolve_unambiguously():
    assert roles.resolve_legacy('axis.title', 'xlabel') == 'axis.title'
    assert roles.resolve_legacy('axis.title', 'ylabel') == 'axis.title'
    assert roles.resolve_legacy('axis.tick', 'ticklabels') == 'axis.tick'
    assert roles.resolve_legacy('curve.linewidth', 'curve') == 'curve.linewidth'
    # set_title 家族是 Axes.title：配给 axis.title 必须拒绝（旧契约不迁移，但新验证拒绝）
    with pytest.raises(roles.RoleBindingError):
        roles.resolve_legacy('axis.title', 'title')
    # 别名兼容：axis.label.x -> axis.title
    assert roles.resolve('axis.label.x') == 'axis.title'


def test_verify_param_effective_change_demo_linewidth():
    r = change_audit.verify_param('examples/demo/demo_figure.py',
                                  'examples/demo/demo.yaml', 'main', 'line_width')
    assert r['status'] == 'EFFECT_OK'
    assert r['target_effectively_changed'] is True
    assert r['unauthorized'] == []
    assert r['science_unchanged'] is True


def test_verify_param_invalid_never_passes():
    with pytest.raises(change_audit.ChangeAuditError):
        change_audit.verify_param('examples/demo/demo_figure.py',
                                  'examples/demo/demo.yaml', 'main',
                                  'label_font_pt')


def test_audit_pair_detects_locates_blocks_unauthorized():
    before = {'styles': {'g1': {'fontsize': 8.0}, 'g2': {'fontsize': 7.0}},
              'shapes': {}}
    after = {'styles': {'g1': {'fontsize': 9.0}, 'g2': {'fontsize': 8.0}},
             'shapes': {}}
    allowed = {'styles': {'g1': {'fontsize'}},
               'shapes': {},
               'required_targets': [{'gid': 'g1', 'property': 'fontsize'}]}
    res = change_audit.audit_pair(before, after, allowed)
    assert res['within_allowed'] is False
    assert res['unauthorized'] == [{'gid': 'g2', 'property': 'fontsize',
                                   'before': 7.0, 'after': 8.0, 'class': 'semantic'}]
    assert res['required_targets_effectively_changed'] == {'g1.fontsize': [8.0, 9.0]}
    assert res['all_required_changed'] is True


def test_audit_pair_required_target_unchanged_flagged():
    before = {'styles': {'g1': {'fontsize': 8.0}}, 'shapes': {}}
    after = {'styles': {'g1': {'fontsize': 8.0}}, 'shapes': {}}
    allowed = {'styles': {'g1': {'fontsize'}},
               'shapes': {},
               'required_targets': [{'gid': 'g1', 'property': 'fontsize'}]}
    res = change_audit.audit_pair(before, after, allowed)
    assert res['within_allowed'] is True
    assert res['required_targets_effectively_changed'] == {'g1.fontsize': None}
    assert res['all_required_changed'] is False


def test_ftir_tick_counterfactual_source_is_canvas_k_not_param():
    # FTIR 反例的来源断言：tick 名义值从未被改（YAML 8.0），13.343 只是
    # nominal x k（k=80/47.964≈1.6679）的派生几何；分类见回执 change_audit。
    from figpact.final_size import audit_figure
    import yaml

    cfg = yaml.safe_load(open('examples/ftir/ftir.yaml', encoding='utf-8').read())
    assert float(cfg['tick_font_pt']) == 8.0
    r48 = audit_figure('examples/ftir/plot_ftir.py', config='examples/ftir/ftir.yaml',
                       target_width_mm=48.0, scope='main')
    r80 = audit_figure('examples/ftir/plot_ftir.py', config='examples/ftir/ftir.yaml',
                       target_width_mm=80.0, scope='main')
    tick48 = next(x for x in r48['font_roles'] if x['role_key'] == 'tick_font_pt')
    tick80 = next(x for x in r80['font_roles'] if x['role_key'] == 'tick_font_pt')
    assert tick48['nominal_pt'] == tick80['nominal_pt'] == 8.0
    assert abs(r80['k'] - 80.0 / r80['measured_export_mm'][0]) < 1e-3
    assert abs(tick80['effective_pt_at_target'] - 8.0 * r80['k']) < 1e-3
    assert abs(tick80['effective_pt_at_target'] - 13.343) < 0.01
