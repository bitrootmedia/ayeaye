import { useEffect, useRef } from "react";

import type { WorkingHourCell } from "@/lib/types";
import { HOURS, WEEKDAY_LABELS, cellKey, cellSet } from "@/lib/working-hours";

/**
 * A Mon–Sun × 0–23 weekly grid. The same component renders both the
 * editable version (Account) and the read-only version (a colleague's
 * grid on the People roster) — `onToggle`'s presence is what tells them
 * apart, rather than keeping two near-identical grids in sync by hand.
 */
export function WorkingHoursGrid({
  cells,
  onToggle,
  className,
}: {
  cells: WorkingHourCell[];
  onToggle?: (weekday: number, hour: number, value: boolean) => void;
  className?: string;
}) {
  const on = cellSet(cells);

  // Dragging paints every cell the pointer crosses to the value the first
  // cell in the drag was set to, so marking a whole afternoon is one
  // gesture instead of a dozen clicks. Reset on a *window* mouseup, not
  // just the grid's own — releasing outside it should still end the drag,
  // the same "don't trust only the element under the pointer" reasoning
  // `main.tsx` already applies to cancelling a stray file drop.
  const painting = useRef<boolean | null>(null);
  useEffect(() => {
    if (!onToggle) return;
    const stop = () => {
      painting.current = null;
    };
    window.addEventListener("mouseup", stop);
    return () => window.removeEventListener("mouseup", stop);
  }, [onToggle]);

  return (
    <div className={`overflow-x-auto ${className ?? ""}`}>
      <table className="border-separate border-spacing-[3px]">
        <thead>
          <tr>
            <th className="w-9" />
            {HOURS.map((h) => (
              <th
                key={h}
                className="w-4 pb-1 text-center font-mono text-[10px] font-normal text-muted-foreground"
              >
                {h % 3 === 0 ? h : ""}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {WEEKDAY_LABELS.map((label, weekday) => (
            <tr key={weekday}>
              <td className="pr-2 text-right text-xs text-muted-foreground">{label}</td>
              {HOURS.map((hour) => {
                const active = on.has(cellKey(weekday, hour));
                const title = `${label} ${String(hour).padStart(2, "0")}:00${
                  active ? " — working" : ""
                }`;
                const swatch = `size-4 rounded-sm ${active ? "bg-primary" : "bg-muted"}`;
                return (
                  <td key={hour} className="p-0">
                    {onToggle ? (
                      <button
                        type="button"
                        title={title}
                        aria-label={title}
                        aria-pressed={active}
                        className={`${swatch} cursor-pointer`}
                        onMouseDown={() => {
                          const next = !active;
                          painting.current = next;
                          onToggle(weekday, hour, next);
                        }}
                        onMouseEnter={() => {
                          if (painting.current !== null) onToggle(weekday, hour, painting.current);
                        }}
                      />
                    ) : (
                      <div title={title} aria-label={title} className={swatch} />
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
