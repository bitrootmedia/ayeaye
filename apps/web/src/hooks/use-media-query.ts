import * as React from "react"

/** Tracks a CSS media query in JS. Used where a component must render in one
 *  of two different DOM *positions* depending on breakpoint (not just show
 *  or hide) — something Tailwind's own responsive classes can't express,
 *  since a class toggle changes styling, not structure. */
export function useMediaQuery(query: string) {
  const [matches, setMatches] = React.useState(() =>
    typeof window === "undefined" ? false : window.matchMedia(query).matches,
  )

  React.useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    onChange()
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [query])

  return matches
}
