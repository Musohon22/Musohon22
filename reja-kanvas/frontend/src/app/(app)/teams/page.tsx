"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { errorText, loadBoards, loadPlans, online, setBoard, useStore, useT } from "@/lib/store";
import type { Board, Team, TeamRole } from "@/lib/types";
import { Plus, X } from "@/components/Icons";

const ROLES: TeamRole[] = ["owner", "admin", "member", "viewer"];

export default function TeamsPage() {
  const t = useT();
  const router = useRouter();
  const me = useStore((s) => s.user)!;
  const boards = useStore((s) => s.boards);
  const [teams, setTeams] = useState<Team[] | null>(null);
  const [name, setName] = useState("");
  const [invite, setInvite] = useState<Record<string, { email: string; role: TeamRole; error?: string }>>({});

  const load = useCallback(() => {
    api.get<{ teams: Team[] }>("/api/teams").then((r) => setTeams(r.teams)).catch(() => setTeams((x) => x ?? []));
  }, []);
  useEffect(load, [load]);

  const replace = (team: Team) => setTeams((list) => list?.map((x) => (x.id === team.id ? team : x)) ?? null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const team = await online(() => api.post<Team>("/api/teams", { name: name.trim() }));
    if (team) {
      setTeams((list) => [...(list ?? []), team]);
      setName("");
      void loadBoards();
    }
  }

  async function add(team: Team) {
    const form = invite[team.id];
    if (!form?.email.trim()) return;
    try {
      replace(await api.post<Team>(`/api/teams/${team.id}/members`, { email: form.email.trim(), role: form.role }));
      setInvite({ ...invite, [team.id]: { email: "", role: "member" } });
    } catch (err) {
      setInvite({ ...invite, [team.id]: { ...form, error: errorText(err) } });
    }
  }

  async function setRole(team: Team, userId: string, role: TeamRole) {
    const out = await online(() => api.patch<Team>(`/api/teams/${team.id}/members/${userId}`, { role }));
    if (out) replace(out);
  }

  async function remove(team: Team, userId: string) {
    const ok = await online(async () => {
      await api.del(`/api/teams/${team.id}/members/${userId}`);
      return true;
    });
    if (ok) {
      if (userId === me.id) {
        setTeams((list) => list?.filter((x) => x.id !== team.id) ?? null);
        void loadBoards();
        void loadPlans();
      } else load();
    }
  }

  async function destroy(team: Team) {
    if (!window.confirm(t("teams.deleteConfirm"))) return;
    const ok = await online(async () => {
      await api.del(`/api/teams/${team.id}`);
      return true;
    });
    if (ok) {
      setTeams((list) => list?.filter((x) => x.id !== team.id) ?? null);
      setBoard(null);
      void loadBoards();
      void loadPlans();
    }
  }

  const teamBoards = (team: Team): Board[] => boards.filter((b) => b.team_id === team.id);

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-4 py-8 sm:px-6">
      <div>
        <h1 className="font-display text-3xl font-extrabold tracking-tight">{t("teams.title")}</h1>
        <p className="mt-1 text-ink-3">{t("teams.lead")}</p>
      </div>
      <form onSubmit={create} className="flex gap-2">
        <label className="flex-1">
          <span className="sr-only">{t("teams.name")}</span>
          <input className="field" maxLength={60} placeholder={t("teams.name")} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <button className="btn-primary" disabled={!name.trim()}><Plus size={16} />{t("teams.new")}</button>
      </form>
      {teams?.length === 0 && <p className="rounded-2xl border border-dashed border-line-strong p-8 text-center text-ink-muted">{t("teams.empty")}</p>}
      {teams?.map((team) => {
        const admin = team.my_role === "owner" || team.my_role === "admin";
        const form = invite[team.id] ?? { email: "", role: "member" as TeamRole };
        return (
          <section key={team.id} className="flex flex-col gap-4 rounded-2xl border border-line bg-surface p-5">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="mr-auto font-display text-xl font-bold">{team.name}</h2>
              <span className="chip bg-paper-3 text-ink-3">{t(`role.${team.my_role}`)}</span>
              {teamBoards(team).map((b) => (
                <button key={b.id} type="button" className="btn h-9 px-3" onClick={() => { setBoard(b.id); router.push("/canvas"); }}>
                  {t("teams.openBoard")}: {b.name}
                </button>
              ))}
            </div>
            <ul className="flex flex-col divide-y divide-line-soft">
              {team.members.map((m) => (
                <li key={m.id} className="flex flex-wrap items-center gap-3 py-2.5">
                  <span className="flex h-9 w-9 flex-none items-center justify-center rounded-full bg-[#9FC3FF] text-sm font-extrabold text-[#0E2A66]">{m.name.slice(0, 1).toUpperCase()}</span>
                  <span className="min-w-0 flex-1">
                    <span className={`block truncate ${m.id === me.id ? "font-extrabold" : "font-semibold"}`}>{m.name}</span>
                    <span className="text-xs text-ink-muted">{m.email}</span>
                  </span>
                  {admin && m.role !== "owner" && m.id !== me.id ? (
                    <label>
                      <span className="sr-only">{t("teams.role")}</span>
                      <select className="field h-9 w-auto py-0 text-sm" value={m.role} onChange={(e) => void setRole(team, m.id, e.target.value as TeamRole)}>
                        {ROLES.filter((r) => team.my_role === "owner" || (r !== "owner" && r !== "admin")).map((r) => <option key={r} value={r}>{t(`role.${r}`)}</option>)}
                      </select>
                    </label>
                  ) : (
                    <span className="text-sm text-ink-3">{t(`role.${m.role}`)}</span>
                  )}
                  {admin && m.role !== "owner" && m.id !== me.id && (
                    <button type="button" className="btn-icon h-9 w-9" aria-label={t("teams.remove", { name: m.name })} onClick={() => void remove(team, m.id)}><X size={16} /></button>
                  )}
                </li>
              ))}
            </ul>
            {admin && (
              <form onSubmit={(e) => { e.preventDefault(); void add(team); }} className="flex flex-col gap-2">
                <div className="flex flex-wrap gap-2">
                  <label className="min-w-0 flex-1 basis-56">
                    <span className="sr-only">{t("auth.email")}</span>
                    <input type="email" className="field" placeholder={t("people.placeholder")} value={form.email} onChange={(e) => setInvite({ ...invite, [team.id]: { ...form, email: e.target.value, error: undefined } })} />
                  </label>
                  <label>
                    <span className="sr-only">{t("teams.role")}</span>
                    <select className="field w-auto" value={form.role} onChange={(e) => setInvite({ ...invite, [team.id]: { ...form, role: e.target.value as TeamRole } })}>
                      {(["member", "viewer", "admin"] as TeamRole[]).map((r) => <option key={r} value={r}>{t(`role.${r}`)}</option>)}
                    </select>
                  </label>
                  <button className="btn-dark" disabled={!form.email.trim()}>{t("teams.add")}</button>
                </div>
                <span className="text-xs text-ink-muted">{t("teams.addHint")}</span>
                {form.error && <span role="alert" className="text-sm font-semibold text-warn-strong">{form.error}</span>}
              </form>
            )}
            <div className="flex gap-3 border-t border-line-soft pt-3 text-sm font-semibold">
              {team.my_role !== "owner" && <button type="button" className="text-warn-strong underline" onClick={() => void remove(team, me.id)}>{t("teams.leave")}</button>}
              {team.my_role === "owner" && <button type="button" className="text-warn-strong underline" onClick={() => void destroy(team)}>{t("teams.delete")}</button>}
            </div>
          </section>
        );
      })}
    </main>
  );
}
