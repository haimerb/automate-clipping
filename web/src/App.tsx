import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Box,
  Button,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Toolbar,
  Typography,
} from "@mui/material";
import MenuRoundedIcon from "@mui/icons-material/MenuRounded";
import LogoutRoundedIcon from "@mui/icons-material/LogoutRounded";
import UploadFileRoundedIcon from "@mui/icons-material/UploadFileRounded";
import MovieFilterRoundedIcon from "@mui/icons-material/MovieFilterRounded";
import SendRoundedIcon from "@mui/icons-material/SendRounded";
import AccountBoxRoundedIcon from "@mui/icons-material/AccountBoxRounded";
import PaidRoundedIcon from "@mui/icons-material/PaidRounded";
import Upload from "./components/Upload";
import Reel from "./components/Reel";
import Dashboard from "./components/Dashboard";
import Accounts from "./components/Accounts";
import Publish from "./components/Publish";
import Auth from "./components/Auth";
import { getClips, getJob, getMe, getToken, setToken } from "./api";
import type { Clip, Job, User } from "./api";
import { CARD, EDGE, MARK, SIDEBAR_WIDTH } from "./theme";

type Phase = "upload" | "reel" | "publish" | "accounts" | "dashboard";

interface NavItem {
  label: string;
  caption: string;
  phase: Phase;
  icon: ReactNode;
  needsJob?: boolean;
  needsSelection?: boolean;
}

const NAV: NavItem[] = [
  {
    label: "Ingresar",
    caption: "sube o pega un video",
    phase: "upload",
    icon: <UploadFileRoundedIcon fontSize="small" />,
  },
  {
    label: "Clips",
    caption: "el carrete de momentos",
    phase: "reel",
    icon: <MovieFilterRoundedIcon fontSize="small" />,
    needsJob: true,
  },
  {
    label: "Publicar",
    caption: "destinos por clip",
    phase: "publish",
    icon: <SendRoundedIcon fontSize="small" />,
    needsJob: true,
    needsSelection: true,
  },
  {
    label: "Cuentas",
    caption: "canales vinculados",
    phase: "accounts",
    icon: <AccountBoxRoundedIcon fontSize="small" />,
  },
  {
    label: "Ganancias",
    caption: "rendimiento por plataforma",
    phase: "dashboard",
    icon: <PaidRoundedIcon fontSize="small" />,
  },
];

function Brand() {
  return (
    <Typography
      sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "1.05rem", letterSpacing: "0.02em" }}
    >
      edgetape<span style={{ color: EDGE }}>.</span>
    </Typography>
  );
}

interface SidebarProps {
  nav: NavItem[];
  active: Phase;
  badge: Partial<Record<Phase, number>>;
  disabled: Partial<Record<Phase, boolean>>;
  onNavigate: (p: Phase) => void;
  onLogout: () => void;
  user: User;
}

function SidebarContent({ nav, active, badge, disabled, onNavigate, onLogout, user }: SidebarProps) {
  return (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Toolbar sx={{ px: 2.5, gap: 1, minHeight: 64 }}>
        <Brand />
      </Toolbar>
      <List sx={{ px: 1.5, flex: 1 }}>
        {nav.map((item) => {
          const disabledHere = disabled[item.phase] === true;
          const count = badge[item.phase];
          return (
            <ListItemButton
              key={item.phase}
              selected={active === item.phase}
              disabled={disabledHere}
              onClick={() => onNavigate(item.phase)}
              sx={{ mb: 0.5, py: 1.1, px: 1.5 }}
            >
              <ListItemIcon sx={{ minWidth: 34, color: active === item.phase ? EDGE : "text.secondary" }}>
                {item.icon}
              </ListItemIcon>
              <ListItemText
                primary={item.label}
                secondary={item.caption}
                slotProps={{
                  primary: {
                    sx: {
                      fontWeight: 600,
                      fontSize: "0.9rem",
                      lineHeight: 1.25,
                      color: disabledHere ? "text.disabled" : "text.primary",
                    },
                  },
                  secondary: { sx: { fontSize: "0.68rem", color: "text.secondary", lineHeight: 1.3 } },
                }}
              />
              {count !== undefined && count > 0 && (
                <Box
                  sx={{
                    minWidth: 20,
                    height: 20,
                    px: 0.5,
                    borderRadius: 1,
                    background: MARK,
                    color: "#14161A",
                    fontFamily: "'Fragment Mono', monospace",
                    fontSize: "0.62rem",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {count}
                </Box>
              )}
            </ListItemButton>
          );
        })}
      </List>
      <Box sx={{ borderTop: "1px solid", borderColor: "divider", px: 2, py: 1.5 }}>
        <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", justifyContent: "space-between" }}>
          <Box sx={{ minWidth: 0 }}>
            <Typography
              variant="body2"
              sx={{ fontWeight: 600, fontSize: "0.82rem", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
            >
              {user.name}
            </Typography>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.6rem" }}
            >
              {user.email}
            </Typography>
          </Box>
          <IconButton size="small" onClick={onLogout} aria-label="salir">
            <LogoutRoundedIcon fontSize="small" />
          </IconButton>
        </Stack>
      </Box>
    </Box>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [phase, setPhase] = useState<Phase>("upload");
  const [job, setJob] = useState<Job | null>(null);
  const [clips, setClips] = useState<Clip[]>([]);
  const [mobileOpen, setMobileOpen] = useState(false);

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
    setMobileOpen(false);
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
    return <Auth onAuth={handleAuth} />;
  }

  const toPublish = clips.filter((c) => c.publish).length;
  const disabled: Partial<Record<Phase, boolean>> = {};
  const badge: Partial<Record<Phase, number>> = {};
  for (const item of NAV) {
    if (item.needsJob && !job) disabled[item.phase] = true;
    if (item.needsSelection && (!job || toPublish === 0)) disabled[item.phase] = true;
  }
  badge.publish = toPublish;
  badge.reel = job ? clips.length : undefined;

  const sidebarProps: SidebarProps = {
    nav: NAV,
    active: phase,
    badge,
    disabled,
    onNavigate: goTo,
    onLogout: logout,
    user,
  };

  const sectionTitle = NAV.find((n) => n.phase === phase)?.label ?? "";

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <Drawer
        variant="permanent"
        open
        sx={{
          width: { md: SIDEBAR_WIDTH },
          display: { xs: "none", md: "block" },
          "& .MuiDrawer-paper": { width: SIDEBAR_WIDTH, boxSizing: "border-box" },
        }}
      >
        <SidebarContent {...sidebarProps} />
      </Drawer>

      <Drawer
        variant="temporary"
        open={mobileOpen}
        onClose={() => setMobileOpen(false)}
        sx={{
          display: { xs: "block", md: "none" },
          "& .MuiDrawer-paper": { width: SIDEBAR_WIDTH, boxSizing: "border-box" },
        }}
      >
        <SidebarContent {...sidebarProps} />
      </Drawer>

      <Box sx={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <Box
          component="header"
          sx={{
            position: "sticky",
            top: 0,
            zIndex: 10,
            background: CARD,
            borderBottom: "1px solid",
            borderColor: "divider",
          }}
        >
          <Toolbar sx={{ gap: 2, px: { xs: 2, md: 3 }, minHeight: 64 }}>
            <IconButton
              edge="start"
              aria-label="abrir menú"
              onClick={() => setMobileOpen(true)}
              sx={{ display: { md: "none" } }}
            >
              <MenuRoundedIcon />
            </IconButton>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="overline" sx={{ display: "block", fontSize: "0.6rem" }}>
                Edgetape — panel de trabajo
              </Typography>
              <Typography variant="h6" sx={{ lineHeight: 1.15, fontSize: "1.05rem" }}>
                {sectionTitle}
              </Typography>
            </Box>
            {job && (
              <Box
                sx={{
                  ml: "auto",
                  display: "flex",
                  alignItems: "center",
                  gap: 1,
                  minWidth: 0,
                }}
              >
                <Typography
                  variant="caption"
                  color="text.secondary"
                  sx={{
                    fontFamily: "'Fragment Mono', monospace",
                    fontSize: "0.64rem",
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    maxWidth: { xs: 120, sm: 220 },
                  }}
                >
                  {job.filename}
                </Typography>
              </Box>
            )}
            <Box sx={{ ml: job ? 1 : "auto", display: { xs: "none", sm: "flex" }, alignItems: "center", gap: 1.5 }}>
              <Typography
                variant="body2"
                sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.72rem" }}
              >
                {user.name}
              </Typography>
              <Button variant="outlined" size="small" onClick={logout} sx={{ borderColor: "divider" }}>
                salir
              </Button>
            </Box>
          </Toolbar>
        </Box>

        <Box component="main" sx={{ flex: 1 }}>
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
        </Box>

        <Box
          component="footer"
          sx={{
            borderTop: "1px solid",
            borderColor: "divider",
            background: CARD,
            px: { xs: 2, md: 3 },
            py: 1.5,
          }}
        >
          <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap" }}>
            <Typography sx={{ fontFamily: "'Fragment Mono', monospace", fontSize: "0.7rem" }}>
              edgetape<span style={{ color: EDGE }}>.</span>
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ ml: "auto" }}>
              Grabaciones largas → los momentos que importan.
            </Typography>
          </Stack>
        </Box>
      </Box>
    </Box>
  );
}
