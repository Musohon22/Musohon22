"use client";

import { useEffect, useRef, useState } from "react";
import { EditorContent, useEditor, type Editor as TipTap } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Underline from "@tiptap/extension-underline";
import Highlight from "@tiptap/extension-highlight";
import Link from "@tiptap/extension-link";
import TaskList from "@tiptap/extension-task-list";
import TaskItem from "@tiptap/extension-task-item";
import TextStyle from "@tiptap/extension-text-style";
import Color from "@tiptap/extension-color";
import Placeholder from "@tiptap/extension-placeholder";
import { t as translate, toast, useT } from "@/lib/store";
import { LinkIcon, ListIcon, Quote, Redo, Tasks, Undo } from "../Icons";

const COLORS = ["#1B1D22", "#E8590C", "#1E44D6", "#12804A", "#7D3AC1"];

/** Word-like pasting without Word's baggage: styles, classes and Office markup are dropped. */
function cleanPaste(html: string): string {
  let droppedImages = false;
  const cleaned = html
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<\/?(o|w|v|m):[^>]*>/gi, "")
    .replace(/<img[^>]*>/gi, () => {
      droppedImages = true;
      return "";
    })
    .replace(/\s(class|style|lang|id)=("[^"]*"|'[^']*'|[^\s>]+)/gi, "");
  if (droppedImages) setTimeout(() => toast(translate("ed.imagesDropped")), 0);
  return cleaned;
}

function Btn({ label, active, onClick, children }: { label: string; active?: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={active}
      onMouseDown={(e) => e.preventDefault()}
      onClick={onClick}
      className={`flex h-9 min-w-9 items-center justify-center rounded-lg px-1.5 text-[15px] ${active ? "bg-accent-soft text-accent-ink" : "text-ink-2 hover:bg-paper-3"}`}
    >
      {children}
    </button>
  );
}

function Sep() {
  return <span aria-hidden="true" className="mx-1 h-6 w-px bg-line" />;
}

export function Editor({
  html, editable, onChange, placeholder,
}: {
  html: string;
  editable: boolean;
  onChange: (html: string) => void;
  placeholder: string;
}) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const editor = useEditor({
    immediatelyRender: false,
    editable,
    content: html,
    extensions: [
      StarterKit.configure({ heading: { levels: [1, 2, 3] } }),
      Underline,
      Highlight.configure({ multicolor: false }),
      Link.configure({ openOnClick: false, autolink: true, protocols: ["http", "https", "mailto"], HTMLAttributes: { rel: "noopener noreferrer nofollow", target: "_blank" } }),
      TaskList,
      TaskItem.configure({ nested: true }),
      TextStyle,
      Color,
      Placeholder.configure({ placeholder }),
    ],
    editorProps: {
      attributes: { class: "prose-plan min-h-[220px]", "aria-label": placeholder, role: "textbox", "aria-multiline": "true" },
      transformPastedHTML: cleanPaste,
    },
    onUpdate: ({ editor }) => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => onChangeRef.current(editor.getHTML()), 700);
    },
    onBlur: ({ editor }) => {
      if (timer.current) {
        clearTimeout(timer.current);
        timer.current = null;
        onChangeRef.current(editor.getHTML());
      }
    },
  });

  // Save pending text when leaving the page.
  useEffect(
    () => () => {
      if (timer.current && editor) {
        clearTimeout(timer.current);
        onChangeRef.current(editor.getHTML());
      }
    },
    [editor],
  );

  useEffect(() => {
    editor?.setEditable(editable);
  }, [editor, editable]);

  // Server copy changed (another device, conflict resolution): refresh unless the user is typing here.
  useEffect(() => {
    if (editor && !editor.isFocused && !timer.current && editor.getHTML() !== html) {
      editor.commands.setContent(html, false);
    }
  }, [editor, html]);

  return (
    <div className="flex flex-col gap-3">
      {editable && editor && <Toolbar editor={editor} />}
      <EditorContent editor={editor} />
    </div>
  );
}

function Toolbar({ editor }: { editor: TipTap }) {
  const t = useT();
  const [linkOpen, setLinkOpen] = useState(false);
  const [url, setUrl] = useState("");
  const [, force] = useState(0);

  useEffect(() => {
    const update = () => force((n) => n + 1);
    editor.on("selectionUpdate", update);
    editor.on("transaction", update);
    return () => {
      editor.off("selectionUpdate", update);
      editor.off("transaction", update);
    };
  }, [editor]);

  const chain = () => editor.chain().focus();
  const style = editor.isActive("heading", { level: 1 }) ? "h1" : editor.isActive("heading", { level: 2 }) ? "h2" : editor.isActive("heading", { level: 3 }) ? "h3" : "p";

  function applyLink() {
    const href = url.trim();
    if (!href) chain().unsetLink().run();
    else chain().extendMarkRange("link").setLink({ href: /^(https?:|mailto:)/i.test(href) ? href : `https://${href}` }).run();
    setLinkOpen(false);
  }

  return (
    <div role="toolbar" aria-label={t("ed.toolbar")} className="sticky top-0 z-10 -mx-2 flex flex-wrap items-center gap-0.5 rounded-xl border border-line bg-white/95 p-1 backdrop-blur">
      <Btn label={t("ed.undo")} onClick={() => chain().undo().run()}><Undo size={17} /></Btn>
      <Btn label={t("ed.redo")} onClick={() => chain().redo().run()}><Redo size={17} /></Btn>
      <Sep />
      <label>
        <span className="sr-only">{t("ed.style")}</span>
        <select
          value={style}
          onChange={(e) => {
            const v = e.target.value;
            if (v === "p") chain().setParagraph().run();
            else chain().setHeading({ level: Number(v[1]) as 1 | 2 | 3 }).run();
          }}
          className="h-9 rounded-lg border border-line bg-paper-2 px-2 text-sm font-semibold"
        >
          <option value="p">{t("ed.paragraph")}</option>
          <option value="h1">{t("ed.h1")}</option>
          <option value="h2">{t("ed.h2")}</option>
          <option value="h3">{t("ed.h3")}</option>
        </select>
      </label>
      <Sep />
      <Btn label={t("ed.bold")} active={editor.isActive("bold")} onClick={() => chain().toggleBold().run()}><b>B</b></Btn>
      <Btn label={t("ed.italic")} active={editor.isActive("italic")} onClick={() => chain().toggleItalic().run()}><i className="font-serif">I</i></Btn>
      <Btn label={t("ed.underline")} active={editor.isActive("underline")} onClick={() => chain().toggleUnderline().run()}><u>U</u></Btn>
      <Btn label={t("ed.strike")} active={editor.isActive("strike")} onClick={() => chain().toggleStrike().run()}><s>S</s></Btn>
      <Btn label={t("ed.highlight")} active={editor.isActive("highlight")} onClick={() => chain().toggleHighlight().run()}>
        <span className="h-4 w-4 rounded border border-[#E2C658] bg-[#FFE07A]" />
      </Btn>
      <span className="flex items-center gap-0.5" role="group" aria-label={t("ed.color")}>
        {COLORS.map((c) => (
          <button
            key={c}
            type="button"
            aria-label={`${t("ed.color")} ${c}`}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => (c === COLORS[0] ? chain().unsetColor().run() : chain().setColor(c).run())}
            className="flex h-9 w-6 items-center justify-center"
          >
            <span className="h-4 w-4 rounded-full ring-1 ring-black/10" style={{ background: c }} />
          </button>
        ))}
      </span>
      <Sep />
      <Btn label={t("ed.bullet")} active={editor.isActive("bulletList")} onClick={() => chain().toggleBulletList().run()}><ListIcon size={17} /></Btn>
      <Btn label={t("ed.ordered")} active={editor.isActive("orderedList")} onClick={() => chain().toggleOrderedList().run()}>
        <span className="font-mono text-xs font-bold">1.</span>
      </Btn>
      <Btn label={t("ed.tasks")} active={editor.isActive("taskList")} onClick={() => chain().toggleTaskList().run()}><Tasks size={17} /></Btn>
      <Btn label={t("ed.quote")} active={editor.isActive("blockquote")} onClick={() => chain().toggleBlockquote().run()}><Quote size={17} /></Btn>
      <span className="relative">
        <Btn
          label={t("ed.link")}
          active={editor.isActive("link")}
          onClick={() => {
            setUrl(editor.getAttributes("link").href ?? "");
            setLinkOpen((o) => !o);
          }}
        >
          <LinkIcon size={17} />
        </Btn>
        {linkOpen && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              applyLink();
            }}
            className="absolute left-0 top-11 z-20 flex w-72 gap-1 rounded-xl border border-line bg-white p-2 shadow-lift"
          >
            <label className="flex-1">
              <span className="sr-only">{t("ed.link")}</span>
              <input autoFocus className="field h-9" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…" onKeyDown={(e) => e.key === "Escape" && setLinkOpen(false)} />
            </label>
            <button className="btn-primary h-9 px-3">{t("ed.linkApply")}</button>
            {editor.isActive("link") && (
              <button type="button" className="btn h-9 px-2" onClick={() => { chain().unsetLink().run(); setLinkOpen(false); }}>{t("ed.unlink")}</button>
            )}
          </form>
        )}
      </span>
    </div>
  );
}
