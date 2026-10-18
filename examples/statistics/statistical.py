"""Synthetic means and standard errors; protocol-only figpact integration."""
from pathlib import Path
import matplotlib.pyplot as plt
import yaml
from figpact import GidRegistry

FIGURE_ID = 'statistics'
SCOPES = ('main',)
SCALARS = {
    'canvas_w_mm': (float, 40, 160), 'canvas_h_mm': (float, 40, 140),
    'axis_font_pt': (float, 5, 14), 'tick_font_pt': (float, 5, 14),
    'legend_font_pt': (float, 5, 14), 'line_width': (float, 0.3, 2),
}
CONFIG = {}

def load_config(path):
    return yaml.safe_load(Path(path).read_text(encoding='utf-8'))

def load_science():
    return {'x': [0, 1, 2, 3, 4],
            'control': [1.0, 1.3, 1.6, 1.7, 1.9],
            'treated': [1.0, 1.7, 2.3, 2.8, 3.1],
            'se_control': [0.10, 0.12, 0.15, 0.12, 0.16],
            'se_treated': [0.12, 0.15, 0.18, 0.21, 0.20]}

def science_manifest(science):
    return {'nodes': {}, 'science': {'source': 'synthetic fixed arrays, not measured data', 'values': science}}

def build_scene(science, cfg, scope):
    fig = plt.figure(figsize=(cfg['canvas_w_mm']/25.4, cfg['canvas_h_mm']/25.4), dpi=120)
    ax = fig.add_axes((0.20, 0.19, 0.75, 0.75))
    reg = GidRegistry(scope=scope)
    for name, color in [('control', '#4477AA'), ('treated', '#AA3377')]:
        line, = ax.plot(science['x'], science[name], marker='o', color=color,
                        linewidth=cfg['line_width'], label=name.capitalize())
        reg.register(line, f'statistics.main.{name}', artist_type='Line2D', science_policy='LOCKED_SCIENCE')
        ax.errorbar(science['x'], science[name], yerr=science['se_'+name],
                    fmt='none', color=color, capsize=3, elinewidth=cfg['line_width'])
    ax.set_xlabel('Time (days)', fontsize=cfg['axis_font_pt'])
    ax.set_ylabel('Response (a.u.)', fontsize=cfg['axis_font_pt'])
    ax.tick_params(labelsize=cfg['tick_font_pt'])
    ax.legend(fontsize=cfg['legend_font_pt'], loc='upper left', frameon=False)
    ax.set_xlim(-0.3, 4.3)
    ax.set_ylim(0.5, 3.6)
    return fig, reg

def build_figure_and_registry(scope='main'):
    return build_scene(load_science(), CONFIG, scope)

def layout_contract(scope='main'):
    gids = ['statistics.main.control', 'statistics.main.treated']
    return {'parameters': [],
            'nodes': {gid: {'type': 'Line2D', 'parent': None, 'editable': False,
                            'science_policy': 'LOCKED_SCIENCE'} for gid in gids},
            'groups': [], 'relations': [], 'outputs': ['statistical.png']}

if __name__ == '__main__':
    figure, _ = build_scene(load_science(), load_config(Path(__file__).with_suffix('.yaml')), 'main')
    figure.savefig(Path(__file__).with_suffix('.png'))
    plt.close(figure)
