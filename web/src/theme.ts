import { createTheme } from "@mui/material/styles";

export const EDGE = "#1E3A8A";
export const EDGE_SOFT = "rgba(30,58,138,0.06)";
export const MARK = "#FFC647";
export const SURFACE = "#F1F3F5";
export const SURFACE_2 = "#E9EDF1";
export const CARD = "#FFFFFF";
export const INK = "#14161A";
export const MUTED = "#69707C";
export const RAIL = "#D6DBE2";
export const SIDEBAR_WIDTH = 244;
const MONO = '"Fragment Mono", ui-monospace, monospace';
const SANS = '"Hanken Grotesk", system-ui, sans-serif';

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
      fontSize: "0.7rem",
      fontWeight: 400,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
    },
    overline: {
      fontFamily: MONO,
      fontSize: "0.64rem",
      fontWeight: 400,
      letterSpacing: "0.14em",
      textTransform: "uppercase",
      color: MUTED,
    },
    h3: { fontWeight: 700, letterSpacing: "-0.02em", lineHeight: 1.1 },
    h4: { fontWeight: 700, letterSpacing: "-0.02em" },
    h5: { fontWeight: 700, letterSpacing: "-0.01em" },
    h6: { fontWeight: 600 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: { WebkitFontSmoothing: "antialiased", background: SURFACE },
        "::selection": { background: MARK, color: INK },
        mark: { background: MARK, color: INK, padding: "0 3px" },
        "*:focus-visible": {
          outline: `2px solid ${MARK}`,
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
        },
        rounded: { borderRadius: 3 },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: CARD,
          color: INK,
          boxShadow: "none",
          borderBottom: `1px solid ${RAIL}`,
        },
      },
    },
    MuiToolbar: {
      styleOverrides: { root: { minHeight: 56 } },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: CARD,
          borderRight: `1px solid ${RAIL}`,
          backgroundImage: "none",
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 3,
          borderLeft: "2px solid transparent",
          "&.Mui-selected": {
            backgroundColor: EDGE_SOFT,
            borderLeftColor: MARK,
            "&:hover": { backgroundColor: EDGE_SOFT },
          },
          "&:hover": { backgroundColor: EDGE_SOFT },
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          border: `1px solid ${RAIL}`,
          boxShadow: "0 1px 0 rgba(20,22,26,.04), 0 10px 24px -20px rgba(20,22,26,.35)",
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 3 },
        contained: {
          "&:hover": {
            boxShadow: "0 10px 24px -16px rgba(30,58,138,.55)",
          },
        },
        outlined: { "&:hover": { borderColor: EDGE } },
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
          fontSize: "0.7rem",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          minHeight: 44,
        },
      },
    },
    MuiTabs: {
      styleOverrides: { indicator: { backgroundColor: MARK, height: 2 } },
    },
    MuiLinearProgress: {
      styleOverrides: {
        root: { backgroundColor: RAIL },
        bar: { backgroundColor: MARK },
      },
    },
    MuiTextField: {
      defaultProps: { size: "small" },
    },
    MuiTableCell: {
      styleOverrides: {
        head: {
          fontFamily: MONO,
          fontSize: "0.62rem",
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: MUTED,
          borderBottom: `1px solid ${RAIL}`,
        },
        body: { borderBottom: `1px dashed ${RAIL}`, fontSize: "0.86rem" },
      },
    },
    MuiTableRow: {
      styleOverrides: {
        root: { "&:hover": { backgroundColor: EDGE_SOFT } },
      },
    },
    MuiDialog: {
      styleOverrides: { paper: { border: `1px solid ${RAIL}` } },
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
  },
});
