import { createTheme } from "@mui/material/styles";

export const EDGE = "#1E3A8A";
export const EDGE_SOFT = "rgba(30,58,138,0.06)";
export const EDGE_DARK = "#162D6B";
export const MARK = "#FFC647";
export const MARK_SOFT = "rgba(255,198,71,0.12)";
export const SURFACE = "#F1F3F5";
export const SURFACE_2 = "#E9EDF1";
export const CARD = "#FFFFFF";
export const INK = "#14161A";
export const MUTED = "#69707C";
export const RAIL = "#D6DBE2";
export const SIDEBAR_BG = "#0F172A";
export const SIDEBAR_WIDTH = 256;
export const MONO = '"Fragment Mono", ui-monospace, monospace';
export const SANS = '"Hanken Grotesk", system-ui, sans-serif';

export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: EDGE },
    secondary: { main: MARK },
    background: { default: SURFACE, paper: CARD },
    text: { primary: INK, secondary: MUTED },
    divider: RAIL,
    error: { main: "#C43D3D" },
    success: { main: "#1E7A46" },
  },
  shape: { borderRadius: 3 },
  typography: {
    fontFamily: SANS,
    button: {
      fontFamily: MONO,
      fontSize: "0.68rem",
      fontWeight: 500,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
    },
    overline: {
      fontFamily: MONO,
      fontSize: "0.62rem",
      fontWeight: 400,
      letterSpacing: "0.14em",
      textTransform: "uppercase",
      color: MUTED,
    },
    h3: { fontWeight: 700, letterSpacing: "-0.02em", lineHeight: 1.1 },
    h4: { fontWeight: 700, letterSpacing: "-0.02em" },
    h5: { fontWeight: 700, letterSpacing: "-0.01em" },
    h6: { fontWeight: 600, letterSpacing: "-0.01em" },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: { WebkitFontSmoothing: "antialiased", background: SURFACE },
        "::selection": { background: MARK, color: INK },
        mark: { background: MARK, color: INK, padding: "0 3px", borderRadius: 2 },
        "*:focus-visible": {
          outline: `2px solid ${EDGE}`,
          outlineOffset: 2,
          borderRadius: 3,
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          border: `1px solid ${RAIL}`,
          borderRadius: 3,
        },
        rounded: { borderRadius: 3 },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: CARD,
          color: INK,
          boxShadow: "0 1px 3px rgba(20,22,26,.06)",
          borderBottom: `1px solid ${RAIL}`,
        },
      },
    },
    MuiToolbar: {
      styleOverrides: { root: { minHeight: 60 } },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: SIDEBAR_BG,
          borderRight: "none",
          backgroundImage: "none",
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 3,
          borderLeft: "3px solid transparent",
          color: "rgba(255,255,255,0.6)",
          "&:hover": {
            backgroundColor: "rgba(255,255,255,0.08)",
            color: "#fff",
          },
          "&.Mui-selected": {
            backgroundColor: "rgba(255,198,71,0.12)",
            borderLeftColor: MARK,
            color: "#fff",
            "&:hover": { backgroundColor: "rgba(255,198,71,0.18)" },
          },
          "&.Mui-disabled": {
            color: "rgba(255,255,255,0.25)",
          },
        },
      },
    },
    MuiListItemText: {
      styleOverrides: {
        primary: { color: "inherit" },
        secondary: { color: "rgba(255,255,255,0.45)" },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          border: `1px solid ${RAIL}`,
          borderRadius: 3,
          boxShadow: "0 1px 2px rgba(20,22,26,.04), 0 4px 12px -4px rgba(20,22,26,.08)",
          transition: "box-shadow 0.2s ease, transform 0.15s ease",
          "&:hover": {
            boxShadow: "0 2px 4px rgba(20,22,26,.06), 0 8px 24px -8px rgba(20,22,26,.12)",
          },
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: {
          borderRadius: 3,
          fontWeight: 600,
          fontFamily: MONO,
          fontSize: "0.78rem",
          letterSpacing: "0.04em",
          textTransform: "none" as const,
        },
        contained: {
          background: INK,
          color: "#fff",
          "&:hover": {
            background: EDGE,
          },
        },
        outlined: {
          borderColor: RAIL,
          "&:hover": { borderColor: EDGE, backgroundColor: EDGE_SOFT },
        },
        sizeSmall: { fontSize: "0.62rem" },
      },
    },
    MuiIconButton: {
      styleOverrides: { root: { borderRadius: 3 } },
    },
    MuiChip: {
      styleOverrides: {
        root: { borderRadius: 3, fontWeight: 500 },
        sizeSmall: { fontSize: "0.62rem" },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          fontFamily: MONO,
          fontSize: "0.68rem",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          minHeight: 44,
        },
      },
    },
    MuiTabs: {
      styleOverrides: { indicator: { backgroundColor: MARK, height: 2, borderRadius: 1 } },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { backgroundColor: RAIL, borderRadius: 2 },
        bar: { backgroundColor: MARK, borderRadius: 2 },
      },
    },
    MuiTextField: {
      defaultProps: { size: "small" },
      styleOverrides: {
        root: {
          "& .MuiOutlinedInput-root": {
            borderRadius: 3,
            "&.Mui-focused fieldset": { borderColor: EDGE },
          },
        },
      },
    },
    MuiTableCell: {
      styleOverrides: {
        head: {
          fontFamily: MONO,
          fontSize: "0.6rem",
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: MUTED,
          borderBottom: `1px solid ${RAIL}`,
          fontWeight: 600,
        },
        body: { borderBottom: `1px dashed ${RAIL}`, fontSize: "0.84rem" },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: { "&:hover": { backgroundColor: EDGE_SOFT } },
      },
    },
    MuiDialog: {
      styleOverrides: { paper: { border: `1px solid ${RAIL}`, borderRadius: 12 } },
    },
    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: 3,
          "&.MuiAlert-standardError": { backgroundColor: "rgba(196,61,61,.08)" },
          "&.MuiAlert-standardInfo": { backgroundColor: EDGE_SOFT },
          "&.MuiAlert-standardSuccess": { backgroundColor: "rgba(30,122,70,.08)" },
        },
      },
    },
    MuiDivider: { styleOverrides: { root: { borderColor: RAIL } } },
    MuiSelect: {
      styleOverrides: {
        root: { borderRadius: 3 },
      },
    },
  },
});
