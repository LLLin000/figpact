"""Scientific invariants independent of permitted display transforms and panel positions.

Four rules keep this honest:
  * only a node the author declares a guide (``science_policy`` LAYOUT *and* ``type`` guide)
    exempts its decorative geometry -- image pixels, text content, curves, scatter offsets and
    every value array stay protected, and an unknown or missing type fails closed;
  * geometry is hashed in its own data coordinates, never through ``get_verts()`` -- that
    returns the display projection, so a dpi change or an ``apply_display_shift`` translation
    would masquerade as a scientific change;
  * a view window is locked unless the author declares an immutable linear ``layout_viewports``
    y reference *and* the real axes still match it -- then its frozen origin/scale is hashed
    instead of the display headroom above the signal;
  * comparing a missing/absent digest is UNVERIFIED, never "equal".
"""
import hashlib
import json
import numpy as np
from matplotlib.patches import Polygon, Rectangle

LAYOUT_POLICY = 'LAYOUT'
# The one explicit decorative-geometry exemption: a node the author declares a guide (policy
# LAYOUT plus semantic type guide). A science_policy of LAYOUT on its own exempts nothing -- a
# curve, scatter or rectangle whose policy claims layout is still scientific payload, and any
# unknown or missing type fails closed.
GUIDE_TYPE = 'guide'
# Manifest keys that are layout bookkeeping, not source scientific payload. The declared
# viewport reference is one of them: it is hashed per axes only after being verified against the
# real window, so a re-tuned declaration still shows up as a change.
LAYOUT_KEYS = ('nodes', 'parameters', 'relations', 'groups', 'outputs', 'layout_viewports')
# These classes build their path in display coordinates, so that path is not data geometry.
DISPLAY_DERIVED_PATCHES = ('FancyArrowPatch', 'ConnectionPatch')
# Declared viewport verification tolerance: relative on the mm-scale ratio, absolute in data
# units. Stated because this is a measured check, not an exact-arithmetic claim.
VIEWPORT_RTOL, VIEWPORT_ATOL = 1e-6, 1e-9


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False).encode('utf8')).hexdigest()


def _array(value):
    """Content digest of an array, masked or not: shape + dtype + raw bytes."""
    data = np.asanyarray(value)
    raw = np.asarray(data)
    if raw.dtype.hasobject:
        payload = json.dumps(raw.tolist(), ensure_ascii=False, default=str).encode('utf8')
    else:
        payload = memoryview(np.ascontiguousarray(raw)).cast('B')
    result = {'shape': list(raw.shape), 'dtype': str(raw.dtype),
              'digest': hashlib.sha256(payload).hexdigest()}
    if np.ma.isMaskedArray(data):
        mask = np.ma.getmaskarray(data)
        result['mask_digest'] = hashlib.sha256(memoryview(np.ascontiguousarray(mask)).cast('B')).hexdigest()
    return result


def _floats(values):
    return [None if value is None else float(value) for value in values]


def _decorative(metadata, gid):
    """The one explicit decorative-geometry exemption: an author-declared guide.

    Fail closed: a missing or unknown type, an unrecognised science_policy, or LAYOUT without the
    semantic guide type all protect the node. A policy string alone never exempts anything.
    """
    node = metadata.get(gid)
    if not isinstance(node, dict):
        return False
    return node.get('type') == GUIDE_TYPE and node.get('science_policy') == LAYOUT_POLICY


def _axes_height_mm(ax):
    """Physical height of the axes box, from the figure's own size: no renderer, no draw."""
    return float(ax.get_position().height) * float(ax.figure.get_figheight()) * 25.4


def _viewport_record(viewport, ax):
    """Frozen origin/scale for a declared immutable linear *y* viewport, else an honest refusal.

    The declaration is only honoured when the real axis is still that viewport: the actual bottom
    limit equals the declared origin and (ylim span) / (axes height in mm) equals the declared
    units_per_mm within VIEWPORT_RTOL. Then the canonical frozen origin/scale is hashed, so
    growing the canvas for headroom is not a scientific change. Any mismatch -- moved origin,
    rescaled signal, re-tuned declaration, non-numeric or non-``y`` declaration, no axes height --
    hashes the measured window instead, so declaring a viewport can never widen what may move.
    xlim is never declared; it stays locked.
    """
    ylim = _floats(ax.get_ylim())
    if not isinstance(viewport, dict):
        return {'declared': str(viewport), 'verified': False, 'ylim': ylim,
                'reason': 'a viewport declaration must be an object'}
    declared = {'axis': viewport.get('axis'), 'origin': viewport.get('origin'),
                'units_per_mm': viewport.get('units_per_mm')}
    if declared['axis'] != 'y':
        return {**declared, 'verified': False, 'ylim': ylim,
                'reason': 'only the y viewport can be declared'}
    try:
        origin = float(viewport['origin'])
        units = float(viewport['units_per_mm'])
    except (KeyError, TypeError, ValueError):
        return {**declared, 'verified': False, 'ylim': ylim,
                'reason': 'origin and units_per_mm must be numbers'}
    height_mm = _axes_height_mm(ax)
    measured = (ylim[1] - ylim[0]) / height_mm if height_mm else None
    if measured is not None and np.isclose(ylim[0], origin, rtol=VIEWPORT_RTOL, atol=VIEWPORT_ATOL) \
            and np.isclose(measured, units, rtol=VIEWPORT_RTOL, atol=VIEWPORT_ATOL):
        return {'axis': 'y', 'origin': origin, 'units_per_mm': units, 'verified': True,
                'tolerance': {'rtol': VIEWPORT_RTOL, 'atol': VIEWPORT_ATOL}}
    return {**declared, 'verified': False, 'ylim': ylim, 'measured_units_per_mm': measured,
            'reason': 'the real window is not the declared linear viewport'}


def _node_metadata(registry, declarations):
    metadata = {}
    if isinstance(declarations, dict) and isinstance(declarations.get('nodes'), dict):
        metadata = {k: dict(v) for k, v in declarations['nodes'].items() if isinstance(v, dict)}
    if hasattr(registry, 'metadata'):
        for gid in registry.all():
            metadata[gid] = {**metadata.get(gid, {}), **registry.metadata(gid)}
    return metadata


def _collection_record(collection, *, decorative):
    """Value arrays are payload whatever the policy says; raw segments/offsets unless a guide.

    Segments and offsets are native data-space arrays (``get_segments`` never simplifies and
    reads the stored paths), so display shifts and dpi cannot move them. Only an author-declared
    guide collection has its geometry exempt -- a scatter's offsets or a curve's segments still
    count as data when the node merely claims LAYOUT -- and even then a mapped value array is
    hashed.
    """
    values = collection.get_array() if hasattr(collection, 'get_array') else None
    if decorative and values is None:
        return None
    record = {'kind': type(collection).__name__}
    if not decorative:
        segments = list(collection.get_segments()) if hasattr(collection, 'get_segments') else []
        if segments:
            shapes = {np.asanyarray(seg).shape for seg in segments}
            if len(shapes) == 1:
                digest = _array(np.concatenate([np.asanyarray(seg) for seg in segments]))
                digest['count'] = len(segments)
                record['segments'] = digest
            else:
                record['segments'] = [_array(seg) for seg in segments]
        if hasattr(collection, 'get_offsets'):
            offsets = np.asanyarray(collection.get_offsets())
            if offsets.size:
                record['offsets'] = _array(offsets)
    if values is not None:
        record['values'] = _array(values)
    return record


def _native_path(patch):
    """Patch geometry in its own data coordinates: patch transform composed with the raw path.

    ``get_verts()`` must never be used here: it applies the full artist transform, so it moves
    with dpi and with ``apply_display_shift`` even though the scientific window is unchanged.
    """
    try:
        path = patch.get_path()
    except NotImplementedError:
        return None
    if path is None:
        return None
    path = patch.get_patch_transform().transform_path(path)
    record = {'vertices': _array(path.vertices)}
    if path.codes is not None:
        record['codes'] = _array(path.codes)
    return record


def _patch_record(patch):
    """Scientific patch geometry as data-space numbers, or an honest marker if there are none."""
    kind = type(patch).__name__
    record = {'kind': kind}
    if isinstance(patch, Polygon):
        record['xy'] = _array(patch.get_xy())
    elif isinstance(patch, Rectangle):
        record['rect'] = [float(patch.get_x()), float(patch.get_y()),
                          float(patch.get_width()), float(patch.get_height())]
    if kind in DISPLAY_DERIVED_PATCHES:
        # Said plainly instead of inventing data coordinates, but still hashed: an arrow whose
        # rendered path changed must not pass as unchanged science.
        record['geometry'] = 'display_derived'
        try:
            record['display_path'] = _array(patch.get_path().vertices)
        except (AttributeError, NotImplementedError):
            record['display_path'] = None
        return record
    path = _native_path(patch)
    record['geometry'] = 'native' if path is not None else 'unresolved'
    if path is not None:
        record['path'] = path
    values = patch.get_array() if hasattr(patch, 'get_array') else None
    if values is not None:
        record['values'] = _array(values)
    return record


def capture_science(fig, registry, *, declarations=None):
    """Hash actual content, scientific view windows and explicit source/processing declarations.

    Only a declared guide (science_policy LAYOUT and type guide) has its decorative geometry
    exempt. Image pixels, image origin and image display range are always protected -- axes images
    and figure images (``fig.figimage``) alike, the latter carrying no data-space extent, so only
    their placement stays layout -- as are text content, curve arrays and scatter offsets, and
    collection value arrays are protected even on a guide.
    Rotation is layout and stays out of the text content hash, while the raw scientific payload of
    source declarations (including scale-bar meaning/ratio) is hashed.
    A y view window is locked unless ``declarations['layout_viewports']`` declares an immutable
    linear reference for that axes and the real axes still matches it (see ``_viewport_record``).
    """
    metadata = _node_metadata(registry, declarations)
    viewports = declarations.get('layout_viewports') if isinstance(declarations, dict) else None
    if not isinstance(viewports, dict):
        viewports = {}
    records = {}
    for i, ax in enumerate(fig.axes):
        panel = ax.get_gid() or f'panel.{i}'
        view = {'xlim': _floats(ax.get_xlim()), 'xscale': str(ax.get_xscale()),
                'yscale': str(ax.get_yscale())}
        if panel in viewports:
            view['viewport'] = _viewport_record(viewports[panel], ax)
        else:
            view['ylim'] = _floats(ax.get_ylim())
        records[panel + ':view'] = view
        for j, line in enumerate(ax.lines):
            if not line.get_visible():
                continue
            gid = line.get_gid() or f'{panel}.unregistered.line.{j}'
            # A curve stays payload even if its node claims LAYOUT: only a declared guide is
            # decorative geometry, and raw arrays never move under a display translation.
            if _decorative(metadata, gid):
                continue
            records[gid] = {'x': _array(line.get_xdata()), 'y': _array(line.get_ydata())}
        for j, image in enumerate(ax.images):
            if image.get_visible():
                gid = image.get_gid() or f'{panel}.unregistered.image.{j}'
                # Pixels, origin and the scientific window/display range are never layout,
                # whatever the node metadata claims: a mislabelled image must still be caught.
                records[gid] = {'pixels': _array(image.get_array()), 'origin': str(image.origin),
                                'extent': _floats(image.get_extent()),
                                'clim': _floats(image.get_clim())}
        # Error bars, bands and stitched curves are scientific data, never decoration -- only a
        # declared guide has its segments/offsets exempt, and its value array is hashed anyway.
        for j, collection in enumerate(getattr(ax, 'collections', [])):
            if collection.get_visible():
                gid = collection.get_gid() or f'{panel}.unregistered.collection.{j}'
                record = _collection_record(collection, decorative=_decorative(metadata, gid))
                if record is not None:
                    records[gid] = record
        for j, patch in enumerate(getattr(ax, 'patches', [])):
            if patch.get_visible():
                gid = patch.get_gid() or f'{panel}.unregistered.patch.{j}'
                if _decorative(metadata, gid):
                    continue
                records[gid] = _patch_record(patch)
        texts = [ax.xaxis.label, ax.yaxis.label, ax.title, ax._left_title, ax._right_title, *ax.texts]
        legend = ax.get_legend()
        if legend is not None:
            texts.extend(legend.get_texts())
        for j, text in enumerate(texts):
            if text.get_visible() and text.get_text():
                gid = text.get_gid() or f'{panel}.unregistered.text.{j}'
                # Text is scientific content whatever the policy says; rotation is layout.
                records[gid + ':text'] = {'text': str(text.get_text())}
    # 图幅图像（`fig.figimage` 出来的 FigureImage）同样是受保护载荷：像素、origin 与显示
    # 范围（clim）永远是科学解释的一部分，节点被错标成 LAYOUT/guide、或者干脆没有 gid 都不
    # 豁免。位置（ox/oy，图幅像素）是作者允许的版面，由会话的真实显示几何测量，不进这份
    # 载荷；连 `get_extent()` 都不哈希：FigureImage 的那个值是「图幅像素 ±0.5」的伪数据坐标，
    # 拿它当科学窗口等于给版面编一个数据含义。
    for j, image in enumerate(getattr(fig, 'images', [])):
        if not image.get_visible():
            continue
        gid = image.get_gid() or f'figure.unregistered.image.{j}'
        records[gid] = {'pixels': _array(image.get_array()), 'origin': str(image.origin),
                        'clim': _floats(image.get_clim())}
    for j, text in enumerate(fig.texts):
        if text.get_visible() and text.get_text():
            gid = text.get_gid() or f'figure.unregistered.text.{j}'
            records[gid + ':text'] = {'text': str(text.get_text())}
    for j, patch in enumerate(getattr(fig, 'patches', [])):
        if patch.get_visible():
            gid = patch.get_gid() or f'figure.unregistered.patch.{j}'
            if _decorative(metadata, gid):
                continue
            records[gid] = _patch_record(patch)
    source = declarations.get('science', declarations) if isinstance(declarations, dict) else declarations
    if isinstance(source, dict):
        source = {k: v for k, v in source.items() if k not in LAYOUT_KEYS}
    result = {'objects': records, 'declarations': source or {}}
    result['digest'] = _digest(result)
    return result


def compare_science(before, after, *, label=''):
    """Diagnostics for protected-payload differences. Missing either side is UNVERIFIED."""
    if not isinstance(before, dict) or not isinstance(after, dict) \
            or not before.get('digest') or not after.get('digest'):
        return [{'rule_id': 'SCIENCE_UNVERIFIED', 'severity': 'blocker', 'object_ids': [],
                 'message': f'Protected scientific payload could not be captured on both sides{label}'
                            ' — refusing to claim invariance'}]
    if before['digest'] == after['digest']:
        return []
    a, b = before.get('objects', {}), after.get('objects', {})
    changed = [key for key in sorted(set(a) | set(b)) if a.get(key) != b.get(key)]
    if before.get('declarations') != after.get('declarations'):
        changed.append('science_manifest')
    return [{'rule_id': 'SCIENCE_CHANGED', 'severity': 'blocker', 'object_ids': changed,
             'message': f'Protected scientific payload differs from the baseline{label}'}]
