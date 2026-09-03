import { common, createLowlight } from "lowlight";
import {
  BoldIcon,
  CodeIcon,
  Heading2Icon,
  Heading3Icon,
  ImageIcon,
  ItalicIcon,
  LinkIcon,
  ListIcon,
  ListOrderedIcon,
  QuoteIcon,
  SquareCodeIcon,
  StrikethroughIcon,
} from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import CodeBlockLowlight from "@tiptap/extension-code-block-lowlight";
import Image from "@tiptap/extension-image";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";

import { ApiError, api } from "@/api";
import { Button } from "@/components/ui/button";
import { useToastManager } from "@/components/ui/toast";
import { useFileDrop } from "@/hooks/use-file-drop";
import { putToStorage } from "@/lib/storage";
import { cn } from "@/lib/utils";

/**
 * The task description editor.
 *
 * ## Images are attachments, not URLs
 *
 * Pasting or dropping a picture uploads it through the **same three-step
 * handshake as every other file** and stores only `data-attachment-id` in the
 * body. The server puts a fresh presigned URL on it at read time.
 *
 * That is not indirection for its own sake: a presigned URL expires, so a
 * description that stored one would be full of dead images within the hour.
 * It also means a picture in a description is a task attachment like any
 * other, and turns up in the Files panel without a second mechanism.
 *
 * ## What it can't do
 *
 * No font families, no arbitrary text colours. Colour in this product means
 * one thing — status — and a description that can paint its own text in red
 * is a description that can imitate "blocked". Code blocks are the exception,
 * because there the colour carries syntax rather than importance.
 */

// `common` is ~35 languages rather than all 190: the rest is weight nobody
// on a boatyard's task board is going to spend.
const lowlight = createLowlight(common);

/**
 * The stock Image node knows `src`, `alt` and `title` and **silently drops
 * everything else** on parse and on serialise. Without declaring it here, the
 * attachment id survives exactly until the first round trip through the
 * server and every picture in the description turns into a blank.
 */
const TaskImage = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      "data-attachment-id": {
        default: null,
        parseHTML: (element) => element.getAttribute("data-attachment-id"),
        renderHTML: (attributes) =>
          attributes["data-attachment-id"]
            ? { "data-attachment-id": attributes["data-attachment-id"] }
            : {},
      },
    };
  },
});

/** The subset of `common` offered by name. Anything else still highlights if
 *  the language is auto-detected; this is just what the picker lists. */
const LANGUAGES = [
  "bash",
  "css",
  "diff",
  "go",
  "html",
  "java",
  "javascript",
  "json",
  "markdown",
  // Not a highlighting language lowlight knows — picking it just leaves the
  // block in plain monospace while typing. What it's actually for is the
  // render step: `RichText` turns any `language-mermaid` block into a
  // diagram once the description is saved and viewed.
  "mermaid",
  "php",
  "python",
  "ruby",
  "rust",
  "sql",
  "typescript",
  "yaml",
];

/** The id is what gets stored; the URL is only so you can see it now. */
type Uploaded = { id: string; url: string };
type Uploader = (file: File) => Promise<Uploaded | null>;

function useImageUploader(orgId: string, basePath: string): [Uploader, boolean] {
  const toast = useToastManager();
  const [busy, setBusy] = useState(false);

  const upload: Uploader = async (file) => {
    setBusy(true);
    try {
      const ticket = await api<{
        attachment: { id: string };
        upload_url: string;
        content_type: string;
      }>(`${basePath}/files`, {
        method: "POST",
        body: JSON.stringify({ filename: file.name, content_type: file.type }),
      });
      // The signed type, not the browser's — SigV4 covers Content-Type byte
      // for byte and the server normalised it.
      await putToStorage(ticket.upload_url, file, ticket.content_type);
      // Confirm hands back a presigned URL. **Use it** — without a `src` the
      // picture you just added renders as its own alt text until the first
      // save, which reads as a failed upload rather than a working one.
      const ready = await api<{ id: string; url: string }>(
        `/organisations/${orgId}/attachments/${ticket.attachment.id}/confirm`,
        { method: "POST" },
      );
      return { id: ready.id, url: ready.url };
    } catch (err) {
      const detail =
        err instanceof ApiError ? (JSON.parse(err.body).detail as string) : "Try again.";
      toast.add({ title: `Couldn't add ${file.name}`, description: detail });
      return null;
    } finally {
      setBusy(false);
    }
  };

  return [upload, busy];
}

export function RichTextEditor({
  orgId,
  basePath,
  value,
  onChange,
  onImageAdded,
  noun = "task",
}: {
  orgId: string;
  /** The resource's own base path — `/organisations/{orgId}/tasks/{taskId}`
   *  or `/organisations/{orgId}/kb/revisions/{revisionId}` — the same
   *  one-prop generalisation `AccessPanel`'s `basePath` already established.
   *  A pasted or dropped image is staged at `${basePath}/files`. */
  basePath: string;
  value: string;
  onChange: (html: string) => void;
  /** So the Files panel picks up a pasted screenshot without a reload. */
  onImageAdded?: () => void;
  /** What to call the thing this editor is attached to, in the hint text
   *  below the toolbar — "task" or "article". */
  noun?: string;
}) {
  const [upload, uploading] = useImageUploader(orgId, basePath);

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        // Replaced below by the highlighting one; leaving both registers the
        // same node twice and Tiptap throws.
        codeBlock: false,
        heading: { levels: [2, 3] },
      }),
      CodeBlockLowlight.configure({ lowlight }),
      TaskImage.configure({ allowBase64: false }),
    ],
    content: value || "",
    editorProps: {
      attributes: {
        class:
          "prose-task min-h-32 rounded-lg border bg-transparent px-3 py-2 outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50",
      },
      // Pasting a screenshot is how most images get into a description, so it
      // is handled at the same level as dropping one.
      handlePaste(_view, event) {
        const files = Array.from(event.clipboardData?.files ?? []);
        if (!files.length) return false;
        event.preventDefault();
        void addImages(files);
        return true;
      },
    },
    onUpdate: ({ editor }) => onChange(editor.getHTML()),
  });

  const addImages = async (files: File[]) => {
    for (const file of files) {
      if (!file.type.startsWith("image/")) continue;
      const added = await upload(file);
      if (!added || !editor) continue;
      // **The id is what gets stored; the URL is only so you can see it.**
      // `sanitise()` drops `src` on write and the server puts a fresh one
      // back on every read — a presigned URL in the body would be a dead
      // link within the hour. This copy is for the next few minutes of
      // editing, and is why the picture appears the moment it uploads.
      editor
        .chain()
        .focus()
        .insertContent({
          type: "image",
          attrs: { src: added.url, alt: file.name, "data-attachment-id": added.id },
        })
        .run();
      onChange(editor.getHTML());
      onImageAdded?.();
    }
  };

  const { dragging, dropProps } = useFileDrop((files) => void addImages(files), uploading);

  // The editor is created once; a value arriving late (the task loads after
  // mount) has to be pushed in, but *only* when it differs — setting content
  // on every render would move the cursor to the start on every keystroke.
  const applied = useRef(value);
  useEffect(() => {
    if (!editor || value === applied.current) return;
    applied.current = value;
    if (value !== editor.getHTML()) editor.commands.setContent(value || "", { emitUpdate: false });
  }, [editor, value]);

  if (!editor) return null;

  return (
    <div
      className={cn("space-y-2 rounded-lg", dragging && "ring-2 ring-primary")}
      {...dropProps}
    >
      <Toolbar editor={editor} onPickImage={(files) => void addImages(files)} busy={uploading} />
      <EditorContent editor={editor} />
      <p className="text-xs text-muted-foreground">
        {dragging
          ? "Drop to add the picture"
          : `Paste or drop a picture to add it. Pictures become files on this ${noun}.`}
      </p>
    </div>
  );
}

function Toolbar({
  editor,
  onPickImage,
  busy,
}: {
  editor: Editor;
  onPickImage: (files: File[]) => void;
  busy: boolean;
}) {
  const picker = useRef<HTMLInputElement>(null);
  // Subscribing to the editor's own state, so a button lights up when the
  // cursor moves into what it applies — not only when it is clicked.
  const [, force] = useState(0);
  useEffect(() => {
    const rerender = () => force((n) => n + 1);
    editor.on("selectionUpdate", rerender);
    editor.on("transaction", rerender);
    return () => {
      editor.off("selectionUpdate", rerender);
      editor.off("transaction", rerender);
    };
  }, [editor]);

  const item = (
    label: string,
    icon: React.ReactNode,
    active: boolean,
    run: () => void,
  ) => (
    <Button
      key={label}
      type="button"
      size="icon-sm"
      variant={active ? "secondary" : "ghost"}
      aria-label={label}
      aria-pressed={active}
      // **Don't take focus off the text.** Clicking a toolbar button
      // otherwise blurs the editor and the chain's `.focus()` puts it back a
      // tick later — long enough to swallow the first character you type
      // afterwards, and to make the selection flicker while you aim.
      onMouseDown={(event) => event.preventDefault()}
      onClick={run}
    >
      {icon}
    </Button>
  );

  return (
    <div className="flex flex-wrap items-center gap-0.5 rounded-lg border bg-muted/40 p-1">
      {item("Bold", <BoldIcon />, editor.isActive("bold"), () =>
        editor.chain().focus().toggleBold().run(),
      )}
      {item("Italic", <ItalicIcon />, editor.isActive("italic"), () =>
        editor.chain().focus().toggleItalic().run(),
      )}
      {item("Strikethrough", <StrikethroughIcon />, editor.isActive("strike"), () =>
        editor.chain().focus().toggleStrike().run(),
      )}
      {item("Inline code", <CodeIcon />, editor.isActive("code"), () =>
        editor.chain().focus().toggleCode().run(),
      )}
      <span className="mx-1 h-5 w-px bg-border" />
      {item("Heading", <Heading2Icon />, editor.isActive("heading", { level: 2 }), () =>
        editor.chain().focus().toggleHeading({ level: 2 }).run(),
      )}
      {item("Subheading", <Heading3Icon />, editor.isActive("heading", { level: 3 }), () =>
        editor.chain().focus().toggleHeading({ level: 3 }).run(),
      )}
      {item("Bullet list", <ListIcon />, editor.isActive("bulletList"), () =>
        editor.chain().focus().toggleBulletList().run(),
      )}
      {item("Numbered list", <ListOrderedIcon />, editor.isActive("orderedList"), () =>
        editor.chain().focus().toggleOrderedList().run(),
      )}
      {item("Quote", <QuoteIcon />, editor.isActive("blockquote"), () =>
        editor.chain().focus().toggleBlockquote().run(),
      )}
      {item("Code block", <SquareCodeIcon />, editor.isActive("codeBlock"), () =>
        editor.chain().focus().toggleCodeBlock().run(),
      )}
      {item("Link", <LinkIcon />, editor.isActive("link"), () => {
        const href = window.prompt("Link to");
        if (!href) return;
        editor.chain().focus().extendMarkRange("link").setMark("link", { href }).run();
      })}
      <span className="mx-1 h-5 w-px bg-border" />
      {item("Add a picture", <ImageIcon />, false, () => picker.current?.click())}
      {editor.isActive("codeBlock") && (
        <select
          aria-label="Code language"
          onMouseDown={(event) => event.stopPropagation()}
          className="ml-1 h-7 rounded-md border bg-background px-1 text-xs"
          value={editor.getAttributes("codeBlock").language ?? ""}
          onChange={(e) =>
            editor.chain().focus().updateAttributes("codeBlock", { language: e.target.value }).run()
          }
        >
          <option value="">Detect</option>
          {LANGUAGES.map((language) => (
            <option key={language} value={language}>
              {language}
            </option>
          ))}
        </select>
      )}
      {busy && <span className="ml-1 text-xs text-muted-foreground">Uploading…</span>}
      <input
        ref={picker}
        type="file"
        accept="image/*"
        multiple
        className="sr-only"
        aria-label="Picture to add"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = "";
          if (files.length) onPickImage(files);
        }}
      />
    </div>
  );
}

/**
 * A stored description, rendered.
 *
 * `dangerouslySetInnerHTML` is safe here **only because the server sanitises
 * on write** — an allow-list, applied to everything that gets stored, not to
 * what the editor happens to produce. Do not use this on anything that hasn't
 * been through `services/richtext.py`.
 */
export function RichText({ html, className }: { html: string; className?: string }) {
  // Descriptions written before the editor existed are plain text. Rendering
  // those as HTML would collapse every line break, so they keep their shape.
  const looksLikeHtml = html.includes("<");
  const parts = useMemo(() => (looksLikeHtml ? splitOnMermaidBlocks(html) : []), [html, looksLikeHtml]);

  if (!looksLikeHtml) {
    return <p className={cn("text-sm whitespace-pre-wrap", className)}>{html}</p>;
  }

  // The common case — no diagram in this description — stays exactly the
  // single dangerouslySetInnerHTML it always was, rather than an unnecessary
  // wrapper around one child.
  if (parts.length === 1 && parts[0].kind === "html") {
    return (
      <div
        className={cn("prose-task", className)}
        dangerouslySetInnerHTML={{ __html: parts[0].content }}
      />
    );
  }

  return (
    <div className={cn("prose-task", className)}>
      {parts.map((part, i) =>
        part.kind === "mermaid" ? (
          <MermaidDiagram key={i} source={part.content} />
        ) : (
          <div key={i} dangerouslySetInnerHTML={{ __html: part.content }} />
        ),
      )}
    </div>
  );
}

/**
 * Splits sanitised HTML on `<pre><code class="language-mermaid">…</code></pre>`
 * blocks — the fenced-code shape `services/richtext.py`'s `sanitise()` and
 * `from_markdown()` both already produce for a ```mermaid``` block, no
 * backend change needed. Everything else stays exactly the HTML the server
 * sent, split into fragments only where a diagram needs to interrupt it.
 */
const MERMAID_BLOCK = /<pre><code class="language-mermaid">([\s\S]*?)<\/code><\/pre>/g;

type Part = { kind: "html" | "mermaid"; content: string };

function splitOnMermaidBlocks(html: string): Part[] {
  const parts: Part[] = [];
  let lastIndex = 0;
  MERMAID_BLOCK.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = MERMAID_BLOCK.exec(html))) {
    if (match.index > lastIndex) {
      parts.push({ kind: "html", content: html.slice(lastIndex, match.index) });
    }
    parts.push({ kind: "mermaid", content: decodeHtmlEntities(match[1]) });
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < html.length || parts.length === 0) {
    parts.push({ kind: "html", content: html.slice(lastIndex) });
  }
  return parts;
}

/** `sanitise()` HTML-escapes text inside `<code>`, same as any browser would
 *  when it puts text in an element — reverse that to get mermaid's own DSL
 *  back before handing it to the renderer. A plain, inert `<textarea>` is
 *  the standard trick: setting `innerHTML` decodes entities, and a textarea
 *  never executes anything it's given regardless of content. */
function decodeHtmlEntities(text: string): string {
  const el = document.createElement("textarea");
  el.innerHTML = text;
  return el.value;
}

/**
 * One diagram, rendered from mermaid's own text DSL.
 *
 * Dynamically imported — mermaid is a few hundred KB, and most descriptions
 * never use it, so the common case shouldn't pay for a library it never
 * loads. Rendered with `securityLevel: "strict"`: mermaid's DSL supports
 * `click` directives that can otherwise run arbitrary JS or navigate on
 * click, and a diagram's source is exactly as untrusted as anything else
 * that arrived through `sanitise()` — "the client is never trusted" applies
 * here too, not just to the surrounding HTML.
 */
function MermaidDiagram({ source }: { source: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const rawId = useId().replace(/[^a-zA-Z0-9]/g, "");
  const isDark = useIsDarkMode();

  useEffect(() => {
    let cancelled = false;
    setError(null);
    (async () => {
      try {
        const { default: mermaid } = await import("mermaid");
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: isDark ? "dark" : "neutral",
        });
        const { svg } = await mermaid.render(`mermaid-${rawId}`, source.trim());
        if (!cancelled && ref.current) ref.current.innerHTML = svg;
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Couldn't render this diagram.");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source, rawId, isDark]);

  if (error) {
    return (
      <div className="my-2 rounded-lg border border-dashed p-3 text-xs text-muted-foreground">
        This diagram couldn&rsquo;t be rendered: {error}
      </div>
    );
  }
  return <div ref={ref} className="my-2 flex justify-center overflow-x-auto [&_svg]:max-w-full" />;
}

/** `useTheme` (lib/theme.ts) owns the toggle button's own state, but a
 *  second component can't read it — it's a separate `useState`, not
 *  context, so a diagram rendered before a toggle click never hears about
 *  it. Observing the `.dark` class `useTheme` itself sets on `<html>` is
 *  what lets an already-rendered diagram redraw in the theme it's actually
 *  being viewed in, instead of freezing in whatever was current at mount. */
function useIsDarkMode(): boolean {
  const [isDark, setIsDark] = useState(() => document.documentElement.classList.contains("dark"));
  useEffect(() => {
    const el = document.documentElement;
    const observer = new MutationObserver(() => setIsDark(el.classList.contains("dark")));
    observer.observe(el, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return isDark;
}
