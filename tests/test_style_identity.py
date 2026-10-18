"""Consumer-visible identity isolation and fail-closed matching."""
import copy

import matplotlib.pyplot as plt
import pytest

from figpact.style_identity import inventory, resolve


def test_layout_redraw_and_axes_reordering_do_not_retarget():
    fig, axes = plt.subplots(2, sharex=True, layout='constrained')
    try:
        axes[0].plot([0, 1, 2], [1, 2, 3], label='top')
        axes[1].plot([0, 1, 2], [3, 1, 2], label='bottom')
        axes[0].set_ylabel('Response')
        targets = inventory(fig)
        label = next(t for t in targets if t['role'] == 'axis.title')
        tick = next(t for t in targets if t['role'] == 'axis.tick'
                    and t['display']['axes_index'] == 0 and t['selector']['axis'] == 'y')
        assert not any(t['role'] == 'axis.tick' and t['display']['axes_index'] == 0
                       and t['selector']['axis'] == 'x' for t in targets)
        for _ in range(3):
            fig.canvas.draw()
            assert resolve(fig, label) == [axes[0].yaxis.label]
            assert set(resolve(fig, tick)) == set(axes[0].get_yticklabels())
        axes[0].yaxis.label.set_fontsize(8)
        assert resolve(fig, label) == [axes[0].yaxis.label]
    finally:
        plt.close(fig)


def test_duplicate_curve_and_missing_target_are_rejected():
    fig, ax = plt.subplots()
    try:
        line, = ax.plot([0, 1], [1, 2], label='data')
        target = next(t for t in inventory(fig) if t['role'] == 'curve.linewidth')
        ax.plot([0, 1], [1, 2], label='data')
        assert all(not t['eligible'] for t in inventory(fig) if t['role'] == 'curve.linewidth')
        with pytest.raises(ValueError):
            resolve(fig, target)
        ax.lines[1].remove()
        line.remove()
        with pytest.raises(ValueError):
            resolve(fig, target)
    finally:
        plt.close(fig)


def test_errorbar_data_curve_is_only_editable_line_and_descriptors_are_closed():
    fig, ax = plt.subplots()
    try:
        container = ax.errorbar([0, 1, 2], [1, 2, 3], yerr=[.1, .2, .3],
                                fmt='-o', capsize=4)
        ax.plot([0, 1], [2, 3], linestyle='none', marker='o')
        curves = [t for t in inventory(fig) if t['role'] == 'curve.linewidth']
        assert len(curves) == 1
        assert resolve(fig, curves[0]) == [container.lines[0]]
        forged = copy.deepcopy(curves[0])
        forged['property'] = 'color'
        with pytest.raises(ValueError, match='UNSUPPORTED_PROPERTY'):
            resolve(fig, forged)
        forged = copy.deepcopy(curves[0])
        forged['method'] = 'set_data'
        with pytest.raises(ValueError, match='UNKNOWN_FIELD'):
            resolve(fig, forged)
    finally:
        plt.close(fig)
