import { Fragment, useState } from "react";
import type { FormEvent } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { login, register } from "../api";
import type { User } from "../api";
import { EDGE, MARK } from "../theme";

interface Props {
  onAuth: (user: User) => void;
}

type Mode = "login" | "register";

const STAGES = ["INGEST", "DETECT", "CUT", "POST"];

export default function Auth({ onAuth }: Props) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const resp =
        mode === "login" ? await login(email, password) : await register(email, password, name);
      onAuth(resp.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Algo salió mal");
    } finally {
      setBusy(false);
    }
  }

  function switchMode(m: Mode) {
    setMode(m);
    setError(null);
  }

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "grid",
        gridTemplateColumns: { xs: "1fr", md: "5fr 6fr" },
      }}
    >
      <Box
        sx={{
          display: { xs: "none", md: "flex" },
          flexDirection: "column",
          justifyContent: "space-between",
          bgcolor: EDGE,
          color: "#fff",
          p: { md: 6, lg: 8 },
        }}
      >
        <Box>
          <Typography
            sx={{
              fontFamily: "'Fragment Mono', monospace",
              fontSize: "1.2rem",
              letterSpacing: "0.02em",
            }}
          >
            edgetape<span style={{ color: MARK }}>.</span>
          </Typography>
        </Box>

        <Box>
          <Typography
            variant="h3"
            sx={{ color: "#fff", maxWidth: "16ch", fontSize: { md: "2.6rem", lg: "3.2rem" } }}
          >
            Tu carrete,{" "}
            <span style={{ background: `linear-gradient(transparent 66%, ${MARK} 66%)`, paddingInline: "0.08em" }}>
              tu cuenta
            </span>
            .
          </Typography>
          <Typography sx={{ mt: 3, color: "#C7D0E8", maxWidth: "46ch", fontSize: "1.02rem" }}>
            Procesa videos, elige qué clips publicar y lleva el control de ganancias por
            plataforma — todo desde un solo panel.
          </Typography>
        </Box>

        <Box>
          <Stack direction="row" spacing={2} sx={{ alignItems: "center", mb: 4 }}>
            {STAGES.map((stage, i) => (
              <Fragment key={stage}>
                {i > 0 && <Box aria-hidden sx={{ width: 22, height: 1, bgcolor: "rgba(255,255,255,.35)" }} />}
                <Typography
                  sx={{
                    fontFamily: "'Fragment Mono', monospace",
                    fontSize: "0.6rem",
                    letterSpacing: "0.18em",
                    color: i === 0 ? MARK : "rgba(255,255,255,.65)",
                  }}
                >
                  {stage}
                </Typography>
              </Fragment>
            ))}
          </Stack>
          <Typography
            sx={{
              fontFamily: "'Fragment Mono', monospace",
              fontSize: "0.62rem",
              letterSpacing: "0.12em",
              color: "rgba(255,255,255,.55)",
            }}
          >
            GRABACIÓN LARGA → MOMENTOS → SHORTS · TIKTOK · REELS
          </Typography>
        </Box>
      </Box>

      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          bgcolor: "background.default",
          p: { xs: 3, md: 8 },
        }}
      >
        <Box sx={{ width: "100%", maxWidth: 420 }}>
          <Box sx={{ mb: 4, display: { xs: "block", md: "none" } }}>
            <Typography
              sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "1.1rem" }}
            >
              edgetape<span style={{ color: EDGE }}>.</span>
            </Typography>
          </Box>
          <Card sx={{ p: 3.5 }}>
            <Tabs
              value={mode}
              onChange={(_, v) => switchMode(v as Mode)}
              sx={{ borderBottom: 1, borderColor: "divider" }}
            >
              <Tab value="login" label="Ingresar" sx={{ flex: 1 }} />
              <Tab value="register" label="Crear cuenta" sx={{ flex: 1 }} />
            </Tabs>

            <Box
              component="form"
              onSubmit={onSubmit}
              sx={{ mt: 3, display: "flex", flexDirection: "column", gap: 2 }}
            >
              {mode === "register" && (
                <TextField
                  label="Nombre"
                  placeholder="Tu nombre"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  autoComplete="name"
                />
              )}
              <TextField
                label="Email"
                type="email"
                placeholder="tucorreo@ejemplo.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
              <TextField
                label="Contraseña"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                required
                slotProps={{ htmlInput: { minLength: 6 } }}
              />
              {error && <Alert severity="error">{error}</Alert>}
              <Button variant="contained" type="submit" disabled={busy} sx={{ mt: 1 }}>
                {busy ? "Espera…" : mode === "login" ? "Entrar al panel" : "Crear cuenta"}
              </Button>
            </Box>
          </Card>
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ mt: 3, display: "block", textAlign: "center", fontFamily: "'Fragment Mono', monospace", fontSize: "0.62rem", letterSpacing: "0.06em" }}
          >
            INGRESAR · CREAR CUENTA — TUS CLIPS, TUS CUENTAS
          </Typography>
        </Box>
      </Box>
    </Box>
  );
}
