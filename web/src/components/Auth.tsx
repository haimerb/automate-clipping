import { Fragment, useState } from "react";
import type { FormEvent } from "react";
import { Alert, Box, Button, Card, Container, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import { login, register } from "../api";
import type { User } from "../api";
import { MARK } from "../theme";

interface Props {
  onAuth: (user: User) => void;
}

type Mode = "login" | "register";

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
    <Container maxWidth="lg" sx={{ py: 8 }}>
      <Typography variant="overline" sx={{ display: "block" }}>
        edgetape — clipping automático
      </Typography>
      <Typography variant="h3" sx={{ mt: 1, maxWidth: "14ch" }}>
        Tu carrete, <span style={{ textDecoration: "underline", textDecorationColor: "#FFC647" }}>tu cuenta</span>.
      </Typography>
      <Typography variant="body1" color="text.secondary" sx={{ mt: 1.5, maxWidth: "52ch" }}>
        Inicia sesión para procesar videos, elegir qué clips publicar y llevar el control de
        ganancias por plataforma.
      </Typography>

      <Stack direction="row" spacing={2} sx={{ mt: 3, alignItems: "center" }}>
        {["INGEST", "DETECT", "CUT", "POST"].map((stage, i) => (
          <Fragment key={stage}>
            {i > 0 && <Box aria-hidden sx={{ width: 22, height: 1, bgcolor: "divider" }} />}
            <Typography
              sx={{
                fontFamily: "'Fragment Mono', monospace",
                fontSize: "0.6rem",
                letterSpacing: "0.18em",
                color: i === 0 ? MARK : "text.secondary",
                textTransform: "uppercase",
              }}
            >
              {stage}
            </Typography>
          </Fragment>
        ))}
      </Stack>

      <Card sx={{ maxWidth: 420, mt: 5, p: 3 }}>
        <Tabs value={mode} onChange={(_, v) => switchMode(v as Mode)} sx={{ borderBottom: 1, borderColor: "divider" }}>
          <Tab value="login" label="Ingresar" sx={{ flex: 1 }} />
          <Tab value="register" label="Crear cuenta" sx={{ flex: 1 }} />
        </Tabs>

        <Box component="form" onSubmit={onSubmit} sx={{ mt: 3, display: "flex", flexDirection: "column", gap: 2 }}>
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
            {busy ? "Espera…" : mode === "login" ? "Entrar" : "Crear cuenta"}
          </Button>
        </Box>
      </Card>
    </Container>
  );
}
