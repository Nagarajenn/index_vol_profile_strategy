import { createTheme } from "@mui/material/styles";

// Bloomberg-terminal-inspired: near-black background, blue accents, high
// information density. Dark mode only for V1 -- no light-mode variant.
export const darkTheme = createTheme({
  palette: {
    mode: "dark",
    background: {
      default: "#0a0e14",
      paper: "#11161f",
    },
    primary: {
      main: "#4da3ff",
    },
    secondary: {
      main: "#7fd858",
    },
    error: {
      main: "#ff5c5c",
    },
    text: {
      primary: "#e6edf3",
      secondary: "#8b98a9",
    },
    divider: "#1f2733",
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
          border: "1px solid #1f2733",
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundColor: "#0d1117",
          borderBottom: "1px solid #1f2733",
        },
      },
    },
  },
});
