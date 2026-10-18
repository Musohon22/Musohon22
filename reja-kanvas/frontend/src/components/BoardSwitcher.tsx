"use client";

import { api } from "@/lib/api";
import { loadBoards, loadPlans, online, setBoard, useStore, useT } from "@/lib/store";
import type { Board } from "@/lib/types";
import { More } from "./Icons";

export function boardLabel(b: Board, personal: string, team: (n: string) => string) {
  if (b.id === null) return personal;
  return b.team_name ? `${team(b.team_name)} · ${b.name}` : b.name ?? "";
}

/** Pick which canvas you are looking at; create, rename or delete boards you manage. */
export function BoardSwitcher() {
  const t = useT();
  const boards = useStore((s) => s.boards);
  const board = useStore((s) => s.board);
  const current = boards.find((b) => b.id === board) ?? boards[0];
  const canManage = current && current.id !== null && (current.role === "owner" || current.role === "admin");

  async function create() {
    const name = window.prompt(t("board.name"));
    if (!name?.trim()) return;
    const b = await online(() => api.post<Board>("/api/boards", { name: name.trim().slice(0, 60), team_id: current?.team_id ?? null }));
    if (b) {
      await loadBoards();
      setBoard(b.id);
    }
  }

  async function rename() {
    if (!current?.id) return;
    const name = window.prompt(t("board.name"), current.name ?? "");
    if (!name?.trim()) return;
    if (await online(() => api.patch(`/api/boards/${current.id}`, { name: name.trim().slice(0, 60) }))) void loadBoards();
  }

  async function remove() {
    if (!current?.id || !window.confirm(t("board.deleteConfirm"))) return;
    const ok = await online(async () => {
      await api.del(`/api/boards/${current.id}`);
      return true;
    });
    if (ok) {
      setBoard(null);
      await loadBoards();
      void loadPlans();
    }
  }

  return (
    <div className="flex items-center gap-1">
      <label>
        <span className="sr-only">{t("board.switch")}</span>
        <select
          className="field h-10 w-auto max-w-[220px] py-0 text-sm font-bold"
          value={board ?? ""}
          onChange={(e) => (e.target.value === "__new" ? void create() : setBoard(e.target.value || null))}
        >
          {boards.map((b) => (
            <option key={b.id ?? "personal"} value={b.id ?? ""}>{boardLabel(b, t("board.personal"), (n) => t("board.team", { name: n }))}</option>
          ))}
          <option value="__new">+ {t("board.new")}</option>
        </select>
      </label>
      {canManage && (
        <details className="relative">
          <summary aria-label={t("plan.more")} className="btn-icon h-10 w-10 cursor-pointer list-none [&::-webkit-details-marker]:hidden"><More size={16} /></summary>
          <div className="absolute right-0 z-30 mt-1 w-52 rounded-xl border border-line bg-surface p-1 shadow-lift">
            <button type="button" className="h-10 w-full rounded-lg px-3 text-left text-sm font-semibold hover:bg-paper-2" onClick={() => void rename()}>{t("board.rename")}</button>
            <button type="button" className="h-10 w-full rounded-lg px-3 text-left text-sm font-semibold text-warn-strong hover:bg-warn-soft" onClick={() => void remove()}>{t("board.delete")}</button>
          </div>
        </details>
      )}
    </div>
  );
}
