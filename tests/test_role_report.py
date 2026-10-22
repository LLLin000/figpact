"""Behavioral coverage for same-capture role facts and read-only capabilities."""
import json

from figpact.role_report import capability_report


def _frame(nodes):
    return {'scene_json': json.dumps({'nodes': nodes})}


def _node(gid, role, axis, *, registered=True, paths=None, font=8.0):
    return {'id': gid, 'gid': gid if registered else None, 'registered': registered,
            'artist_type': 'Text', 'is_text': True, 'font_size_pt': font,
            'visible': True, 'measured': True, 'controlled_by': paths or [],
            'semantic': {'role': role, 'axis': axis, 'axes_id': 'ax0',
                         'axes_context': 'root', 'evidence': 'artist_identity'}}


def test_report_distinguishes_xy_axes_titles_and_rejects_decoy_identity():
    nodes = [_node('xlabel', 'axis.title', 'x', paths=[['axis_font_pt']]),
             _node('ylabel', 'axis.title', 'y', paths=[['axis_font_pt']]),
             _node('decoy', None, None, registered=False, paths=[['axis_font_pt']])]
    controls = [{'control_id': '["axis_font_pt"]', 'path': ['axis_font_pt'], 'unit': 'pt',
                 'value_shape': 'scalar', 'objects': ['xlabel', 'ylabel'], 'min': 5, 'max': 20}]
    projection = {'nodes': [{'id': gid, 'rect_mm': [1, 2, 3, 4], 'measurable': True,
                            'scale_xy': [1, 1], 'anisotropic': False}
                           for gid in ('xlabel', 'ylabel', 'decoy')]}
    result = capability_report(_frame(nodes), controls, projection, editable=True)
    assert result['status'] == 'READY'
    assert [(row['semantic_role'], row['axis']) for row in result['roles']] == [
        ('axis.title', 'x'), ('axis.title', 'y'), (None, None)]
    assert result['roles'][0]['font_controls'][0]['editable'] is True
    assert result['roles'][2]['font_controls'] == []


def test_shared_control_coupling_and_translations_never_become_font_controls():
    nodes = [_node('x', 'axis.title', 'x', paths=[['axis_font_pt']]),
             _node('y', 'axis.title', 'y', paths=[['axis_font_pt']])]
    controls = [
        {'control_id': '["axis_font_pt"]', 'path': ['axis_font_pt'], 'unit': 'pt',
         'value_shape': 'scalar', 'objects': ['x', 'y'], 'min': 5, 'max': 20},
        {'control_id': '["x_shift_mm"]', 'path': ['x_shift_mm'], 'unit': 'mm',
         'value_shape': 'scalar', 'objects': ['x', 'y']},
        {'control_id': '["canvas_w_mm"]', 'path': ['canvas_w_mm'], 'unit': 'pt',
         'value_shape': 'scalar', 'objects': ['x', 'y']}]
    projection = {'nodes': [{'id': gid, 'rect_mm': [0, 0, 2, 2], 'measurable': True,
                            'scale_xy': [2, 2], 'anisotropic': False} for gid in ('x', 'y')]}
    result = capability_report(_frame(nodes), controls, projection, editable=True)
    assert len(result['coupling']) == 1
    assert result['coupling'][0]['affected_role_groups'] == [
        {'role': 'axis.title', 'axis': 'x', 'axes_id': 'ax0', 'axes_context': 'root'},
        {'role': 'axis.title', 'axis': 'y', 'axes_id': 'ax0', 'axes_context': 'root'}]
    assert all(row['effective_font_pt'] == 16 for row in result['roles'])


def test_readonly_unknown_and_anisotropic_are_measurement_only():
    nodes = [_node('x', 'axis.title', 'x', paths=[['axis_font_pt']]),
             _node('unknown', None, None, paths=[['axis_font_pt']])]
    controls = [{'control_id': '["axis_font_pt"]', 'path': ['axis_font_pt'], 'unit': 'pt',
                 'value_shape': 'scalar', 'objects': ['x'], 'min': 5, 'max': 20}]
    projection = {'nodes': [{'id': 'x', 'rect_mm': [0, 0, 2, 2], 'measurable': True,
                            'scale_xy': [2, 1], 'anisotropic': True},
                           {'id': 'unknown', 'rect_mm': None, 'measurable': False,
                            'scale_xy': None, 'anisotropic': None}]}
    result = capability_report(_frame(nodes), controls, projection, editable=False)
    assert result['roles'][0]['effective_font_pt'] is None
    assert result['roles'][0]['font_reason'] == 'ANISOTROPIC_SCALE'
    assert result['roles'][0]['font_controls'][0]['editable'] is False
    assert result['roles'][1]['semantic_role'] is None
    assert result['roles'][1]['effective_font_pt'] is None


def test_scene_semantics_use_exact_axes_identity_and_nested_ownership():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    from figpact.registry import GidRegistry
    from figpact.scene import snapshot

    fig, root = plt.subplots()
    try:
        root.set_xlabel('same decoy text')
        root.set_ylabel('Y')
        root.set_title('X')
        inset = root.inset_axes([0.55, 0.55, 0.3, 0.3])
        inset.set_xlabel('same decoy text')
        inset.set_ylabel('unregistered inset label')
        decoy = root.text(0.4, 0.5, 'X')
        registry = GidRegistry(scope='main')
        registry.register(root.xaxis.label, 'root.x')
        registry.register(root.yaxis.label, 'root.y')
        registry.register(root.title, 'root.title')
        registry.register(inset.xaxis.label, 'inset.x')
        registry.register(decoy, 'decoy')
        result = snapshot(fig, registry, scope='main')
        nodes = {node['id']: node for node in result['nodes']}
        assert nodes['root.x']['semantic'] == {
            'role': 'axis.title', 'axis': 'x', 'axes_id': 'main::panel.0',
            'axes_context': 'root', 'evidence': 'artist_identity'}
        assert nodes['root.y']['semantic']['axis'] == 'y'
        assert nodes['root.title']['semantic']['role'] == 'axes.title'
        assert nodes['inset.x']['semantic']['axes_context'] == 'inset'
        assert nodes['inset.x']['semantic']['role'] == 'axis.title'
        inset_y = next(node for node in result['nodes']
                       if node.get('text') == 'unregistered inset label')
        assert inset_y['registered'] is False
        assert inset_y['semantic']['role'] == 'axis.title'
        assert inset_y['semantic']['axis'] == 'y'
        assert inset_y['semantic']['axes_context'] == 'inset'
        assert inset_y['semantic']['axes_id'] in nodes
        assert nodes['decoy']['semantic']['role'] is None
    finally:
        plt.close(fig)


def test_annotation_subclasses_remain_measured_but_unclassified_and_not_editable():
    annotation = _node('annotation', None, None, registered=False, font=6.0)
    annotation.pop('is_text')
    annotation.update(artist_type='Annotation', type='text')
    projection = {'nodes': [{'id': 'annotation', 'rect_mm': [1, 2, 3, 4],
                             'measurable': True, 'scale_xy': [0.5, 0.5], 'anisotropic': False}]}
    report = capability_report(_frame([annotation]), [], projection, editable=True)
    (row,) = report['roles']
    assert row['source_font_pt'] == 6.0 and row['effective_font_pt'] == 3.0
    assert row['semantic_role'] is None and row['font_controls'] == []
    assert report['status'] == 'UNSUPPORTED'
