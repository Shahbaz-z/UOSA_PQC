"""Theme configuration for the application."""

# Color palette
COLORS = {
    "primary": "#3b82f6",      # Blue
    "secondary": "#10b981",    # Green
    "warning": "#f59e0b",      # Amber
    "error": "#ef4444",        # Red
    "background": "#0f172a",   # Slate 900
    "surface": "#1e293b",      # Slate 800
    "text": "#f8fafc",         # Slate 50
    "text_muted": "#94a3b8",   # Slate 400
    "border": "#334155",       # Slate 700
}

# Plotly chart template
PLOTLY_TEMPLATE = {
    "layout": {
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "Inter, system-ui, sans-serif", "color": COLORS["text"]},
        "colorway": [
            COLORS["primary"],
            COLORS["secondary"],
            COLORS["warning"],
            COLORS["error"],
            "#8b5cf6",  # Purple
            "#ec4899",  # Pink
        ],
        "xaxis": {"gridcolor": COLORS["border"], "linecolor": COLORS["border"]},
        "yaxis": {"gridcolor": COLORS["border"], "linecolor": COLORS["border"]},
    }
}

# Global theme settings
THEME = {
    "colors": COLORS,
    "plotly": PLOTLY_TEMPLATE,
    "font_family": "Inter, system-ui, sans-serif",
    "border_radius": "8px",
}
