import { useRef, useState } from "react";

import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export type MentionPerson = {
  id: string;
  /** Exactly the text that gets inserted after the `@`, and exactly what the
   *  server matches on — a display name, or the email for somebody who has
   *  never set one. Getting these out of step is what makes a mention look
   *  like it worked and notify nobody. */
  name: string;
  /** Second line, searched as well as shown. An email, usually. */
  hint?: string;
};

/** How much typing after an `@` still counts as looking for a name. Long
 *  enough for "Alexandra Fitzgerald", short enough that a paragraph
 *  beginning with an address doesn't keep a dead list open. */
const MAX_QUERY = 40;
const MAX_SUGGESTIONS = 8;

type Query = { start: number; end: number; text: string };

/**
 * A comment box that can name people.
 *
 * Type `@`, keep typing, choose with ↑↓ and Enter (or Tab, or the mouse).
 * The list is **only ever the people who can see the thing being discussed** —
 * the caller fetches it; see `services/mentions.py` for why it isn't the
 * organisation's roster.
 *
 * Four things here are load-bearing:
 *
 * - **The list renders in flow, below the box, not absolutely positioned.**
 *   `Card` sets `overflow-hidden` unconditionally, so an `absolute` list
 *   inside one is clipped — the exact bug `EntityPicker` had to portal to
 *   escape. Below rather than above so the caret never moves under the
 *   pointer while somebody is mid-word.
 * - **Enter is intercepted while the list is open.** The composer sends on
 *   Enter, so without this, choosing a name posts a comment reading "@ku".
 * - **An option cancels its own `mousedown`.** Otherwise the click blurs the
 *   textarea first, the selection collapses, and the name lands at the
 *   wrong offset — the same trap the rich-text toolbar documents.
 * - **The `@` must start a word.** `bob@example.com` typed mid-sentence is an
 *   address, and offering a list there is noise. The server applies the
 *   identical rule when it resolves what got posted.
 */
export function MentionTextarea({
  people,
  value,
  onValueChange,
  onKeyDown,
  className,
  ...rest
}: {
  people: MentionPerson[];
  value: string;
  onValueChange: (value: string) => void;
} & Omit<React.ComponentProps<"textarea">, "value" | "onChange">) {
  const box = useRef<HTMLTextAreaElement>(null);
  const [query, setQuery] = useState<Query | null>(null);
  const [active, setActive] = useState(0);

  const suggestions = query ? filter(people, query.text).slice(0, MAX_SUGGESTIONS) : [];
  const open = suggestions.length > 0;

  const close = () => {
    setQuery(null);
    setActive(0);
  };

  const retarget = (next: string, caret: number) => {
    const found = activeQuery(next, caret);
    setQuery(found);
    setActive(0);
  };

  const choose = (person: MentionPerson) => {
    if (!query) return;
    const before = value.slice(0, query.start);
    const after = value.slice(query.end);
    const inserted = `@${person.name} `;
    onValueChange(before + inserted + after);
    close();
    // The caret has to follow the text it just wrote, and the value it lands
    // in hasn't rendered yet — so this waits a frame rather than reading
    // `box.current` mid-update.
    const caret = before.length + inserted.length;
    requestAnimationFrame(() => {
      box.current?.focus();
      box.current?.setSelectionRange(caret, caret);
    });
  };

  return (
    <div className="space-y-1">
      <Textarea
        ref={box}
        value={value}
        className={className}
        aria-autocomplete="list"
        aria-expanded={open}
        onChange={(e) => {
          onValueChange(e.target.value);
          retarget(e.target.value, e.target.selectionStart ?? e.target.value.length);
        }}
        onClick={(e) => retarget(value, e.currentTarget.selectionStart ?? value.length)}
        onBlur={close}
        onKeyDown={(e) => {
          if (open) {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setActive((i) => (i + 1) % suggestions.length);
              return;
            }
            if (e.key === "ArrowUp") {
              e.preventDefault();
              setActive((i) => (i - 1 + suggestions.length) % suggestions.length);
              return;
            }
            if (e.key === "Enter" || e.key === "Tab") {
              e.preventDefault();
              choose(suggestions[active]);
              return;
            }
            if (e.key === "Escape") {
              e.preventDefault();
              close();
              return;
            }
          }
          onKeyDown?.(e);
        }}
        {...rest}
      />
      {open && (
        <ul
          role="listbox"
          aria-label="People you can mention"
          className="max-h-44 overflow-y-auto rounded-lg border bg-popover p-1 text-sm shadow-md"
        >
          {suggestions.map((person, i) => (
            <li key={person.id}>
              <button
                type="button"
                role="option"
                aria-selected={i === active}
                className={cn(
                  "flex w-full items-baseline gap-2 rounded-md px-2 py-1.5 text-left",
                  i === active && "bg-accent text-accent-foreground",
                )}
                // Keeps the caret where it was; see the note above.
                onMouseDown={(e) => e.preventDefault()}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(person)}
              >
                <span className="truncate">{person.name}</span>
                {person.hint && (
                  <span className="truncate font-mono text-xs text-muted-foreground">
                    {person.hint}
                  </span>
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The `@…` being typed at the caret, if there is one. */
function activeQuery(value: string, caret: number): Query | null {
  const upto = value.slice(0, caret);
  const start = upto.lastIndexOf("@");
  if (start === -1) return null;
  // Mid-word, so it's an email address rather than somebody's name.
  if (start > 0 && !/\s/.test(upto[start - 1])) return null;
  const text = upto.slice(start + 1);
  if (text.includes("\n") || text.length > MAX_QUERY) return null;
  return { start, end: caret, text };
}

/** Substring, on both the name and the hint — two people called Jan is the
 *  ordinary case, the same reasoning `EntityPicker` gives for searching its
 *  own hint line. */
function filter(people: MentionPerson[], text: string): MentionPerson[] {
  const q = text.trim().toLowerCase();
  if (!q) return people;
  return people.filter(
    (p) => p.name.toLowerCase().includes(q) || p.hint?.toLowerCase().includes(q),
  );
}

/**
 * A comment body with the names in it picked out.
 *
 * Cosmetic only — the server decides what actually counted as a mention when
 * the comment was posted, and this is a second, deliberately simpler reading
 * of the same text. Two consequences worth knowing: a name that was resolved
 * against somebody whose access has since been revoked stops being
 * highlighted (they are no longer a candidate), and nothing here is a link,
 * because this product has no page for a person.
 *
 * Safe by construction rather than by an allow-list, the same reasoning
 * `Linkified` gives on the Sparks screen: every segment is a React text
 * node, so there is no markup to sanitise because none is ever parsed as
 * markup.
 */
export function MentionedText({ body, people }: { body: string; people: MentionPerson[] }) {
  const names = [...people]
    .map((p) => p.name)
    .filter(Boolean)
    .sort((a, b) => b.length - a.length);
  if (names.length === 0) return <>{body}</>;

  const parts: (string | { name: string })[] = [];
  let plain = "";
  let i = 0;
  while (i < body.length) {
    const at = body.indexOf("@", i);
    if (at === -1) break;
    const boundary = at === 0 || /\s/.test(body[at - 1]);
    const name = boundary
      ? names.find((n) => {
          const end = at + 1 + n.length;
          return (
            body.slice(at + 1, end).toLowerCase() === n.toLowerCase() &&
            (end === body.length || !/[\w]/.test(body[end]))
          );
        })
      : undefined;
    if (!name) {
      plain += body.slice(i, at + 1);
      i = at + 1;
      continue;
    }
    plain += body.slice(i, at);
    if (plain) parts.push(plain);
    plain = "";
    parts.push({ name: body.slice(at, at + 1 + name.length) });
    i = at + 1 + name.length;
  }
  plain += body.slice(i);
  if (plain) parts.push(plain);

  return (
    <>
      {parts.map((part, index) =>
        typeof part === "string" ? (
          part
        ) : (
          <span key={index} className="font-medium text-primary">
            {part.name}
          </span>
        ),
      )}
    </>
  );
}
