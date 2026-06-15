# wallust template for colorschemes/wallust.py (optional).
#
# Add to ~/.config/wallust/wallust.toml under [templates]:
#   ranger-colors = { template = 'ranger-colors.py', target = '~/.cache/wallust/ranger-colors.py' }
# and copy this file to ~/.config/wallust/templates/ranger-colors.py.
# Running rangers pick up a new palette on SIGUSR2 (see ranger-reload).
#
# The rendered file is plain Python, exec'd by the colorscheme.
COLORS = {
    0: "{{color0}}",
    1: "{{color1}}",
    2: "{{color2}}",
    3: "{{color3}}",
    4: "{{color4}}",
    5: "{{color5}}",
    6: "{{color6}}",
    7: "{{color7}}",
    8: "{{color8}}",
}

# Which palette slot (0-15) each UI element uses; None = the colorscheme's
# default (dir 4, link 6, marked 3, tab 7).  "fill" is a "#rrggbb" string for
# a solid cursor bar, or None for the plain reverse-video cursor row.
ROLES = {
    "dir":    None,
    "link":   None,
    "marked": None,
    "tab":    None,
    "fill":   None,
}
