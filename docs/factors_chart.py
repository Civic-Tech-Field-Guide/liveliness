"""
Draws docs/factors.png, the most points each factor can add to a score.

The numbers are read from the package, so rerun this after changing a weight:

    pip install matplotlib
    python docs/factors_chart.py

Space Grotesk is used if it is installed, and the default font otherwise.
"""
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.patches import Rectangle

from liveliness import core

now = datetime.now(timezone.utc)
dated_max = core.recency_base_score(now, now)
page_max = core.page_recency_score(now, now)
social_max = core.social_recency_score(now, now)

factors = [
    ("Newest dated activity", dated_max,
     f"Only the single best of: GitHub, blog, news page ({dated_max}),\n"
     f"the site's own dates ({page_max}), a social post ({social_max})"),
    ("Website responding", core.WEBSITE_ALIVE_BONUS,
     f"(Only {core.WEBSITE_ALIVE_BONUS_STALE} if nothing dated in the last year)"),
    ("Social accounts reachable", core.SOCIAL_REACHABLE_BONUS_MAX,
     f"10 per account, capped at {core.SOCIAL_REACHABLE_BONUS_MAX}"),
    ("Issues being closed", core.ISSUE_RESOLUTION_BONUS,
     f"Half or more of recent issues resolved"),
]

if any("Space Grotesk" in f.name for f in font_manager.fontManager.ttflist):
    plt.rcParams["font.family"] = "Space Grotesk"

colors = ["#574FD9", "#01B583", "#7A7FF0", "#E8A23B"]
ink, soft, page = "#19191E", "#6B6B68", "#FBFBFB"

fig = plt.figure(figsize=(10, 5.6), dpi=200)
fig.patch.set_facecolor(page)
ax = fig.add_axes([0.03, 0.17, 0.42, 0.64])
wedges, _ = ax.pie([v for _, v, _ in factors], colors=colors, startangle=90,
                   counterclock=False, wedgeprops=dict(linewidth=0))
ax.set_aspect("equal")
# Dividers drawn as radial lines from the exact centre. Wedge outlines are
# closed paths with mitred corners, and at the centre point those corners
# overshoot into a spike.
for w in wedges:
    a = np.deg2rad(w.theta1)
    ax.plot([0, 1.02 * np.cos(a)], [0, 1.02 * np.sin(a)], color=page,
            lw=2.5, solid_capstyle="round", zorder=3)
ax.text(0.33, -0.25, f"+{dated_max}", ha="center", va="center", fontsize=20,
        fontweight="semibold", color="white")

y = 0.76
for (name, v, note), c in zip(factors, colors):
    fig.patches.append(Rectangle((0.52, y - 0.012), 0.018, 0.032, color=c,
                                 transform=fig.transFigure, figure=fig))
    fig.text(0.55, y, f"+{v}", fontsize=13, fontweight="semibold", color=ink, va="center")
    fig.text(0.605, y, name, fontsize=13, fontweight="semibold", color=ink, va="center")
    fig.text(0.605, y - 0.035, note, fontsize=9.5, color=soft, va="top", linespacing=1.4)
    y -= 0.155

fig.text(0.04, 0.93, "Behind the CTFG Liveliness Score", fontsize=17,
         fontweight="semibold", color=ink)
fig.text(0.04, 0.88, "Here are each of the factors that make up the score, "
         "which is capped at 100.", fontsize=10.5, color=soft)
fig.text(0.04, 0.04,
         f"Penalizing factors: site down or domain gone −50, "
         f"stale link −{core.RELINK_PENALTY}, "
         f"issues ignored −{core.ISSUE_RESOLUTION_PENALTY},\n"
         f"archived repo capped at 15, archive snapshot or page saying it closed "
         f"capped at {core.CLOSED_CAP}.\n"
         f"Minimum scores: recent launch {core.RECENT_LAUNCH_SCORE}, "
         f"current footer copyright {core.COPYRIGHT_FRESH_FLOOR}.",
         fontsize=8.5, color=soft, linespacing=1.5)
fig.savefig(Path(__file__).with_name("factors.png"), facecolor=page)
