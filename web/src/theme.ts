import { createTheme } from "@mui/material/styles";

// Tokens semánticos reactivos al modo (claro/oscuro) vía CSS vars de MUI.
// EDGE  = azul de acción (primary)
// MARK  = acento verde (secondary)
export const EDGE = "var(--mui-palette-primary-main)";
export const EDGE_SOFT = "rgb(var(--mui-palette-primary-mainChannel) / 0.09)";
export const EDGE_DARK = "var(--mui-palette-primary-dark)";
export const MARK = "var(--mui-palette-secondary-main)";
export const MARK_SOFT = "rgb(var(--mui-palette-secondary-mainChannel) / 0.14)";
export const SURFACE = "var(--mui-palette-background-default)";
export const SURFACE_2 = "var(--mui-palette-background-paper)";
export const CARD = "var(--mui-palette-background-paper)";
export const INK = "var(--mui-palette-text-primary)";
export const MUTED = "var(--mui-palette-text-secondary)";
export const RAIL = "var(--mui-palette-divider)";
export const ON_ACCENT = "var(--mui-palette-secondary-contrastText)";
export const SUCCESS = "var(--mui-palette-success-main)";
export const SIDEBAR_BG = "#0B0E14";
export const SIDEBAR_WIDTH = 256;
export const SIDEBAR_TEXT = "rgba(255,255,255,0.6)";
export const SIDEBAR_TEXT_ACTIVE = "#fff";
export const SIDEBAR_HOVER = "rgba(255,255,255,0.08)";
export const SIDEBAR_SELECTED = "rgba(0,255,136,0.12)";
export const SIDEBAR_DISABLED = "rgba(255,255,255,0.25)";
export const MONO = '"Fragment Mono", "Roboto Mono", ui-monospace, monospace';
export const SANS = '"Inter", "Roboto", system-ui, sans-serif';

export const theme = createTheme({
  cssVariables: { colorSchemeSelector: "class" },
  defaultColorScheme: "dark",
  colorSchemes: {
    dark: {
      palette: {
        mode: "dark",
        primary: { main: "#1E90FF", light: "#63B6FF", dark: "#0E66C8", contrastText: "#051220" },
        secondary: { main: "#00FF88", light: "#7BFFC2", dark: "#00C869", contrastText: "#04240F" },
        background: { default: "#0E1013", paper: "#171A1F" },
        text: { primary: "#F2F4F8", secondary: "#98A0AE" },
        divider: "#262B33",
        error: { main: "#FF5D63" },
        success: { main: "#28E08A" },
      },
    },
    light: {
      palette: {
        mode: "light",
        primary: { main: "#1E90FF", light: "#63B6FF", dark: "#0C66C9", contrastText: "#fff" },
        secondary: { main: "#00C869", light: "#4DF59A", dark: "#009952", contrastText: "#04240F" },
        background: { default: "#F5F3EE", paper: "#FFFFFF" },
        text: { primary: "#14161A", secondary: "#69707C" },
        divider: "#D6DBE2",
        error: { main: "#C43D3D" },
        success: { main: "#1E7A46" },
      },
    },
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
        body: { WebkitFontSmoothing: "antialiased" },
        "::selection": { background: MARK, color: INK },
        mark: { background: MARK, color: INK, padding: "0 3px", borderRadius: 2 },
        "*:focus-visible": {
          outline: `2px solid ${EDGE}`,
          outlineOffset: 2,
          borderRadius: 3,
        },
        "@media (prefers-reduced-motion: reduce)": {
          "*, *::before, *::after": {
            animationDuration: "0.01ms !important",
            animationIterationCount: "1 !important",
            transitionDuration: "0.01ms !important",
            scrollBehavior: "auto !important",
          },
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
          boxShadow: "0 1px 3px rgba(0,0,0,.35)",
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
          color: SIDEBAR_TEXT,
          "&:hover": {
            backgroundColor: SIDEBAR_HOVER,
            color: SIDEBAR_TEXT_ACTIVE,
          },
          "&.Mui-selected": {
            backgroundColor: SIDEBAR_SELECTED,
            borderLeftColor: MARK,
            color: SIDEBAR_TEXT_ACTIVE,
            "&:hover": { backgroundColor: "rgba(0,255,136,0.18)" },
          },
          "&.Mui-disabled": {
            color: SIDEBAR_DISABLED,
          },
        },
      },
    },
    MuiListItemText: {
      styleOverrides: {
        primary: { color: "inherit" },
        secondary: { color: SIDEBAR_TEXT },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          border: `1px solid ${RAIL}`,
          borderRadius: 3,
          boxShadow: "0 1px 2px rgba(0,0,0,.12), 0 4px 12px -4px rgba(0,0,0,.28)",
          transition: "box-shadow 0.2s ease, transform 0.15s ease",
          "&:hover": {
            boxShadow: "0 2px 4px rgba(0,0,0,.16), 0 8px 24px -8px rgba(0,0,0,.4)",
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
          background: EDGE,
          color: "var(--mui-palette-primary-contrastText)",
          "&:hover": {
            background: EDGE_DARK,
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
          "&.MuiAlert-standardError": {
            backgroundColor: "rgb(var(--mui-palette-error-mainChannel) / 0.1)",
          },
          "&.MuiAlert-standardInfo": {
            backgroundColor: "rgb(var(--mui-palette-primary-mainChannel) / 0.1)",
          },
          "&.MuiAlert-standardSuccess": {
            backgroundColor: "rgb(var(--mui-palette-success-mainChannel) / 0.1)",
          },
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