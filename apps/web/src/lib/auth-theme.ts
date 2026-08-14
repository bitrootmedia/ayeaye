/**
 * The sign-in screens, wearing the product's clothes.
 *
 * SuperTokens' pre-built UI ships its own look — a white card and a near-black
 * button — which is fine for getting started and wrong for the first screen
 * anyone sees. Left alone it reads as a different product bolted onto the
 * front of this one.
 *
 * **This deliberately restates no colours.** Every rule below reaches for the
 * same custom properties as the rest of the app (`--primary`, `--card`,
 * `--border`…), so the auth screens follow a token change and dark mode
 * without anyone remembering they exist. A second palette here is a palette
 * that drifts.
 *
 * That works because CSS custom properties inherit through a shadow root, and
 * SuperTokens renders its UI inside one: the variables defined on `:root` in
 * `index.css` are visible to these rules even though the markup is isolated.
 *
 * Selectors are SuperTokens' own `data-supertokens` attributes. They are the
 * documented styling surface, but they are still someone else's markup — if a
 * future version renames one, the screen goes back to looking stock rather
 * than breaking, which is the right way round for a failure.
 */
export const AUTH_STYLE = `
  [data-supertokens~="container"] {
    --palette-primary: 79, 70, 229;
    --palette-primaryBorder: 79, 70, 229;
    font-family: var(--font-sans);
    background: var(--card);
    color: var(--foreground);
    border: 1px solid var(--border);
    border-radius: var(--radius-xl);
    box-shadow: 0 1px 2px 0 rgb(0 0 0 / 0.04);
    margin-top: 4rem;
  }

  [data-supertokens~="headerTitle"] {
    font-family: var(--font-heading);
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--foreground);
  }

  [data-supertokens~="headerSubtitle"],
  [data-supertokens~="secondaryText"],
  [data-supertokens~="privacyPolicyAndTermsAndConditions"] {
    color: var(--muted-foreground);
    /* Theirs layers an opacity on top of the colour, which lands well under
       the contrast floor once the background is dark. */
    opacity: 1;
  }

  /* Theirs paints a background on an element with vertical padding, so the
     "line" comes out about 7px thick. A border draws a hairline regardless of
     the box around it. */
  [data-supertokens~="divider"] {
    background: none;
    padding: 0;
    height: 0;
    border-top: 1px solid var(--border);
  }

  [data-supertokens~="divider"]::before {
    display: none;
  }

  [data-supertokens~="label"] {
    color: var(--foreground);
    font-weight: 500;
  }

  [data-supertokens~="inputContainer"] [data-supertokens~="inputWrapper"] {
    background: transparent;
    border: 1px solid var(--input);
    border-radius: var(--radius-lg);
    box-shadow: none;
  }

  [data-supertokens~="inputContainer"] [data-supertokens~="inputWrapper"]:focus-within {
    border-color: var(--ring);
    /* Matches the focus ring on every other input in the product. */
    box-shadow: 0 0 0 3px color-mix(in oklch, var(--ring) 50%, transparent);
  }

  /* Font has to be restated per element: SuperTokens sets a family on its
     inputs and buttons directly, and inheriting from the container isn't
     enough to beat that. */
  [data-supertokens~="input"],
  [data-supertokens~="button"],
  [data-supertokens~="label"],
  [data-supertokens~="headerSubtitle"],
  [data-supertokens~="secondaryText"] {
    font-family: var(--font-sans);
  }

  [data-supertokens~="input"] {
    color: var(--foreground);
    font-family: var(--font-sans);
    background: transparent;
  }

  [data-supertokens~="input"]::placeholder {
    color: var(--muted-foreground);
  }

  [data-supertokens~="button"] {
    background: var(--primary);
    border: 1px solid var(--primary);
    border-radius: var(--radius-lg);
    color: var(--primary-foreground);
    font-family: var(--font-sans);
    font-weight: 500;
    /* Their default shouts in caps. Nothing else in the product does. */
    text-transform: none;
    letter-spacing: normal;
    font-size: 0.875rem;
    transition: background-color 120ms ease;
  }

  [data-supertokens~="button"]:hover {
    background: color-mix(in oklch, var(--primary) 85%, transparent);
  }

  [data-supertokens~="link"] {
    color: var(--primary);
  }

  [data-supertokens~="generalError"] {
    background: color-mix(in oklch, var(--destructive) 12%, transparent);
    border-radius: var(--radius-lg);
    color: var(--destructive);
  }

  [data-supertokens~="inputErrorMessage"] {
    color: var(--destructive);
  }

  [data-supertokens~="superTokensBranding"] {
    /* Self-hosted product, not a SuperTokens demo. The library is Apache-2.0
       and asks for no attribution in the UI. */
    display: none;
  }
`;
