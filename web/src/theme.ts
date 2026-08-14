import { createTheme } from "@mui/material/styles";

export const EDGE = "#1E3A8A";
export const MARK = "#FFC647";
export const SURFACE = "#F1F3F5";
export const CARD = "#FFFFFF";
export const INK = "#14161A";
export const MUTED = "#69707C";
export const RAIL = "#D6DBE2";
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
  },
  shape: { borderRadius: 2 },
  typography: {
    fontFamily: SANS,
    button: {
      fontFamily: MONO,
      fontSize: "0.72rem",
      fontWeight: 400,
      letterSpacing: "0.08em",
      textTransform: "uppercase",
    },
    overline: {
      fontFamily: MONO,
      fontSize: "0.66rem",
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
        body: { WebkitFontSmoothing: "antialiased" },
        "::selection": { background: MARK, color: INK },
        mark: { background: MARK, color: INK, padding: "0 3px" },
        "*:focus-visible": {
          outline: `2px solid ${MARK}`,
          outlineOffset: 2,
          borderRadius: 2,
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: SURFACE,
          color: INK,
          boxShadow: "none",
          borderBottom: `1px solid ${RAIL}`,
        },
      },
    },
    MuiToolbar: {
      styleOverrides: { root: { minHeight: 56 } },
    },
    MuiCard: {
      styleOverrides: { root: { border: `1px solid ${RAIL}`, boxShadow: "none" } },
    },
    MuiPaper: {
      styleOverrides: { root: { backgroundImage: "none" } },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 2 },
        contained: {
          "&:hover": {
            boxShadow: "0 10px 24px -16px rgba(30,58,138,.55)",
          },
        },
        outlined: { "&:hover": { borderColor: EDGE } },
      },
    },
    MuiIconButton: {
      styleOverrides: { root: { borderRadius: 2 } },
    },
    MuiChip: {
      styleOverrides: { root: { borderRadius: 2 } },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          fontFamily: MONO,
          fontSize: "0.72rem",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
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
    MuiTableCell: {
      styleOverrides: {
        head: {
          fontFamily: MONO,
          fontSize: "0.66rem",
          letterSpacing: "0.12em",
          textTransform: "uppercase",
        },
      },
    },
    MuiDialog: {
      styleOverrides: { paper: { border: `1px solid ${RAIL}` } },
    },
  },
});
