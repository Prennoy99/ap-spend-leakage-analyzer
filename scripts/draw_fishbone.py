"""Draws the fishbone (Ishikawa) diagram in docs/09_root_cause_analysis.md as a standalone SVG.

The figures on the bones are copied from that document (computed by src/root_cause.py,
src/process_mining.py and src/kpis.py). Run: python scripts/draw_fishbone.py docs/img/fishbone_paid_too_late.svg
"""
import sys
from html import escape

W, H = 1560, 720
SPINE_Y = 360
HEAD_X = 1300
BLUE, RED, INK, MUTED, BONE = "#2a78d6", "#e34948", "#1f1f1d", "#52514e", "#8a8980"

# (category, [(text, evidenced)]) — top row left to right, then bottom row.
top = [
    ("Method", [("Payment run takes all approved invoices alike", True),
                ("No approval deadline: P90 10 days", True),
                ("10-day discount window, 9.4-day cycle", True)]),
    ("System", [("Payment proposal not sorted by due date", True),
                ("No alert before a discount deadline", False),
                ("Approver can't see remaining budget", False)]),
    ("Input", [("Wrong cost centre: 35% of rejections", True),
               ("Missing PO or receipt: 43% of rejections", True),
               ("Each rework loop adds about 4 days", True)]),
]
bottom = [
    ("Measurement", [("4 control tasks without an Accountable", True),
                     ("Discount capture not tracked as a KPI", False)]),
    ("People", [("Approving is a side job for budget owners", False),
                ("Invoices keyed in by hand", False)]),
    ("Policy", [("No rule to pay 2/10 invoices first", True),
                ("Supplier terms never reviewed", False)]),
]

out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
       'font-family="Helvetica, Arial, sans-serif">',
       f'<rect width="{W}" height="{H}" fill="#ffffff"/>',
       f'<line x1="60" y1="{SPINE_Y}" x2="{HEAD_X}" y2="{SPINE_Y}" stroke="{INK}" stroke-width="4"/>',
       f'<polygon points="{HEAD_X},{SPINE_Y-14} {HEAD_X+18},{SPINE_Y} {HEAD_X},{SPINE_Y+14}" fill="{INK}"/>',
       f'<rect x="{HEAD_X+24}" y="{SPINE_Y-62}" width="210" height="124" rx="10" fill="#fde8e8" stroke="{RED}" stroke-width="2"/>']
for i, line in enumerate(["Invoices paid too late", "for the discount", "or due date", "€13.3k a year · 47% of", "discounts missed"]):
    weight = "700" if i < 3 else "400"
    out.append(f'<text x="{HEAD_X+129}" y="{SPINE_Y-34+i*21}" text-anchor="middle" font-size="{15 if i < 3 else 13}" '
               f'font-weight="{weight}" fill="{INK}">{escape(line)}</text>')

def bone(x_end, category, causes, above):
    # Diagonal bone from the category label down/up to the spine.
    y_label = 60 if above else H - 60
    x_start = x_end - 150
    out.append(f'<line x1="{x_start}" y1="{y_label + (14 if above else -14)}" x2="{x_end}" y2="{SPINE_Y}" '
               f'stroke="{BONE}" stroke-width="2.5"/>')
    out.append(f'<rect x="{x_start-70}" y="{y_label-22 if above else y_label-8}" width="140" height="30" rx="6" fill="#eef4fc" stroke="{BLUE}"/>')
    out.append(f'<text x="{x_start}" y="{y_label-2 if above else y_label+12}" text-anchor="middle" font-size="15" '
               f'font-weight="700" fill="{INK}">{category}</text>')
    for k, (text, evidenced) in enumerate(causes):
        t = (k + 1) / (len(causes) + 1)
        y = (y_label + 14) + ((SPINE_Y - (y_label + 14)) * t) if above else (y_label - 14) + ((SPINE_Y - (y_label - 14)) * t)
        x = x_start + 150 * t
        out.append(f'<line x1="{x-6}" y1="{y:.0f}" x2="{x-26}" y2="{y:.0f}" stroke="{BONE}" stroke-width="1.5"/>')
        mark = "●" if evidenced else "○"
        color = INK if evidenced else MUTED
        out.append(f'<text x="{x-30}" y="{y+4:.0f}" text-anchor="end" font-size="12.5" fill="{color}">'
                   f'{escape(text)} <tspan fill="{BLUE if evidenced else MUTED}">{mark}</tspan></text>')

for n, (cat, causes) in enumerate(top):
    bone(520 + n * 380, cat, causes, above=True)
for n, (cat, causes) in enumerate(bottom):
    bone(520 + n * 380, cat, causes, above=False)

out.append(f'<text x="60" y="{H-14}" font-size="12" fill="{MUTED}">● shown in the data or the Define documents (see docs/09)   '
           '○ hypothesis: not in the extract, to confirm in interviews</text>')
out.append("</svg>")
open(sys.argv[1], "w").write("\n".join(out) + "\n")
