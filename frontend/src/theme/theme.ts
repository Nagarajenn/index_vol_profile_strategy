import { createTheme } from "@mui/material/styles";

// Bloomberg-terminal-inspired density, pale/light backdrop: black text on a
// half-white page with white cards for subtle elevation. Red/green (error /
// success) are left as the app's existing semantic colors.
export const appTheme = createTheme({
  palette: {
    mode: "light",
    background: {
      default: "#f1efea",
      paper: "#ffffff",
    },
    primary: {
      main: "#2f6fb3",
    },
    secondary: {
      main: "#7fd858",
    },
    error: {
      main: "#ff5c5c",
    },
    text: {
      primary: "#1a1a1a",
      secondary: "#5c6470",
    },
    divider: "#dedad0",
  },
  typography: {
    fontFamily: '"Inter", "Segoe UI", Roboto, sans-serif',
    fontSize: 13,
    h6: { fontWeight: 600 },
    body2: { fontSize: "0.8rem" },
  },
  shape: {
    borderRadius: 4,
  },
  components: {
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          border: "1px solid #dedad0",
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: "#ffffff",
          borderBottom: "1px solid #dedad0",
          color: "#1a1a1a",
        },
      },
    },
  },
});
