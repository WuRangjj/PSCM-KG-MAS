import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(14, 10))
ax.set_xlim(0, 14)
ax.set_ylim(0, 10)
ax.axis('off')

colors = {
    'user': '#FFF3E0',
    'planner': '#E3F2FD',
    'miner': '#E8F5E9',
    'scientist': '#FFF8E1',
    'critic': '#FCE4EC',
    'editor': '#F3E5F5',
    'neo4j': '#ECEFF1',
    'output': '#E0F7FA',
    'arrow': '#555555'
}

def draw_box(x, y, width, height, text, subtext='', color='#FFFFFF', fontsize=11, subfontsize=8):
    box = FancyBboxPatch((x - width/2, y - height/2), width, height,
                         boxstyle="round,pad=0.15",
                         facecolor=color, edgecolor='#444444', linewidth=1.5)
    ax.add_patch(box)
    ax.text(x, y + 0.08, text, ha='center', va='center', fontsize=fontsize, fontweight='bold')
    if subtext:
        ax.text(x, y - 0.25, subtext, ha='center', va='center', fontsize=subfontsize, color='#666666')

def draw_arrow(x1, y1, x2, y2, label='', label_pos='right'):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='->', lw=1.8, color=colors['arrow']))
    if label:
        offset = 0.35 if label_pos == 'right' else -0.35
        ax.text((x1 + x2)/2 + offset, (y1 + y2)/2, label,
                ha='center', va='center', fontsize=9, color='#555555', style='italic')

ax.text(7, 9.6, 'Multi-Agent System Architecture', ha='center', va='center', fontsize=16, fontweight='bold')

draw_box(7, 8.8, 2.6, 0.8, 'User Input', 'Natural Language', colors['user'])

agents = [
    (7, 7.4, 2.8, 0.9, 'Planner', 'Task Planning', colors['planner']),
    (7, 6.0, 2.8, 0.9, 'KG-Miner', 'Cypher Query', colors['miner']),
    (7, 4.6, 2.8, 0.9, 'Scientist', 'Evidence Reasoning', colors['scientist']),
    (7, 3.2, 2.8, 0.9, 'Critic', 'Review & Verify', colors['critic']),
    (7, 1.8, 2.8, 0.9, 'Editor', 'Report Generation', colors['editor'])
]

for x, y, w, h, name, desc, color in agents:
    draw_box(x, y, w, h, name, desc, color)

draw_box(10.5, 6.0, 2.8, 1.2, 'Neo4j', '6,674 nodes · 12,261 rels', colors['neo4j'])

draw_box(7, 0.4, 3.0, 0.9, 'Structured Report', 'Evidence & Verification', colors['output'])

draw_arrow(7, 8.4, 7, 7.85)
draw_arrow(7, 6.95, 7, 6.45)
draw_arrow(7, 5.55, 7, 5.05)
draw_arrow(7, 4.15, 7, 3.65)
draw_arrow(7, 2.75, 7, 2.25)
draw_arrow(7, 1.35, 7, 0.85)

ax.annotate('', xy=(9.1, 6.0), xytext=(8.4, 6.0),
            arrowprops=dict(arrowstyle='->', lw=1.8, color=colors['arrow']))
ax.annotate('', xy=(8.4, 5.6), xytext=(9.1, 5.6),
            arrowprops=dict(arrowstyle='->', lw=1.8, color=colors['arrow']))
ax.text(8.75, 6.2, 'Query', ha='center', va='center', fontsize=9, color='#555555')
ax.text(8.75, 5.4, 'Evidence', ha='center', va='center', fontsize=9, color='#555555')

boundary = FancyBboxPatch((0.3, 0.1), 13.4, 9.3,
                          boxstyle="round,pad=0.1",
                          facecolor='none', edgecolor='#AAAAAA', linewidth=1.5, linestyle='--')
ax.add_patch(boundary)
ax.text(0.6, 9.2, 'Perovskite Materials Multi-Agent System', ha='left', va='center', fontsize=10, color='#888888')

plt.tight_layout()
plt.savefig('system_architecture.png', dpi=300, bbox_inches='tight', facecolor='white')
print("✅ Architecture diagram saved as system_architecture.png")
plt.show()