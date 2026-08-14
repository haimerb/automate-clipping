import { useEffect, useState } from "react";
import {
  AppBar,
  Box,
  Button,
  Container,
  Toolbar,
  Typography,
} from "@mui/material";
import Upload from "./components/Upload";
import Reel from "./components/Reel";
import Dashboard from "./components/Dashboard";
import Accounts from "./components/Accounts";
import Publish from "./components/Publish";
import Auth from "./components/Auth";
import { getClips, getJob, getMe, getToken, setToken } from "./api";
import type { Clip, Job, User } from "./api";
import { CARD, EDGE, MARK } from "./theme";

type Phase = "upload" | "reel" | "publish" | "accounts" | "dashboard";

interface NavItem {
  label: string;
  phase: Phase;
  needsJob?: boolean;
  needsSelection?: boolean;
}

const NAV: NavItem[] = [
  { label: "01 · INGRESAR", phase: "upload" },
  { label: "02 · CLIPS", phase: "reel", needsJob: true },
  { label: "03 · PUBLICAR", phase: "publish", needsJob: true, needsSelection: true },
  { label: "04 · CUENTAS", phase: "accounts" },
  { label: "05 · GANANCIAS", phase: "dashboard" },
];

function NavButton({
  item,
  active,
  disabled,
  onClick,
}: {
  item: NavItem;
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      color="inherit"
      disabled={disabled}
      onClick={onClick}
      sx={{
        color: disabled ? "text.disabled" : active ? "text.primary" : "text.secondary",
        px: 0.75,
        minWidth: 0,
        borderBottom: active ? `2px solid ${MARK}` : "2px solid transparent",
        borderRadius: 0,
        "&:hover": { color: "text.primary", background: "transparent" },
        "&:disabled": { opacity: 0.35 },
      }}
    >
      {item.label}
    </Button>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [phase, setPhase] = useState<Phase>("upload");
  const [job, setJob] = useState<Job | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);

  useEffect(() => {
    if (!getToken()) return;
    getMe()
      .then(setUser)
      .catch(() => setToken(null));
  }, []);

  useEffect(() => {
    const onUnauthorized = () => setUser(null);
    window.addEventListener("edgetape:unauthorized", onUnauthorized);
    return () => window.removeEventListener("edgetape:unauthorized", onUnauthorized);
  }, []);

  function handleAuth(next: User) {
    setUser(next);
    goTo("upload");
  }

  function logout() {
    setToken(null);
    setUser(null);
    setJob(null);
    setClips([]);
    goTo("upload");
  }

  async function handleReady(finished: Job) {
    const found = await getClips(finished.id);
    setClips(found);
    setJob(finished);
    setPhase("reel");
    window.scrollTo({ top: 0 });
  }

  async function openJob(jobId: string) {
    const found = await getJob(jobId);
    if (found.status !== "done") {
      window.alert("Este video aún no está listo para ver clips.");
      return;
    }
    await handleReady(found);
  }

  function goTo(p: Phase) {
    setPhase(p);
    window.scrollTo({ top: 0 });
  }

  function handleReset() {
    setJob(null);
    setClips([]);
    goTo("upload");
  }

  function updateClip(updated: Clip) {
    setClips((prev) => prev.map((c) => (c.id === updated.id ? updated : c)));
  }

  if (!user) {
    return (
      <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
        <AppBar position="sticky">
          <Toolbar>
            <Typography
              sx={{ fontFamily: "'Fragment Mono', monospace", letterSpacing: "0.02em" }}
            >
              edgetape<span style={{ color: EDGE }}>.</span>
            </Typography>
          </Toolbar>
        </AppBar>
        <Auth onAuth={handleAuth} />
      </Box>
    );
  }

  const toPublish = clips.filter((c) => c.publish).length;

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column" }}>
      <AppBar position="sticky">
        <Container maxWidth="lg">
          <Toolbar disableGutters sx={{ gap: 3, flexWrap: "wrap", py: 0.5 }}>
            <Button
              color="inherit"
              onClick={() => goTo("upload")}
              sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "1rem", p: 0, minWidth: 0 }}
            >
              edgetape<span style={{ color: EDGE }}>.</span>
            </Button>
            <Box sx={{ display: "flex", gap: 1, flex: 1 }}>
              {NAV.map((item) => {
                const disabled =
                  (item.needsJob && !job) ||
                  (item.needsSelection && (!job || toPublish === 0));
                return (
                  <NavButton
                    key={item.phase}
                    item={item}
                    active={phase === item.phase}
                    disabled={disabled}
                    onClick={() => goTo(item.phase)}
                  />
                );
              })}
            </Box>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1.5 }}>
              <Typography variant="body2" sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.72rem" }}>
                {user.name}
              </Typography>
              <Button variant="outlined" size="small" onClick={logout} sx={{ borderColor: "divider" }}>
                salir
              </Button>
            </Box>
          </Toolbar>
        </Container>
      </AppBar>

      {phase === "upload" && <Upload onReady={(j) => void handleReady(j)} onOpenJob={openJob} />}
      {phase === "reel" && job && (
        <Reel
          job={job}
          clips={clips}
          onUpdateClip={updateClip}
          onGoPublish={() => goTo("publish")}
          onReset={handleReset}
          onDashboard={() => goTo("dashboard")}
        />
      )}
      {phase === "publish" && job && (
        <Publish
          job={job}
          clips={clips}
          onUpdateClip={updateClip}
          onBack={() => goTo("reel")}
          onJobChange={setJob}
        />
      )}
      {phase === "accounts" && <Accounts />}
      {phase === "dashboard" && (
        <Dashboard onNewJob={() => goTo("upload")} onOpenJob={(j) => void openJob(j.id)} />
      )}

      <Box
        component="footer"
        sx={{
          mt: "auto",
          borderTop: "1px solid",
          borderColor: "divider",
          background: CARD,
        }}
      >
        <Container maxWidth="lg">
          <Toolbar disableGutters sx={{ gap: 2, flexWrap: "wrap", py: 1 }}>
            <Typography
              sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.78rem" }}
            >
              edgetape<span style={{ color: EDGE }}>.</span>
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ ml: "auto" }}>
              Grabaciones largas → los momentos que importan.
            </Typography>
          </Toolbar>
        </Container>
      </Box>
    </Box>
  );
}
